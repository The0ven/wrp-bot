from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import registration_store as rs
from registration_logic import ActionError
from registration_service import NO_MENTIONS, STALE, RegistrationService
from registration_settings import RegistrationSettings
from tracker_client import TrackerError

SETTINGS = RegistrationSettings()
GUILD_ID = 100
MEMBER_ID = 200
FAITH_ROLE = 301
CONTINENT_ROLE = 302


class FakeRole:
    def __init__(self, id, name, position=10):
        self.id = id
        self.name = name
        self.position = position


def forbidden():
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Access")


class FakeMember:
    def __init__(self, id, roles=()):
        self.id = id
        self.roles = list(roles)
        self.fail_add = set()
        self.added = []
        self.removed = []

    async def add_roles(self, role, reason=None):
        if role.id in self.fail_add:
            raise forbidden()
        self.added.append(role.id)
        if role not in self.roles:
            self.roles.append(role)

    async def remove_roles(self, role, reason=None):
        self.removed.append(role.id)
        self.roles = [r for r in self.roles if r.id != role.id]


class FakeGuild:
    def __init__(self, member):
        self.id = GUILD_ID
        ids = [SETTINGS.player_role_id, SETTINGS.temp_role_id, SETTINGS.closed_role_id,
               SETTINGS.open_role_id, FAITH_ROLE, CONTINENT_ROLE]
        self.roles = {i: FakeRole(i, f"role-{i}") for i in ids}
        self.member = member
        self.me = SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=True),
                                  top_role=SimpleNamespace(position=100))

    def get_role(self, role_id):
        return self.roles.get(int(role_id))

    def get_member(self, member_id):
        return self.member if int(member_id) == self.member.id else None

    async def fetch_member(self, member_id):
        raise discord.NotFound(MagicMock(status=404, reason="Not Found"), "Unknown Member")


def approved_data(system="closed"):
    return {
        "official_name": "Kingdom of Avalon",
        "short_name": "Avalon",
        "system": system,
        "calendar": {"mode": "new", "name": "Avalon Reckoning", "key": "AR",
                     "current_year": 10, "staff_years_per_year": 1.0},
    }


@pytest.fixture
def env(tmp_path):
    store = rs.RegistrationStore(str(tmp_path / "reg.db"))
    member = FakeMember(MEMBER_ID)
    guild = FakeGuild(member)
    bot = SimpleNamespace(get_guild=lambda gid: guild if int(gid) == GUILD_ID else None)
    tracker = MagicMock()
    tracker.configured = True
    tracker.create_registration = AsyncMock(
        return_value={"nation": {"id": "n1"}, "nationPath": "/nations/n1", "created": True})
    tracker.member_links = AsyncMock(return_value=[])
    tracker.nation_url = lambda path: "http://t" + path
    svc = RegistrationService(bot, store, SETTINGS, tracker)
    svc.send_thread = AsyncMock(return_value=MagicMock())
    svc.dm = AsyncMock(return_value=("sent", MagicMock()))
    svc._edit_status = AsyncMock()
    svc._edit_message = AsyncMock(return_value=True)
    svc._queue_calendar = AsyncMock()
    yield SimpleNamespace(store=store, member=member, guild=guild, tracker=tracker, svc=svc)
    store.close()


def awaiting_population(env, system="closed", groups=True):
    data = approved_data(system)
    review = {"region": "North"}
    if groups:
        review.update(faith_role_ids=[FAITH_ROLE], continent_role_ids=[CONTINENT_ROLE])
    return env.store.create(GUILD_ID, MEMBER_ID, state=rs.AWAITING_POPULATION, revision=2,
                            submitted=data, approved=data, review=review)


def role_ids(member):
    return {r.id for r in member.roles}


@pytest.mark.asyncio
async def test_happy_path_creates_nation_and_grants_roles(env):
    app = awaiting_population(env)
    result = await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 5000, 1200)
    assert result.state == rs.ACTIVE
    assert result.population == 5000 and result.start_year == 1200
    assert result.tracker_nation_id == "n1"
    assert result.tracker_url == "http://t/nations/n1"
    kwargs = env.tracker.create_registration.await_args.kwargs
    assert kwargs["name"] == "Avalon"
    assert kwargs["official_name"] == "Kingdom of Avalon"
    assert kwargs["region"] == "North"
    assert kwargs["start_population"] == 5000 and kwargs["start_year"] == 1200
    assert role_ids(env.member) == {SETTINGS.player_role_id, SETTINGS.temp_role_id,
                                    SETTINGS.closed_role_id, FAITH_ROLE, CONTINENT_ROLE}
    granted = rs.parse_iso(result.temp_role_granted_at)
    expires = rs.parse_iso(result.temp_role_expires_at)
    assert expires - granted == timedelta(days=SETTINGS.temp_role_days)
    assert result.steps["announce"]["status"] == "done"

    await env.svc.provision(app.id)
    assert env.tracker.create_registration.await_count == 1


@pytest.mark.asyncio
async def test_open_system_gets_open_role_only(env):
    app = awaiting_population(env, system="open", groups=False)
    await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 10, 0)
    held = role_ids(env.member)
    assert SETTINGS.open_role_id in held
    assert SETTINGS.closed_role_id not in held


@pytest.mark.asyncio
async def test_population_rejects_stale_and_unauthorized(env):
    app = awaiting_population(env)
    with pytest.raises(ActionError):
        await env.svc.confirm_population(app.id, 2, 999, 10, 10)
    with pytest.raises(ActionError) as stale:
        await env.svc.confirm_population(app.id, 1, SETTINGS.population_approver_id, 10, 10)
    assert str(stale.value) == STALE
    with pytest.raises(ActionError):
        await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, -1, 10)
    with pytest.raises(ActionError):
        await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 10, 99999)
    assert env.store.get(app.id).state == rs.AWAITING_POPULATION
    env.tracker.create_registration.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_confirmation_cannot_complete_twice(env):
    app = awaiting_population(env)
    await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 10, 10)
    with pytest.raises(ActionError):
        await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 20, 20)
    assert env.tracker.create_registration.await_count == 1
    assert env.store.get(app.id).population == 10


@pytest.mark.asyncio
async def test_role_failure_then_retry_without_second_tracker_write(env):
    app = awaiting_population(env)
    env.member.fail_add = {SETTINGS.temp_role_id}
    result = await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 10, 10)
    assert result.state == rs.PROVISIONING
    assert result.failed_steps() == ["roles"]
    assert result.temp_role_expires_at is None
    env.svc.send_thread.assert_not_awaited()

    env.member.fail_add = set()
    result = await env.svc.retry(app.id)
    assert result.state == rs.ACTIVE
    assert env.tracker.create_registration.await_count == 1
    assert SETTINGS.temp_role_id in role_ids(env.member)
    assert result.temp_role_expires_at is not None


@pytest.mark.asyncio
async def test_tracker_failure_then_retry(env):
    app = awaiting_population(env)
    env.tracker.create_registration.side_effect = TrackerError(503, "down")
    result = await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 10, 10)
    assert result.state == rs.PROVISIONING
    assert result.steps["tracker"]["status"] == "failed"
    assert env.member.added == []

    env.tracker.create_registration.side_effect = None
    result = await env.svc.retry(app.id)
    assert result.state == rs.ACTIVE
    assert result.tracker_nation_id == "n1"


@pytest.mark.asyncio
async def test_retry_roles_does_not_extend_expiry(env):
    app = awaiting_population(env)
    first = await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 10, 10)
    await env.member.remove_roles(env.guild.get_role(FAITH_ROLE))
    await env.svc.retry_roles(app.id)
    again = env.store.get(app.id)
    assert again.temp_role_expires_at == first.temp_role_expires_at
    assert FAITH_ROLE in role_ids(env.member)


@pytest.mark.asyncio
async def test_temp_role_expiry_removes_only_temp_role(env):
    app = awaiting_population(env)
    await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 10, 10)
    assert await env.svc.expire_temp_roles(rs.utcnow() + timedelta(days=13)) == 0
    later = rs.utcnow() + timedelta(days=15)
    assert await env.svc.expire_temp_roles(later) == 1
    held = role_ids(env.member)
    assert SETTINGS.temp_role_id not in held
    assert {SETTINGS.player_role_id, SETTINGS.closed_role_id, FAITH_ROLE} <= held
    assert await env.svc.expire_temp_roles(later) == 0

    await env.svc.retry_roles(app.id)
    assert SETTINGS.temp_role_id not in role_ids(env.member)


@pytest.mark.asyncio
async def test_calendar_approved_converts_choice(env):
    app = awaiting_population(env)
    env.store.update(app.id, calendar_submission_id="sub-1", draft=approved_data())
    await env.svc.on_calendar_decision("sub-1", "approved", {"name": "Avalon Reckoning"})
    got = env.store.get(app.id)
    assert got.approved["calendar"] == {"mode": "existing", "name": "Avalon Reckoning"}
    assert got.draft["calendar"]["mode"] == "existing"
    assert got.steps["calendar"]["status"] == "approved"
    assert got.state == rs.AWAITING_POPULATION


@pytest.mark.asyncio
async def test_calendar_denied_keeps_registration(env):
    app = awaiting_population(env)
    env.store.update(app.id, calendar_submission_id="sub-2")
    await env.svc.on_calendar_decision("sub-2", "denied", {"name": "Avalon Reckoning"})
    got = env.store.get(app.id)
    assert got.calendar_submission_id is None
    assert got.steps["calendar"]["status"] == "denied"
    assert got.state == rs.AWAITING_POPULATION
    env.svc.dm.assert_awaited()
    env.svc.send_thread.assert_awaited()


@pytest.mark.asyncio
async def test_eligibility(env):
    member = FakeMember(MEMBER_ID, roles=[FakeRole(SETTINGS.player_role_id, "Player")])
    assert "player role" in await env.svc.eligibility(GUILD_ID, member)
    newcomer = FakeMember(555)
    assert await env.svc.eligibility(GUILD_ID, newcomer) is None
    env.tracker.member_links.return_value = [{"registration": {"releasedAt": None}}]
    assert await env.svc.eligibility(GUILD_ID, newcomer)
    env.tracker.member_links.return_value = [{"registration": {"releasedAt": "2026-01-01"}}]
    assert await env.svc.eligibility(GUILD_ID, newcomer) is None
    env.store.create(GUILD_ID, MEMBER_ID)
    assert await env.svc.eligibility(GUILD_ID, member) is None


THREAD_ID = 555


def with_channels(env):
    """Give the service a real-looking registration channel that creates one thread."""
    thread = MagicMock(spec=discord.Thread)
    thread.id = THREAD_ID
    thread.name = "New nation"
    thread.archived = False
    thread.send = AsyncMock(return_value=SimpleNamespace(id=777))
    thread.add_user = AsyncMock()
    thread.edit = AsyncMock()
    parent = MagicMock(spec=discord.TextChannel)
    parent.guild = SimpleNamespace(id=GUILD_ID)
    parent.create_thread = AsyncMock(return_value=thread)
    channels = {SETTINGS.channel_id: parent, THREAD_ID: thread}
    env.svc.bot = SimpleNamespace(get_guild=lambda gid: env.guild,
                                  get_channel=lambda cid: channels.get(int(cid)),
                                  fetch_channel=AsyncMock())
    return parent, thread


def role_pings(thread):
    return [c for c in thread.send.await_args_list if "<@&" in str(c.kwargs.get("content") or "")]


@pytest.mark.asyncio
async def test_partial_draft_opens_thread_without_ping(env):
    parent, thread = with_channels(env)
    app = env.svc.start(GUILD_ID, MEMBER_ID)
    env.svc.save_draft(app.id, MEMBER_ID, lambda d: {**d, "short_name": "Avalon"})
    await env.svc.sync_draft_thread(app.id)

    got = env.store.get(app.id)
    assert got.state == rs.DRAFT
    assert got.thread_id == THREAD_ID
    assert got.status_message_id == 777
    parent.create_thread.assert_awaited_once()
    assert parent.create_thread.await_args.kwargs["name"] == "Avalon"
    assert not role_pings(thread)
    assert all(c.kwargs.get("allowed_mentions") is NO_MENTIONS for c in thread.send.await_args_list)

    # Further saves only refresh the status message.
    env.svc.save_draft(app.id, MEMBER_ID, lambda d: {**d, "capital": "Camelot"})
    await env.svc.sync_draft_thread(app.id)
    parent.create_thread.assert_awaited_once()
    env.svc._edit_status.assert_awaited()
    assert env.store.get(app.id).state == rs.DRAFT


@pytest.mark.asyncio
async def test_incomplete_draft_cannot_submit(env):
    with_channels(env)
    app = env.svc.start(GUILD_ID, MEMBER_ID)
    env.svc.save_draft(app.id, MEMBER_ID, lambda d: {**d, "short_name": "Avalon"})
    await env.svc.sync_draft_thread(app.id)
    with pytest.raises(ActionError, match="Still missing"):
        await env.svc.submit(app.id, MEMBER_ID)
    got = env.store.get(app.id)
    assert got.state == rs.DRAFT
    assert got.revision == 0


@pytest.mark.asyncio
async def test_submit_reuses_draft_thread_and_pings_once(env, monkeypatch):
    import registration_service

    parent, thread = with_channels(env)
    app = env.svc.start(GUILD_ID, MEMBER_ID)
    env.svc.save_draft(app.id, MEMBER_ID, lambda d: {**d, **approved_data()})
    await env.svc.sync_draft_thread(app.id)
    assert not role_pings(thread)

    monkeypatch.setattr(registration_service.logic, "missing_items", lambda data: [])
    note = await env.svc.submit(app.id, MEMBER_ID)

    got = env.store.get(app.id)
    assert got.state == rs.AWAITING_STAFF
    assert str(THREAD_ID) in note
    parent.create_thread.assert_awaited_once()
    assert len(role_pings(thread)) == 1


@pytest.mark.asyncio
async def test_draft_thread_failure_does_not_block_saving(env):
    parent, _ = with_channels(env)
    parent.create_thread.side_effect = discord.HTTPException(MagicMock(status=500, reason="x"), "boom")
    app = env.svc.start(GUILD_ID, MEMBER_ID)
    env.svc.save_draft(app.id, MEMBER_ID, lambda d: {**d, "short_name": "Avalon"})
    await env.svc.sync_draft_thread(app.id)
    got = env.store.get(app.id)
    assert got.thread_id is None
    assert got.draft["short_name"] == "Avalon"
    assert got.state == rs.DRAFT


def embed_text(embed):
    parts = [embed.title or "", embed.description or ""]
    parts += [f"{f.name} {f.value}" for f in embed.fields]
    return "\n".join(parts)


@pytest.mark.asyncio
async def test_tracker_link_only_in_approver_dm(env):
    import registration_ui as ui

    app = awaiting_population(env)
    env.store.update(app.id, dm_channel_id=11, dm_message_id=12)
    result = await env.svc.confirm_population(app.id, 2, SETTINGS.population_approver_id, 5000, 1200)
    link = "http://t/nations/n1"
    assert result.tracker_url == link

    thread_posts = [c.kwargs["embed"] for c in env.svc.send_thread.await_args_list if "embed" in c.kwargs]
    registrant_dms = [c.kwargs["embed"] for c in env.svc.dm.await_args_list
                      if c.args and c.args[0] == MEMBER_ID and "embed" in c.kwargs]
    assert thread_posts and registrant_dms
    for embed in thread_posts + registrant_dms + [ui.status_embed(result, SETTINGS)]:
        assert link not in embed_text(embed)

    approver_edits = [c.kwargs["embed"] for c in env.svc._edit_message.await_args_list
                      if c.args[:2] == (11, 12) and "embed" in c.kwargs]
    assert approver_edits and link in embed_text(approver_edits[-1])
