from datetime import timedelta

import pytest

import registration_store as rs


@pytest.fixture
def store(tmp_path):
    s = rs.RegistrationStore(str(tmp_path / "reg.db"))
    yield s
    s.close()


def test_create_and_get(store):
    app = store.create(1, 2)
    got = store.get(app.id)
    assert got.state == rs.DRAFT
    assert got.guild_id == 1 and got.member_id == 2
    assert got.nation_name == "Unnamed nation"
    assert store.live_for_member(1, 2).id == app.id


def test_one_live_application_per_member(store):
    app = store.create(1, 2)
    with pytest.raises(rs.DuplicateApplication):
        store.create(1, 2)
    store.create(1, 3)
    store.create(9, 2)
    assert store.update(app.id, state=rs.WITHDRAWN)
    again = store.create(1, 2)
    assert again.id != app.id


def test_update_guards_state_and_revision(store):
    app = store.create(1, 2, state=rs.AWAITING_STAFF, revision=2)
    assert not store.update(app.id, expect_state=rs.DRAFT, state=rs.REJECTED)
    assert not store.update(app.id, expect_revision=1, state=rs.REJECTED)
    assert store.update(app.id, expect_state=rs.AWAITING_STAFF, expect_revision=2, state=rs.AWAITING_POPULATION)
    assert store.get(app.id).state == rs.AWAITING_POPULATION
    with pytest.raises(ValueError):
        store.update(app.id, not_a_column=1)


def test_json_fields_round_trip(store):
    app = store.create(1, 2, submitted={"short_name": "Avalon", "official_name": "Kingdom of Avalon"})
    store.update(app.id, review={"region": "North", "faith_role_ids": [5]})
    got = store.get(app.id)
    assert got.nation_name == "Avalon"
    assert got.review["faith_role_ids"] == [5]


def test_steps_and_failed_steps(store):
    app = store.create(1, 2)
    store.set_step(app.id, "tracker", "done")
    store.set_step(app.id, "roles", "failed", "Missing permissions")
    got = store.get(app.id)
    assert got.steps["roles"]["status"] == "failed"
    assert got.steps["roles"]["detail"] == "Missing permissions"
    assert got.failed_steps() == ["roles"]


def test_list_states_and_calendar_lookup(store):
    a = store.create(1, 2, state=rs.AWAITING_STAFF)
    b = store.create(1, 3, state=rs.AWAITING_POPULATION, calendar_submission_id="sub-1")
    store.create(2, 4, state=rs.AWAITING_STAFF)
    ids = {x.id for x in store.list_states([rs.AWAITING_STAFF, rs.AWAITING_POPULATION], guild_id=1)}
    assert ids == {a.id, b.id}
    assert store.by_calendar_submission("sub-1").id == b.id
    assert store.by_calendar_submission("missing") is None


def test_due_temp_roles(store):
    now = rs.utcnow()
    due = store.create(1, 2, state=rs.ACTIVE)
    later = store.create(1, 3, state=rs.ACTIVE)
    removed = store.create(1, 4, state=rs.ACTIVE)
    store.update(due.id, temp_role_expires_at=rs.iso(now - timedelta(minutes=1)))
    store.update(later.id, temp_role_expires_at=rs.iso(now + timedelta(days=1)))
    store.update(
        removed.id,
        temp_role_expires_at=rs.iso(now - timedelta(days=1)),
        temp_role_removed_at=rs.iso(now),
    )
    assert [a.id for a in store.due_temp_roles(now)] == [due.id]


def test_files_events_settings(store, tmp_path):
    app = store.create(1, 2)
    fid = store.add_file(app.id, "flag", str(tmp_path / "a.png"), "a.png", "image/png", 10)
    assert isinstance(fid, int)
    store.set_file_path(fid, str(tmp_path / "b.png"))
    f = store.get_file(fid)
    assert f["path"].endswith("b.png")
    assert f["purpose"] == "flag"
    assert store.get_file(None) is None
    store.log(app.id, "submitted", 2, "rev 1")
    assert len(store.events(app.id)) == 1
    assert store.get_setting("x", "d") == "d"
    store.set_setting("x", "y")
    assert store.get_setting("x") == "y"


def test_iso_round_trip():
    now = rs.utcnow()
    assert now.tzinfo is not None
    assert rs.parse_iso(rs.iso(now)) == now
