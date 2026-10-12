"""Nation registration workflow: drafts, staff review, population, tracker and roles."""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from datetime import timedelta
from typing import Any, Callable, Iterable

import discord

import calendar_submissions as cs
import registration_logic as logic
import registration_store as rs
import registration_ui as ui
from registration_logic import ActionError
from tracker_client import TrackerError

logger = logging.getLogger(__name__)

NO_MENTIONS = discord.AllowedMentions.none()
STALE = "These controls are out of date. Reopen the latest registration controls."
POST_APPROVAL = (rs.AWAITING_POPULATION, rs.PROVISIONING, rs.ACTIVE)
CALENDAR_RETRY = ("denied", "conflict", "failed")
GROUP_LIMIT = 24
# Discord allows two channel renames per ten minutes; stay under it so we never sleep on a 429.
RENAME_LIMIT = 2
RENAME_WINDOW = 600
_DEFAULT = object()


def mentions(users: Iterable[int] = (), roles: Iterable[int] = ()) -> discord.AllowedMentions:
    users, roles = list(users), list(roles)
    return discord.AllowedMentions(
        everyone=False,
        users=[discord.Object(int(i)) for i in users] if users else False,
        roles=[discord.Object(int(i)) for i in roles] if roles else False,
    )


def step_status(app: rs.Application, name: str) -> str | None:
    return (app.steps.get(name) or {}).get("status")


def _done_for(app: rs.Application, name: str) -> bool:
    info = app.steps.get(name) or {}
    return info.get("status") == "done" and info.get("detail") == f"revision {app.revision}"


class RegistrationService:
    def __init__(self, bot: Any, store: rs.RegistrationStore, settings: Any, tracker: Any):
        self.bot = bot
        self.store = store
        self.settings = settings
        self.tracker = tracker
        self._locks: dict[str, asyncio.Lock] = {}
        self._renames: dict[int, list[float]] = {}

    def lock(self, app_id: str) -> asyncio.Lock:
        lock = self._locks.get(app_id)
        if lock is None:
            lock = self._locks[app_id] = asyncio.Lock()
        return lock

    # Checks -------------------------------------------------------------------

    def require(self, app_id: str) -> rs.Application:
        app = self.store.get(app_id)
        if app is None:
            raise ActionError("That registration no longer exists.")
        return app

    def check_current(self, app_id: str, states: str | Iterable[str],
                      revision: int | None = None) -> rs.Application:
        app = self.require(app_id)
        states = (states,) if isinstance(states, str) else tuple(states)
        if app.state not in states or (revision is not None and app.revision != revision):
            raise ActionError(STALE)
        return app

    @staticmethod
    def _check_owner(app: rs.Application, actor_id: int) -> None:
        if int(actor_id) != int(app.member_id):
            raise ActionError("Only the registrant can do that.")

    def _check_reviewer(self, app: rs.Application, member: Any) -> None:
        if not logic.is_staff(member, self.settings.staff_role_id):
            raise ActionError("Only registration staff can review registrations.")
        perms = getattr(member, "guild_permissions", None)
        if int(member.id) == int(app.member_id) and not getattr(perms, "administrator", False):
            raise ActionError("You cannot review your own registration.")

    @staticmethod
    def _check_amendable(app: rs.Application) -> None:
        if app.state != rs.ACTIVE:
            raise ActionError(STALE)
        if app.source == "legacy":
            raise ActionError("This nation was linked by staff; ask staff to update its details.")
        if (app.amendment or {}).get("status") == "pending":
            raise ActionError("Your previous changes are still waiting for staff review.")

    # Group role allowlists ---------------------------------------------------

    def group_roles(self) -> dict[str, list[int]]:
        stored = self.store.get_setting("group_roles", {}) or {}
        return {g: [int(i) for i in stored.get(g, [])] for g in ui.GROUPS}

    def _core_role_ids(self) -> set[int]:
        s = self.settings
        return {s.player_role_id, s.temp_role_id, s.closed_role_id, s.open_role_id, s.staff_role_id}

    def add_group_role(self, group: str, role_id: int) -> None:
        if group not in ui.GROUPS:
            raise ActionError("Unknown role group.")
        if int(role_id) in self._core_role_ids():
            raise ActionError("Registration and staff roles cannot be group roles.")
        roles = self.group_roles()
        if int(role_id) in roles[group]:
            return
        if len(roles[group]) >= GROUP_LIMIT:
            raise ActionError(f"Each group can hold at most {GROUP_LIMIT} roles.")
        roles[group].append(int(role_id))
        self.store.set_setting("group_roles", roles)

    def remove_group_role(self, group: str, role_id: int) -> bool:
        roles = self.group_roles()
        if int(role_id) not in roles.get(group, []):
            return False
        roles[group].remove(int(role_id))
        self.store.set_setting("group_roles", roles)
        return True

    # Released members (may register again after their nation was archived) ----

    def is_released(self, guild_id: int, member_id: int) -> bool:
        return f"{guild_id}:{member_id}" in (self.store.get_setting("released_members", []) or [])

    def _set_released(self, guild_id: int, member_id: int, flag: bool) -> None:
        key = f"{guild_id}:{member_id}"
        released = [k for k in (self.store.get_setting("released_members", []) or []) if k != key]
        if flag:
            released.append(key)
        self.store.set_setting("released_members", released)

    # Discord helpers -----------------------------------------------------------

    async def fetch_member(self, guild: Any, member_id: int) -> Any:
        member = guild.get_member(int(member_id))
        if member is not None:
            return member
        try:
            return await guild.fetch_member(int(member_id))
        except discord.NotFound:
            return None

    async def channel(self, channel_id: int | None) -> Any:
        if not channel_id:
            return None
        found = self.bot.get_channel(int(channel_id))
        if found is not None:
            return found
        try:
            return await self.bot.fetch_channel(int(channel_id))
        except discord.HTTPException:
            return None

    async def thread(self, app: rs.Application) -> Any:
        found = await self.channel(app.thread_id)
        return found if isinstance(found, discord.Thread) else None

    @staticmethod
    def thread_url(app: rs.Application) -> str | None:
        if not app.thread_id:
            return None
        return f"https://discord.com/channels/{app.guild_id}/{app.thread_id}"

    @staticmethod
    async def _unarchive(thread: Any) -> None:
        if getattr(thread, "archived", False):
            try:
                await thread.edit(archived=False)
            except discord.HTTPException:
                logger.warning("Could not unarchive registration thread %s", getattr(thread, "id", None))

    async def _maybe_rename(self, thread: Any, name: str) -> None:
        if not name or getattr(thread, "name", None) == name:
            return
        now = time.monotonic()
        recent = [t for t in self._renames.get(thread.id, []) if now - t < RENAME_WINDOW]
        if len(recent) >= RENAME_LIMIT:
            self._renames[thread.id] = recent
            return
        recent.append(now)
        self._renames[thread.id] = recent
        try:
            await thread.edit(name=name)
        except discord.HTTPException:
            logger.info("Could not rename registration thread %s", getattr(thread, "id", None))

    async def _thread_gone(self, thread_id: int) -> bool:
        """True only when Discord confirms the thread was deleted (not on transient errors)."""
        if self.bot.get_channel(int(thread_id)) is not None:
            return False
        try:
            await self.bot.fetch_channel(int(thread_id))
            return False
        except discord.NotFound:
            return True
        except discord.HTTPException:
            return False

    async def send_thread(self, app: rs.Application, **kwargs: Any) -> Any:
        thread = await self.thread(app)
        if thread is None:
            return None
        await self._unarchive(thread)
        kwargs.setdefault("allowed_mentions", NO_MENTIONS)
        try:
            return await thread.send(**kwargs)
        except discord.HTTPException:
            logger.exception("Could not post in registration thread app=%s", app.id)
            return None

    async def dm(self, user_id: int, **kwargs: Any) -> tuple[str, Any]:
        try:
            user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
            return "sent", await user.send(**kwargs)
        except discord.Forbidden:
            return "forbidden", None
        except discord.HTTPException:
            logger.exception("Registration DM failed user=%s", user_id)
            return "failed", None

    async def _edit_message(self, channel: Any, message_id: int | None, **kwargs: Any) -> bool:
        if not channel or not message_id:
            return False
        try:
            if isinstance(channel, int):
                channel = self.bot.get_partial_messageable(channel)
            message = await channel.fetch_message(int(message_id))
            await message.edit(**kwargs)
            return True
        except discord.HTTPException:
            logger.info("Could not edit registration message %s", message_id)
            return False

    async def _edit_status(self, app: rs.Application, note: str | None = None, view: Any = _DEFAULT) -> bool:
        if view is _DEFAULT:
            view = ui.staff_controls(app) if app.state == rs.AWAITING_STAFF else None
        return await self._edit_message(app.thread_id, app.status_message_id,
                                        embed=ui.status_embed(app, self.settings, note), view=view)

    def files_for(self, data: dict, purposes: Iterable[str] | None = None) -> list[tuple[str, discord.File]]:
        wanted = list(purposes) if purposes is not None else list(logic.UPLOAD_PURPOSES)
        files: list[tuple[str, discord.File]] = []
        for purpose in wanted:
            record = self.store.get_file((data.get("files") or {}).get(purpose))
            if not record or not os.path.exists(record["path"]):
                continue
            ext = os.path.splitext(record.get("filename") or record["path"])[1].lower() or ".png"
            files.append((purpose, discord.File(record["path"], filename=purpose + ext)))
        return files

    # Drafts -------------------------------------------------------------------

    def start(self, guild_id: int, member_id: int) -> rs.Application:
        app = self.store.live_for_member(guild_id, member_id)
        if app is not None:
            return app
        try:
            return self.store.create(guild_id, member_id)
        except rs.DuplicateApplication:
            app = self.store.live_for_member(guild_id, member_id)
            if app is None:
                raise
            return app

    async def eligibility(self, guild_id: int, member: Any) -> str | None:
        """None when the member may use /register, otherwise the reason they cannot."""
        if self.store.live_for_member(guild_id, member.id) is not None:
            return None
        if self.is_released(guild_id, member.id):
            return None
        if any(getattr(r, "id", None) == self.settings.player_role_id for r in getattr(member, "roles", [])):
            return ("You already have the player role. Ask staff to link your existing nation, "
                    "or to release it if you want to register a new one.")
        if self.tracker.configured:
            try:
                links = await self.tracker.member_links(guild_id, member.id)
            except TrackerError:
                logger.warning("Tracker lookup failed during eligibility check", exc_info=True)
                return None
            if any(not (link.get("registration") or {}).get("releasedAt") for link in links or []):
                return "You already have a nation in the tracker. Ask staff if you need to change it."
        return None

    def save_draft(self, app_id: str, actor_id: int, mutate: Callable[[dict], dict],
                   mode: str = "edit") -> rs.Application:
        app = self.require(app_id)
        self._check_owner(app, actor_id)
        if mode == "amend":
            self._check_amendable(app)
        elif app.state not in rs.EDITABLE_STATES:
            raise ActionError("This registration can no longer be edited.")
        data = mutate(copy.deepcopy(app.draft or {}))
        if not self.store.update(app_id, expect_state=app.state, expect_revision=app.revision, draft=data):
            raise ActionError(STALE)
        return self.require(app_id)

    def set_position(self, app_id: str, step: str) -> None:
        if step in logic.STEPS:
            self.store.update(app_id, step=step)

    def set_upload(self, app_id: str, actor_id: int, purpose: str, file_id: int) -> rs.Application:
        app = self.require(app_id)
        mode = "amend" if app.state == rs.ACTIVE else "edit"

        def mutate(data: dict) -> dict:
            files = dict(data.get("files") or {})
            files[purpose] = file_id
            data["files"] = files
            return data

        return self.save_draft(app_id, actor_id, mutate, mode)

    async def sync_draft_thread(self, app_id: str) -> None:
        """Create or refresh the public thread for an unsubmitted draft.

        Drafts get a thread as soon as anything is saved so registrants can work in the open,
        but this never pings anyone and never changes the application's state. Failures are
        logged only; saving a draft must not depend on Discord.
        """
        async with self.lock(app_id):
            app = self.require(app_id)
            if app.state not in rs.EDITABLE_STATES or not self.settings.channel_id:
                return
            try:
                if app.thread_id and app.state == rs.DRAFT and await self._thread_gone(app.thread_id):
                    self.store.update(app_id, thread_id=None, status_message_id=None)
                    app = self.require(app_id)
                if not app.thread_id:
                    thread = await self._ensure_thread(app)
                    app = self.require(app_id)
                    message = await thread.send(embed=ui.status_embed(app, self.settings),
                                                allowed_mentions=NO_MENTIONS)
                    self.store.update(app_id, status_message_id=message.id)
                    self.store.log(app_id, "draft_thread", app.member_id, str(thread.id))
                    return
                thread = await self.thread(app)
                if thread is None:
                    return
                if app.state == rs.DRAFT:
                    await self._maybe_rename(thread, logic.thread_name(app.draft or {}))
                if app.status_message_id:
                    await self._edit_status(app)
                else:
                    message = await thread.send(embed=ui.status_embed(app, self.settings),
                                                allowed_mentions=NO_MENTIONS)
                    self.store.update(app_id, status_message_id=message.id)
            except (ActionError, discord.HTTPException, OSError) as error:
                logger.warning("Draft thread sync for registration %s failed: %s", app_id, error)

    async def discard_amendment(self, app_id: str, actor_id: int) -> str:
        async with self.lock(app_id):
            app = self.require(app_id)
            self._check_owner(app, actor_id)
            self._check_amendable(app)
            self.store.update(app_id, expect_state=rs.ACTIVE, draft=copy.deepcopy(app.approved or {}),
                              step="identity")
        return "Your unsent changes were discarded."

    # Submit and publish ----------------------------------------------------------

    async def submit(self, app_id: str, actor_id: int) -> str:
        async with self.lock(app_id):
            app = self.require(app_id)
            self._check_owner(app, actor_id)
            if app.state not in rs.EDITABLE_STATES:
                raise ActionError("This registration was already submitted.")
            missing = logic.missing_items(app.draft or {})
            if missing:
                raise ActionError("Still missing: " + ", ".join(missing[:10]))
            if app.thread_id and app.state == rs.DRAFT and await self._thread_gone(app.thread_id):
                self.store.update(app_id, thread_id=None, status_message_id=None)
            ok = self.store.update(
                app_id, expect_state=rs.EDITABLE_STATES, expect_revision=app.revision,
                state=rs.AWAITING_STAFF, revision=app.revision + 1,
                submitted=copy.deepcopy(app.draft), notes=None, step="review")
            if not ok:
                raise ActionError(STALE)
            self.store.set_step(app_id, "publish", "pending")
            self.store.log(app_id, "submitted", actor_id, f"revision {app.revision + 1}")
        await self.publish(app_id, ping=True)
        app = self.require(app_id)
        if step_status(app, "publish") == "done":
            return f"{ui.DONE} Submitted for staff review: {self.thread_url(app)}"
        return (f"{ui.WARN} Your registration is saved and submitted, but the review thread could not be "
                "posted yet. Staff have been notified to retry.")

    async def publish(self, app_id: str, ping: bool = True) -> None:
        async with self.lock(app_id):
            app = self.require(app_id)
            if app.state != rs.AWAITING_STAFF:
                return
            try:
                thread = await self._ensure_thread(app)
                app = self.require(app_id)
                await self._post_submission(app, thread)
                app = self.require(app_id)
                await self._post_staff_controls(app, thread, ping)
                self.store.set_step(app_id, "publish", "done", f"revision {app.revision}")
            except (ActionError, discord.HTTPException, OSError) as error:
                logger.warning("Publishing registration %s failed: %s", app_id, error)
                self.store.set_step(app_id, "publish", "failed", logic.truncate(str(error), 300))

    async def _ensure_thread(self, app: rs.Application) -> Any:
        if app.thread_id:
            thread = await self.thread(app)
            if thread is None:
                raise ActionError("The registration thread is missing. Use /registrations reopen_review.")
            await self._unarchive(thread)
            await self._maybe_rename(thread, logic.thread_name(app.submitted or app.draft or {}))
            return thread
        parent = await self.channel(self.settings.channel_id)
        if parent is None or getattr(getattr(parent, "guild", None), "id", None) != app.guild_id:
            raise ActionError("The registration channel is unavailable to the bot.")
        data = app.submitted or app.draft or {}
        name = logic.thread_name(data)
        intro = f"Nation registration by <@{app.member_id}>"
        if isinstance(parent, discord.ForumChannel):
            tags = parent.available_tags[:1] if getattr(parent, "requires_tag", False) else []
            created = await parent.create_thread(name=name, content=intro, applied_tags=tags,
                                                 allowed_mentions=NO_MENTIONS)
            thread = getattr(created, "thread", created)
        elif isinstance(parent, discord.TextChannel):
            thread = await parent.create_thread(name=name, auto_archive_duration=10080,
                                                type=discord.ChannelType.public_thread)
            await thread.send(intro, allowed_mentions=NO_MENTIONS)
        else:
            raise ActionError("The registration channel must be a forum or text channel.")
        self.store.update(app.id, thread_id=thread.id, status_message_id=None)
        self.store.set_step(app.id, "publish_content", "pending")
        try:
            await thread.add_user(discord.Object(app.member_id))
        except discord.HTTPException:
            logger.info("Could not add registrant %s to thread %s", app.member_id, thread.id)
        return thread

    async def _post_submission(self, app: rs.Application, thread: Any) -> None:
        if _done_for(app, "publish_content"):
            return
        if app.revision > 1:
            await thread.send(f"**Revision {app.revision}** submitted by <@{app.member_id}>.",
                              allowed_mentions=NO_MENTIONS)
        await ui.send_preview(thread, self, app.submitted or {})
        self.store.set_step(app.id, "publish_content", "done", f"revision {app.revision}")

    async def _post_staff_controls(self, app: rs.Application, thread: Any, ping: bool) -> None:
        role = self.settings.staff_role_id
        should_ping = ping and not _done_for(app, "staff_ping")
        content = f"<@&{role}> a registration is ready for review." if should_ping else None
        message = await thread.send(content=content, embed=ui.status_embed(app, self.settings),
                                    view=ui.staff_controls(app),
                                    allowed_mentions=mentions(roles=[role]) if should_ping else NO_MENTIONS)
        old = app.status_message_id
        self.store.update(app.id, status_message_id=message.id)
        if should_ping:
            self.store.set_step(app.id, "staff_ping", "done", f"revision {app.revision}")
        if old and old != message.id:
            await self._edit_message(thread, old, view=None, embed=ui.status_embed(
                app, self.settings, "Superseded. The current status is further down this thread."))

    # Staff decisions ---------------------------------------------------------------

    async def staff_approve(self, app_id: str, revision: int, reviewer: Any, region: str,
                            faith_ids: Iterable[int], continent_ids: Iterable[int]) -> str:
        async with self.lock(app_id):
            app = self.check_current(app_id, rs.AWAITING_STAFF, revision)
            self._check_reviewer(app, reviewer)
            region = logic.clean(region)
            if not 1 <= len(region) <= 100:
                raise ActionError("Region must be 1-100 characters.")
            allowed = self.group_roles()
            faith = [int(i) for i in faith_ids]
            continent = [int(i) for i in continent_ids]
            if any(i not in allowed["faith"] for i in faith) or any(i not in allowed["continent"] for i in continent):
                raise ActionError("A selected group role is no longer allowed. Reopen the review form.")
            review = {"decision": "approved", "reviewer_id": reviewer.id, "region": region,
                      "faith_role_ids": faith, "continent_role_ids": continent, "reviewed_at": rs.iso()}
            ok = self.store.update(app_id, expect_state=rs.AWAITING_STAFF, expect_revision=revision,
                                   state=rs.AWAITING_POPULATION, review=review,
                                   approved=copy.deepcopy(app.submitted), notes=None)
            if not ok:
                raise ActionError(STALE)
            self.store.log(app_id, "staff_approved", reviewer.id, region)
            app = self.require(app_id)
            await self._edit_status(app)
            await self.send_thread(
                app, content=(f"<@{app.member_id}> staff approved your registration "
                              f"(reviewed by <@{reviewer.id}>). Next, your population and start year "
                              "will be assigned."),
                allowed_mentions=mentions(users=[app.member_id]))
        await self._queue_calendar(app_id)
        await self.send_population_request(app_id)
        app = self.require(app_id)
        if step_status(app, "population_request") == "done":
            return f"{ui.DONE} Approved. The population request has been sent."
        return (f"{ui.WARN} Approved, but the population request could not be delivered. "
                "Use /registrations resend_population.")

    async def send_population_request(self, app_id: str) -> None:
        async with self.lock(app_id):
            app = self.require(app_id)
            if app.state != rs.AWAITING_POPULATION:
                return
            approver = self.settings.population_approver_id
            guild = self.bot.get_guild(app.guild_id)
            applicant = await self.fetch_member(guild, app.member_id) if guild else None
            embed = ui.population_embed(app, self.settings, applicant, self.thread_url(app))
            status, message = await self.dm(approver, embed=embed, view=ui.population_controls(app))
            if message is None:
                message = await self.send_thread(
                    app, content=f"<@{approver}> I could not DM you this population request.",
                    embed=embed, view=ui.population_controls(app),
                    allowed_mentions=mentions(users=[approver]))
            if message is None:
                self.store.set_step(app_id, "population_request", "failed",
                                    f"Could not DM the population approver ({status}) or post in the thread.")
                await self._edit_status(self.require(app_id))
                return
            old_channel, old_message = app.dm_channel_id, app.dm_message_id
            self.store.update(app_id, dm_channel_id=message.channel.id, dm_message_id=message.id)
            self.store.set_step(app_id, "population_request", "done")
            if old_message and old_message != message.id:
                await self._edit_message(old_channel, old_message, view=None)
            await self._edit_status(self.require(app_id))

    async def staff_decline(self, app_id: str, revision: int, reviewer: Any, reason: str,
                            reject: bool) -> str:
        reason = logic.clean(reason)
        if not reason:
            raise ActionError("A reason is required.")
        async with self.lock(app_id):
            app = self.check_current(app_id, rs.AWAITING_STAFF, revision)
            self._check_reviewer(app, reviewer)
            state = rs.REJECTED if reject else rs.CHANGES_REQUESTED
            decision = "rejected" if reject else "changes_requested"
            review = {"decision": decision, "reviewer_id": reviewer.id, "reviewed_at": rs.iso()}
            ok = self.store.update(app_id, expect_state=rs.AWAITING_STAFF, expect_revision=revision,
                                   state=state, notes=reason, review=review)
            if not ok:
                raise ActionError(STALE)
            self.store.log(app_id, decision, reviewer.id, reason)
            app = self.require(app_id)
            await self._edit_status(app)
            quoted = "\n".join("> " + line for line in logic.truncate(reason, 1500).splitlines())
            if reject:
                text = f"<@{app.member_id}> your registration was rejected by <@{reviewer.id}>.\n{quoted}"
                dm_text = f"Your nation registration was rejected.\n{quoted}"
            else:
                text = (f"<@{app.member_id}> <@{reviewer.id}> requested changes:\n{quoted}\n"
                        "Run `/register` to update and resubmit.")
                dm_text = (f"Staff requested changes to your nation registration:\n{quoted}\n"
                           "Run `/register` in the server to update and resubmit.")
            await self.send_thread(app, content=text, allowed_mentions=mentions(users=[app.member_id]))
            await self.dm(app.member_id, content=dm_text)
        return f"{ui.DONE} {'Rejected' if reject else 'Changes requested'}. The registrant has been notified."

    async def withdraw(self, app_id: str, actor_id: int, by_staff: bool = False) -> str:
        async with self.lock(app_id):
            app = self.require(app_id)
            if not by_staff:
                self._check_owner(app, actor_id)
            if app.state not in rs.WITHDRAWABLE_STATES:
                raise ActionError("This registration can no longer be withdrawn.")
            if not self.store.update(app_id, expect_state=app.state, expect_revision=app.revision,
                                     state=rs.WITHDRAWN):
                raise ActionError(STALE)
            self.store.log(app_id, "withdrawn", actor_id, "staff" if by_staff else "registrant")
            app = self.require(app_id)
            await self._edit_status(app, view=None)
            if app.dm_message_id:
                await self._edit_message(app.dm_channel_id, app.dm_message_id, view=None)
            who = f"staff (<@{actor_id}>)" if by_staff else "the registrant"
            await self.send_thread(app, content=f"This registration was withdrawn by {who}.")
        return "The registration was withdrawn. You can start again with `/register`."

    # Population and provisioning ------------------------------------------------

    async def confirm_population(self, app_id: str, revision: int, actor_id: int,
                                 population: int, start_year: int) -> rs.Application:
        if int(actor_id) != int(self.settings.population_approver_id):
            raise ActionError("Only the population approver can assign population.")
        async with self.lock(app_id):
            app = self.check_current(app_id, rs.AWAITING_POPULATION, revision)
            low, high = logic.POPULATION_RANGE
            if not isinstance(population, int) or not low <= population <= high:
                raise ActionError(f"Population must be a whole number from {low:,} to {high:,}.")
            low, high = logic.YEAR_RANGE
            if not isinstance(start_year, int) or not low <= start_year <= high:
                raise ActionError(f"Start year must be a whole number from {low} to {high}.")
            ok = self.store.update(app_id, expect_state=rs.AWAITING_POPULATION, expect_revision=revision,
                                   state=rs.PROVISIONING, population=population, start_year=start_year,
                                   population_by=int(actor_id))
            if not ok:
                raise ActionError(STALE)
            self.store.log(app_id, "population_assigned", actor_id, f"{population} @ {start_year}")
            app = self.require(app_id)
            if app.dm_message_id:
                await self._edit_message(app.dm_channel_id, app.dm_message_id, view=None)
            await self._edit_status(app)
        await self.provision(app_id)
        return self.require(app_id)

    async def provision(self, app_id: str) -> None:
        activated = False
        async with self.lock(app_id):
            app = self.require(app_id)
            if app.state != rs.PROVISIONING:
                return
            await self._provision_tracker(app)
            app = self.require(app_id)
            if step_status(app, "tracker") == "done":
                await self._provision_roles(app)
                app = self.require(app_id)
            if step_status(app, "tracker") == "done" and step_status(app, "roles") == "done":
                activated = self.store.update(app_id, expect_state=rs.PROVISIONING, state=rs.ACTIVE,
                                              draft=copy.deepcopy(app.approved or {}), step="identity")
                if activated:
                    self._set_released(app.guild_id, app.member_id, False)
                    self.store.log(app_id, "activated")
            await self._edit_status(self.require(app_id))
        if activated:
            await self._announce(app_id)

    async def _provision_tracker(self, app: rs.Application) -> None:
        if app.tracker_nation_id:
            self.store.set_step(app.id, "tracker", "done")
            return
        if not self.tracker.configured:
            self.store.set_step(app.id, "tracker", "failed",
                                "The tracker is not configured (WRP_POPS_URL / WRP_POPS_TOKEN).")
            return
        data = app.approved or app.submitted or {}
        try:
            result = await self.tracker.create_registration(
                guild_id=app.guild_id, member_id=app.member_id, application_id=app.id,
                name=logic.clean(data.get("short_name")) or app.nation_name,
                official_name=logic.clean(data.get("official_name")) or None,
                region=(app.review or {}).get("region"), start_population=app.population,
                start_year=app.start_year, thread_id=app.thread_id, registration_url=self.thread_url(app))
        except TrackerError as error:
            detail = str(error)
            if error.status == 409:
                detail += " Resolve it in the tracker or use /registrations link."
            self.store.set_step(app.id, "tracker", "failed", logic.truncate(detail, 300))
            return
        nation = result.get("nation") or {}
        self.store.update(app.id, tracker_nation_id=str(nation.get("id")),
                          tracker_url=self.tracker.nation_url(result.get("nationPath")))
        self.store.set_step(app.id, "tracker", "done", "created" if result.get("created") else "existing")

    async def _provision_roles(self, app: rs.Application) -> None:
        guild = self.bot.get_guild(app.guild_id)
        if guild is None:
            self.store.set_step(app.id, "roles", "failed", "The bot cannot see the server.")
            return
        try:
            member = await self.fetch_member(guild, app.member_id)
        except discord.HTTPException as error:
            self.store.set_step(app.id, "roles", "failed", f"Could not load the member: {error}")
            return
        if member is None:
            self.store.set_step(app.id, "roles", "failed", "The registrant is no longer in the server.")
            return
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            self.store.set_step(app.id, "roles", "failed", "The bot needs the Manage Roles permission.")
            return
        now = rs.utcnow()
        expires = rs.parse_iso(app.temp_role_expires_at)
        include_temp = app.temp_role_removed_at is None and (expires is None or now < expires)
        review = app.review or {}
        groups = list(review.get("faith_role_ids") or []) + list(review.get("continent_role_ids") or [])
        data = app.approved or app.submitted or {}
        held = {r.id for r in member.roles}
        add, remove = logic.role_plan(held, self.settings, data.get("system"), groups, include_temp)
        core = {self.settings.player_role_id, self.settings.temp_role_id,
                self.settings.system_role_id(data.get("system"))}
        problems: list[str] = []
        for role_id in add + remove:
            role = guild.get_role(int(role_id))
            adding = role_id in add
            if role is None:
                if role_id in core:
                    problems.append(f"Role {role_id} does not exist.")
                else:
                    logger.info("Skipping missing group role %s for app %s", role_id, app.id)
                continue
            if role.position >= me.top_role.position:
                problems.append(f"Role {role.name} is above the bot's highest role.")
                continue
            try:
                if adding:
                    await member.add_roles(role, reason=f"Nation registration {app.id[:8]}")
                    held.add(role.id)
                else:
                    await member.remove_roles(role, reason=f"Nation registration {app.id[:8]}")
                    held.discard(role.id)
            except discord.HTTPException as error:
                problems.append(f"Could not {'add' if adding else 'remove'} {role.name}: {error}")
        if app.temp_role_granted_at is None and include_temp and self.settings.temp_role_id in held:
            self.store.update(app.id, temp_role_granted_at=rs.iso(now),
                              temp_role_expires_at=rs.iso(now + timedelta(days=self.settings.temp_role_days)))
        if problems:
            self.store.set_step(app.id, "roles", "failed", logic.truncate(" ".join(problems), 300))
        else:
            self.store.set_step(app.id, "roles", "done")

    async def _announce(self, app_id: str, retry_failed: bool = True) -> None:
        async with self.lock(app_id):
            app = self.require(app_id)
            if app.state != rs.ACTIVE:
                return

            def due(name: str) -> bool:
                status = step_status(app, name)
                return status not in ("done", "skipped") and (retry_failed or status != "failed")

            expiry = app.temp_role_expires_at if not app.temp_role_removed_at else None
            embed = ui.active_embed(app, expiry, self.thread_url(app))
            if due("announce"):
                message = await self.send_thread(app, content=f"<@{app.member_id}> welcome to the world!",
                                                 embed=embed, allowed_mentions=mentions(users=[app.member_id]))
                self.store.set_step(app_id, "announce", "done" if message else "failed",
                                    None if message else "Could not post in the registration thread.")
            if due("registrant_dm"):
                status, _ = await self.dm(app.member_id, content="Your nation registration is complete.",
                                          embed=embed)
                result = {"sent": "done", "forbidden": "skipped"}.get(status, "failed")
                self.store.set_step(app_id, "registrant_dm", result,
                                    "DMs are closed." if status == "forbidden" else None)
            if due("approver_dm"):
                if app.dm_message_id:
                    ok = await self._edit_message(app.dm_channel_id, app.dm_message_id, embed=embed, view=None)
                    self.store.set_step(app_id, "approver_dm", "done" if ok else "failed")
                else:
                    self.store.set_step(app_id, "approver_dm", "skipped")
            await self._edit_status(self.require(app_id))

    async def retry_roles(self, app_id: str) -> None:
        async with self.lock(app_id):
            app = self.require(app_id)
            if app.state == rs.ACTIVE:
                await self._provision_roles(app)
                await self._edit_status(self.require(app_id))

    async def expire_temp_roles(self, now: Any = None) -> int:
        removed = 0
        for due in self.store.due_temp_roles(now):
            async with self.lock(due.id):
                app = self.require(due.id)
                if app.temp_role_removed_at:
                    continue
                guild = self.bot.get_guild(app.guild_id)
                if guild is None:
                    continue
                try:
                    member = await self.fetch_member(guild, app.member_id)
                    role = guild.get_role(self.settings.temp_role_id)
                    if member is not None and role is not None and any(r.id == role.id for r in member.roles):
                        await member.remove_roles(role, reason="Temporary registration role expired")
                except discord.HTTPException as error:
                    self.store.set_step(app.id, "temp_role", "failed", logic.truncate(str(error), 300))
                    continue
                self.store.update(app.id, temp_role_removed_at=rs.iso())
                self.store.set_step(app.id, "temp_role", "done")
                self.store.log(app.id, "temp_role_removed")
                removed += 1
        return removed

    # Calendars -------------------------------------------------------------------

    async def on_calendar_decision(self, submission_id: str, status: str, calendar_data: dict) -> None:
        app = self.store.by_calendar_submission(submission_id)
        if app is None:
            return
        async with self.lock(app.id):
            app = self.require(app.id)
            if app.calendar_submission_id != submission_id:
                return
            if status == "approved":
                name = calendar_data.get("name")

                def convert(data: dict | None) -> dict | None:
                    if not data:
                        return data
                    choice = data.get("calendar") or {}
                    if choice.get("mode") == "new" and logic.clean(choice.get("name")).casefold() == \
                            logic.clean(name).casefold():
                        data = copy.deepcopy(data)
                        data["calendar"] = {"mode": "existing", "name": name}
                    return data

                self.store.update(app.id, draft=convert(app.draft) or {}, submitted=convert(app.submitted),
                                  approved=convert(app.approved))
                self.store.set_step(app.id, "calendar", "approved")
                await self.send_thread(app, content=f"{ui.DONE} The calendar **{name}** was approved.")
            else:
                self.store.update(app.id, calendar_submission_id=None)
                self.store.set_step(app.id, "calendar", "denied")
                text = (f"The proposed calendar **{calendar_data.get('name')}** was declined. Run `/register` "
                        "to revise it or choose an existing calendar. Your nation registration is not affected.")
                await self.send_thread(app, content=f"<@{app.member_id}> {text}",
                                       allowed_mentions=mentions(users=[app.member_id]))
                await self.dm(app.member_id, content=text)
            await self._edit_status(self.require(app.id))

    async def replace_calendar(self, app_id: str, actor_id: int, choice: dict) -> str:
        async with self.lock(app_id):
            app = self.require(app_id)
            self._check_owner(app, actor_id)
            if app.state not in POST_APPROVAL or step_status(app, "calendar") not in CALENDAR_RETRY:
                raise ActionError("Your calendar does not need changes right now.")
            if not logic.calendar_valid(choice):
                raise ActionError("Choose an existing calendar or create a new one.")

            def setcal(data: dict | None) -> dict | None:
                if data is None:
                    return None
                data = copy.deepcopy(data)
                data["calendar"] = copy.deepcopy(choice)
                return data

            self.store.update(app_id, draft=setcal(app.draft) or {}, submitted=setcal(app.submitted),
                              approved=setcal(app.approved), calendar_submission_id=None)
            self.store.set_step(app_id, "calendar", "queued" if choice["mode"] == "new" else "done")
        await self._queue_calendar(app_id)
        app = self.require(app_id)
        await self._edit_status(app)
        status = step_status(app, "calendar")
        if status == "done":
            return f"{ui.DONE} Your calendar is set to {choice['name']}."
        if status == "pending":
            return f"{ui.DONE} Your calendar was sent for approval."
        detail = (app.steps.get("calendar") or {}).get("detail")
        return f"{ui.WARN} The calendar could not be queued" + (f": {detail}" if detail else ".")

    async def _queue_calendar(self, app_id: str) -> None:
        async with self.lock(app_id):
            app = self.require(app_id)
            if app.state not in POST_APPROVAL:
                return
            choice = (app.approved or {}).get("calendar") or {}
            status = step_status(app, "calendar")
            if choice.get("mode") == "existing":
                if status not in ("done", "approved"):
                    self.store.set_step(app_id, "calendar", "done")
                return
            if choice.get("mode") != "new":
                return
            if app.calendar_submission_id or status in ("pending", "approved", "denied", "conflict"):
                return
            thread = await self.thread(app)
            try:
                existing = await cs.pending_for_registration(app.id)
                if existing and logic.clean(existing["calendar_data"].get("name")).casefold() == \
                        logic.clean(choice.get("name")).casefold():
                    submission_id = existing["submission_id"]
                else:
                    guild = self.bot.get_guild(app.guild_id)
                    member = await self.fetch_member(guild, app.member_id) if guild else None
                    submission_id = await cs.queue_calendar_submission(
                        self.bot, logic.calendar_submission_data(choice), app.member_id,
                        getattr(member, "name", None) or str(app.member_id),
                        registration_application_id=app.id, registration_url=self.thread_url(app),
                        fallback_channel=thread)
            except cs.CalendarConflict as conflict:
                self.store.set_step(app_id, "calendar", "conflict", logic.truncate(str(conflict), 300))
                await self.send_thread(app, content=(
                    f"<@{app.member_id}> {conflict} Run `/register` to choose another calendar."),
                    allowed_mentions=mentions(users=[app.member_id]))
                return
            except Exception as error:  # noqa: BLE001 - recorded for retry
                logger.exception("Queueing calendar failed app=%s", app_id)
                self.store.set_step(app_id, "calendar", "failed", logic.truncate(str(error), 300))
                return
            self.store.update(app_id, calendar_submission_id=submission_id)
            self.store.set_step(app_id, "calendar", "pending")

    # Amendments --------------------------------------------------------------------

    async def submit_amendment(self, app_id: str, actor_id: int) -> str:
        reviewed: list[str] = []
        async with self.lock(app_id):
            app = self.require(app_id)
            self._check_owner(app, actor_id)
            self._check_amendable(app)
            draft = app.draft or {}
            changed = logic.diff_fields(app.approved or {}, draft)
            if not changed:
                raise ActionError("Nothing has changed yet.")
            missing = logic.missing_items(draft)
            if missing:
                raise ActionError("Still missing: " + ", ".join(missing[:10]))
            direct = [k for k in changed if k in logic.DIRECT_AMEND_KEYS]
            reviewed = [k for k in changed if k not in logic.DIRECT_AMEND_KEYS]
            approved = logic.merge_fields(app.approved or {}, draft, direct)
            fields: dict[str, Any] = {"approved": approved}
            if "calendar" in direct:
                fields["calendar_submission_id"] = None
            if reviewed:
                fields.update(revision=app.revision + 1, submitted=copy.deepcopy(draft),
                              amendment={"fields": reviewed, "status": "pending",
                                         "revision": app.revision + 1, "posted": False},
                              notes=None)
            if not self.store.update(app_id, expect_state=rs.ACTIVE, expect_revision=app.revision, **fields):
                raise ActionError(STALE)
            if "calendar" in direct:
                new = (approved.get("calendar") or {}).get("mode") == "new"
                self.store.set_step(app_id, "calendar", "queued" if new else "done")
            self.store.log(app_id, "amendment_submitted", actor_id, ", ".join(changed))
            app = self.require(app_id)
            if direct:
                await self._post_changes(app, direct, approved, "Registration updated")
        await self._queue_calendar(app_id)
        if reviewed:
            await self.publish_amendment(app_id)
            return f"{ui.DONE} Your changes were sent to staff for review."
        await self._edit_status(self.require(app_id))
        return f"{ui.DONE} Your registration was updated."

    async def _post_changes(self, app: rs.Application, keys: list[str], data: dict, title: str) -> None:
        lines = []
        for key in keys:
            if key.startswith("files.") or key.startswith("lore_"):
                continue
            if key == "calendar":
                value = logic.calendar_label(data.get("calendar"))
            elif key == "system":
                value = logic.SYSTEMS.get(data.get("system"), ("Not chosen", ""))[0]
            else:
                value = logic.clean(data.get(key)) or "None"
            lines.append(f"**{logic.field_label(key)}** - {value}")
        if any(k.startswith("lore_") for k in keys):
            lines.append(f"**Lore** - updated ({logic.lore_length(data):,} characters, below)")
        text = "\n".join(lines) or "Images updated."
        for i, chunk in enumerate(logic.chunk_text(text, 4000)):
            await self.send_thread(app, embed=discord.Embed(
                title=f"{title} (revision {app.revision})" if i == 0 else None,
                description=chunk, colour=discord.Colour.blurple()))
        purposes = [k.split(".", 1)[1] for k in keys if k.startswith("files.")]
        for purpose, file in self.files_for(data, purposes):
            await self.send_thread(app, content=f"**{logic.UPLOAD_PURPOSES[purpose]}**", file=file)
        if any(k.startswith("lore_") for k in keys):
            for chunk in logic.chunk_text(logic.lore_text(data), 4000):
                await self.send_thread(app, embed=discord.Embed(description=chunk,
                                                                colour=discord.Colour.blurple()))

    async def publish_amendment(self, app_id: str, ping: bool = True) -> None:
        async with self.lock(app_id):
            app = self.require(app_id)
            amendment = dict(app.amendment or {})
            if app.state != rs.ACTIVE or amendment.get("status") != "pending":
                return
            thread = await self.thread(app)
            if thread is None:
                self.store.set_step(app_id, "amendment_publish", "failed", "The registration thread is missing.")
                return
            await self._unarchive(thread)
            try:
                if not amendment.get("posted"):
                    await self._post_changes(app, amendment.get("fields", []), app.submitted or {},
                                             "Requested changes")
                    amendment["posted"] = True
                    self.store.update(app_id, amendment=amendment)
                role = self.settings.staff_role_id
                message = await thread.send(
                    content=f"<@&{role}> an accepted nation requested changes." if ping else None,
                    embed=ui.status_embed(app, self.settings), view=ui.amendment_controls(app),
                    allowed_mentions=mentions(roles=[role]) if ping else NO_MENTIONS)
            except (discord.HTTPException, OSError) as error:
                self.store.set_step(app_id, "amendment_publish", "failed", logic.truncate(str(error), 300))
                return
            old = amendment.get("message_id")
            amendment["message_id"] = message.id
            self.store.update(app_id, amendment=amendment)
            self.store.set_step(app_id, "amendment_publish", "done", f"revision {app.revision}")
            if old and old != message.id:
                await self._edit_message(thread, old, view=None)

    async def decide_amendment(self, app_id: str, revision: int, reviewer: Any, decision: str,
                               reason: str | None = None) -> str:
        reason = logic.clean(reason) or None
        if decision != "approve" and not reason:
            raise ActionError("A reason is required.")
        system_changed = False
        async with self.lock(app_id):
            app = self.check_current(app_id, rs.ACTIVE, revision)
            amendment = dict(app.amendment or {})
            if amendment.get("status") != "pending":
                raise ActionError(STALE)
            self._check_reviewer(app, reviewer)
            amendment.update(status={"approve": "approved", "changes": "changes_requested",
                                     "decline": "declined"}[decision],
                             reviewer_id=reviewer.id, decided_at=rs.iso(), reason=reason)
            fields: dict[str, Any] = {"amendment": amendment}
            if decision == "approve":
                merged = logic.merge_fields(app.approved or {}, app.submitted or {}, amendment.get("fields", []))
                fields.update(approved=merged, draft=copy.deepcopy(merged), notes=None)
                system_changed = "system" in amendment.get("fields", [])
            elif decision == "changes":
                fields["notes"] = reason
            else:
                fields.update(notes=reason, draft=copy.deepcopy(app.approved or {}))
            if not self.store.update(app_id, expect_state=rs.ACTIVE, expect_revision=revision, **fields):
                raise ActionError(STALE)
            self.store.log(app_id, f"amendment_{decision}", reviewer.id, reason)
            app = self.require(app_id)
            await self._edit_message(app.thread_id, amendment.get("message_id"),
                                     embed=ui.status_embed(app, self.settings), view=None)
            if decision == "approve":
                text = f"<@{app.member_id}> your changes were approved by <@{reviewer.id}>."
            else:
                quoted = "\n".join("> " + line for line in logic.truncate(reason or "", 1500).splitlines())
                verb = "need more work" if decision == "changes" else "were declined"
                text = f"<@{app.member_id}> your requested changes {verb}:\n{quoted}"
                if decision == "changes":
                    text += "\nRun `/register` to update them."
            await self.send_thread(app, content=text, allowed_mentions=mentions(users=[app.member_id]))
            await self.dm(app.member_id, content=text)
        if system_changed:
            await self.retry_roles(app_id)
        return f"{ui.DONE} Changes {'approved' if decision == 'approve' else 'returned to the registrant'}."

    # Staff tools ---------------------------------------------------------------------

    async def retry(self, app_id: str) -> rs.Application:
        app = self.require(app_id)
        if app.state == rs.AWAITING_STAFF:
            if step_status(app, "publish") != "done":
                await self.publish(app_id, ping=True)
        elif app.state == rs.AWAITING_POPULATION:
            await self._queue_calendar(app_id)
            if step_status(self.require(app_id), "population_request") != "done":
                await self.send_population_request(app_id)
        elif app.state == rs.PROVISIONING:
            await self.provision(app_id)
        elif app.state == rs.ACTIVE:
            if step_status(app, "roles") == "failed":
                await self.retry_roles(app_id)
            if step_status(app, "amendment_publish") == "failed":
                await self.publish_amendment(app_id, ping=True)
            await self._queue_calendar(app_id)
            await self._announce(app_id, retry_failed=True)
        return self.require(app_id)

    async def reopen_review(self, app_id: str) -> str:
        app = self.require(app_id)
        if app.state == rs.AWAITING_STAFF:
            if app.thread_id and await self.thread(app) is None:
                self.store.update(app_id, thread_id=None, status_message_id=None)
                self.store.set_step(app_id, "publish_content", "pending")
            await self.publish(app_id, ping=False)
            return "Review controls reposted."
        if app.state == rs.ACTIVE and (app.amendment or {}).get("status") == "pending":
            await self.publish_amendment(app_id, ping=False)
            return "Amendment controls reposted."
        if app.state == rs.AWAITING_POPULATION:
            await self.send_population_request(app_id)
            return "Population request resent."
        raise ActionError("Nothing is awaiting review for that member.")

    async def link_existing(self, guild_id: int, member_id: int, nation_id: str, actor: Any) -> rs.Application:
        if not self.tracker.configured:
            raise ActionError("The tracker is not configured (WRP_POPS_URL / WRP_POPS_TOKEN).")
        app = self.store.live_for_member(guild_id, member_id)
        if app is not None and app.state == rs.PROVISIONING:
            async with self.lock(app.id):
                result = await self._link(app, nation_id)
                self.store.set_step(app.id, "tracker", "done", "linked")
                self.store.log(app.id, "linked", actor.id, str((result.get("nation") or {}).get("id")))
            await self.provision(app.id)
            return self.require(app.id)
        if app is not None:
            raise ActionError("That member has a live application; finish or withdraw it first.")
        app = self.store.create(guild_id, member_id, source="legacy", state=rs.ACTIVE, revision=1)
        try:
            result = await self._link(app, nation_id)
        except Exception:
            self.store.update(app.id, state=rs.WITHDRAWN)
            raise
        name = (result.get("nation") or {}).get("name") or "Linked nation"
        data = {"short_name": name}
        self.store.update(app.id, draft=data, submitted=data, approved=data)
        self.store.log(app.id, "linked", actor.id, str(nation_id))
        self._set_released(guild_id, member_id, False)
        return self.require(app.id)

    async def _link(self, app: rs.Application, nation_id: str) -> dict:
        try:
            result = await self.tracker.link_nation(guild_id=app.guild_id, member_id=app.member_id,
                                                    application_id=app.id, nation_id=str(nation_id),
                                                    thread_id=app.thread_id)
        except TrackerError as error:
            raise ActionError(f"Tracker: {error}") from error
        nation = result.get("nation") or {}
        self.store.update(app.id, tracker_nation_id=str(nation.get("id") or nation_id),
                          tracker_url=self.tracker.nation_url(result.get("nationPath")))
        return result

    async def release(self, guild_id: int, member_id: int, actor: Any) -> str:
        if self.tracker.configured:
            try:
                await self.tracker.release_member(guild_id=guild_id, member_id=member_id)
            except TrackerError as error:
                if error.status != 404:
                    raise ActionError(f"Tracker: {error}") from error
        app = self.store.live_for_member(guild_id, member_id)
        if app is not None and app.state == rs.ACTIVE:
            self.store.update(app.id, expect_state=rs.ACTIVE, state=rs.RELEASED)
            self.store.log(app.id, "released", actor.id)
        elif app is not None:
            raise ActionError("That member has an application in progress; withdraw it instead.")
        self._set_released(guild_id, member_id, True)
        return "Released. The member can register a new nation with `/register`."

    async def resume(self) -> None:
        """Continue interrupted work after a restart."""
        for app in self.store.list_states(rs.LIVE_STATES):
            try:
                if app.state == rs.AWAITING_STAFF and step_status(app, "publish") in (None, "pending"):
                    await self.publish(app.id, ping=True)
                elif app.state == rs.AWAITING_POPULATION:
                    if step_status(app, "calendar") != "failed":
                        await self._queue_calendar(app.id)
                    if step_status(app, "population_request") in (None, "pending"):
                        await self.send_population_request(app.id)
                elif app.state == rs.PROVISIONING and not app.failed_steps():
                    await self.provision(app.id)
                elif app.state == rs.ACTIVE and app.source != "legacy":
                    if step_status(app, "calendar") != "failed":
                        await self._queue_calendar(app.id)
                    if (app.amendment or {}).get("status") == "pending" and \
                            step_status(app, "amendment_publish") in (None, "pending"):
                        await self.publish_amendment(app.id)
                    await self._announce(app.id, retry_failed=False)
            except Exception:  # noqa: BLE001 - one bad application must not block the rest
                logger.exception("Resuming registration %s failed", app.id)

    def queue(self, guild_id: int) -> dict[str, list[rs.Application]]:
        live = self.store.list_states(rs.LIVE_STATES, guild_id)
        return {
            "review": [a for a in live if a.state == rs.AWAITING_STAFF
                       or (a.state == rs.ACTIVE and (a.amendment or {}).get("status") == "pending")],
            "population": [a for a in live if a.state == rs.AWAITING_POPULATION],
            "attention": [a for a in live if a.failed_steps() or a.state == rs.PROVISIONING],
        }
