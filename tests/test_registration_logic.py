from types import SimpleNamespace

import registration_logic as rl
from registration_settings import RegistrationSettings


def complete_data():
    data = {key: "Value" for key, field in rl.FIELDS.items() if field.required}
    data["lore_1"] = "x" * rl.LORE_MIN
    data["calendar"] = {"mode": "existing", "name": "Gregorian"}
    data["system"] = "closed"
    data["files"] = {"flag": 1, "claim_map": 2}
    data["acknowledgements"] = list(rl.ACKNOWLEDGEMENTS)
    return data


def test_complete_record_has_nothing_missing():
    assert rl.missing_items(complete_data()) == []


def test_missing_items_reports_each_gap():
    data = complete_data()
    del data["capital"]
    data["files"] = {"flag": 1}
    data["acknowledgements"] = []
    data.pop("system")
    missing = rl.missing_items(data)
    assert missing
    joined = " ".join(missing).lower()
    assert "capital" in joined


def test_lore_boundaries():
    data = complete_data()
    data["lore_1"] = ""
    assert rl.section_missing(data, "lore") == ["Lore"]
    data["lore_1"] = "x" * (rl.LORE_MIN - 1)
    assert rl.section_missing(data, "lore") == ["Lore needs 1 more characters"]
    data["lore_1"] = "x" * rl.LORE_MIN
    assert rl.section_missing(data, "lore") == []


def test_lore_length_sums_trimmed_parts():
    data = {"lore_1": "  " + "a" * 1500 + "  ", "lore_2": "\n" + "b" * 500 + "\n"}
    assert rl.lore_length(data) == 2000
    assert rl.section_missing(dict(complete_data(), **data), "lore") == []


def test_long_lore_split_across_parts():
    data = complete_data()
    data["lore_1"] = "a" * 1000
    data["lore_2"] = "b" * 500
    data["lore_3"] = "c" * 499
    assert rl.section_missing(data, "lore") == ["Lore needs 1 more characters"]


def test_chunk_text_respects_limit_and_prefers_breaks():
    text = ("word " * 300).strip() + "\n" + ("line " * 300).strip()
    chunks = rl.chunk_text(text, 1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks).replace("\n", "").replace(" ", "") == text.replace("\n", "").replace(" ", "")
    assert rl.chunk_text("short", 100) == ["short"]


def test_truncate():
    assert len(rl.truncate("x" * 50, 10)) <= 10
    assert rl.truncate("abc", 10) == "abc"


def test_calendar_names_sorted_and_staff_excluded():
    cals = [
        {"name": "zeta"},
        {"name": "Alpha"},
        {"name": "Staff", "is_staff_years": True},
    ]
    names = rl.calendar_names(cals)
    assert "Staff" not in names
    assert names == ["Alpha", "zeta"]


def test_calendar_page_clamps():
    names = [f"c{i:02d}" for i in range(60)]
    items, page, pages = rl.calendar_page(names, 0)
    assert len(items) == 25 and page == 0 and pages == 3
    items, page, pages = rl.calendar_page(names, 99)
    assert page == 2 and len(items) == 10
    items, page, pages = rl.calendar_page(names, -5)
    assert page == 0
    assert rl.calendar_page([], 3) == ([], 0, 1)


def test_validate_new_calendar():
    cals = [{"name": "Gregorian", "key": "GC"}]
    result, err = rl.validate_new_calendar("Avalon Reckoning", "AR", "1,200", "2", cals)
    assert err is None
    assert result == {
        "mode": "new",
        "name": "Avalon Reckoning",
        "key": "AR",
        "current_year": 1200,
        "staff_years_per_year": 2.0,
    }
    assert rl.validate_new_calendar("gregorian", "XX", "1", "1", cals)[1]
    assert rl.validate_new_calendar("Fresh", "gc", "1", "1", cals)[1]
    assert rl.validate_new_calendar("New", "XX", "1", "0", cals)[1]
    assert rl.validate_new_calendar("New", "XX", "-1", "1", cals)[1]
    assert rl.validate_new_calendar("New", "XX", "abc", "1", cals)[1]
    pending = [{"calendar_data": {"name": "Pending One", "key": "PO"}}]
    assert rl.validate_new_calendar("pending one", "ZZ", "1", "1", cals, pending)[1]


def test_role_plan_closed_and_open():
    s = RegistrationSettings()
    add, remove = rl.role_plan([], s, "closed", extra_ids=[11, 11, 12])
    assert add == [s.player_role_id, s.temp_role_id, s.closed_role_id, 11, 12]
    assert remove == []
    add, remove = rl.role_plan([s.player_role_id, s.closed_role_id], s, "open", include_temp=False)
    assert add == [s.open_role_id]
    assert remove == [s.closed_role_id]


def test_is_staff():
    staff_id = 929039388434898964
    admin = SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True), roles=[])
    staff = SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=False), roles=[SimpleNamespace(id=staff_id)]
    )
    nobody = SimpleNamespace(guild_permissions=SimpleNamespace(administrator=False), roles=[])
    assert rl.is_staff(admin, staff_id)
    assert rl.is_staff(staff, staff_id)
    assert not rl.is_staff(nobody, staff_id)


def test_custom_id_round_trip():
    cid = rl.make_custom_id("staff", "review", "a1b2", 3)
    assert cid == "wrpreg:staff:review:a1b2:3"
    parsed = rl.parse_custom_id(cid)
    assert parsed is not None
    assert tuple(str(p) for p in parsed) == ("staff", "review", "a1b2", "3")
    assert rl.parse_custom_id("other:thing") is None
    assert rl.parse_custom_id("wrpreg:staff:review:a1b2:notanint") is None
    assert rl.parse_custom_id(None) is None


def test_diff_and_merge_fields():
    old = {"capital": "A", "files": {"flag": 1, "claim_map": 2}}
    new = {"capital": "B", "files": {"flag": 1, "claim_map": 3}}
    changed = rl.diff_fields(old, new)
    assert "capital" in changed
    assert "files.claim_map" in changed
    assert "files.flag" not in changed
    merged = rl.merge_fields({"capital": "A", "cities": "X"}, {"capital": "B", "cities": ""}, ["capital", "cities"])
    assert merged["capital"] == "B"
    assert "cities" not in merged
