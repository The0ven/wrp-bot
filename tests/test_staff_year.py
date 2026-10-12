import json

import calendar_submissions as cs


def write(tmp_path, rows, calendars=None):
    config = tmp_path / "config.json"
    history = tmp_path / "history.jsonl"
    calendars = calendars or [{"name": "Staff Years", "key": "sy", "is_staff_years": True},
                              {"name": "Other", "key": "al", "is_staff_years": False}]
    config.write_text(json.dumps({"calendars": calendars}), encoding="utf-8")
    history.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(config), str(history)


def test_uses_last_announced_year(tmp_path):
    paths = write(tmp_path, [
        {"timestamp": 1, "sy": 724.24, "al": 819.2, "printed": 1.0},
        {"timestamp": 2, "sy": 725.24, "al": 820.2, "printed": 1.0},
        {"timestamp": 3, "sy": 725.69, "al": 820.7, "printed": None},
    ])
    assert cs.current_staff_year(*paths) == 725


def test_falls_back_to_latest_value_and_skips_bad_lines(tmp_path):
    config, history = write(tmp_path, [{"timestamp": 1, "sy": 721.9}])
    with open(history, "a", encoding="utf-8") as fh:
        fh.write("not json\n")
    assert cs.current_staff_year(config, history) == 721


def test_missing_files_or_staff_calendar_return_none(tmp_path):
    assert cs.current_staff_year(str(tmp_path / "nope.json"), str(tmp_path / "nope.jsonl")) is None
    paths = write(tmp_path, [{"timestamp": 1, "sy": 1.0}],
                  calendars=[{"name": "Other", "key": "al", "is_staff_years": False}])
    assert cs.current_staff_year(*paths) is None
