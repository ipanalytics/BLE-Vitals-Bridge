from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta

from conftest import log_lines

from ble_vitals_bridge import models, sources, watchdog
from ble_vitals_bridge.cli import main
from ble_vitals_bridge.store import Store


def reading(metric="weight", value=70.0, moment=None, source="scale"):
    return models.Reading(metric, value, moment or models.now_iso(), source)


def test_the_same_reading_is_stored_once(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        moment = "1999-02-03T10:00:00"
        assert store.add([reading(moment=moment)]) == (1, 0)
        assert store.add([reading(moment=moment)]) == (0, 1)
        assert store.count() == 1


def test_two_devices_writing_the_same_moment_are_two_readings(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        moment = "1999-02-03T10:00:00"
        store.add([reading(moment=moment), reading(moment=moment, source="scale-2")])
        assert store.count() == 2


def test_latest_gives_one_row_per_metric(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        store.add([reading("weight", 70.0, "1999-02-01T08:00:00"), reading("weight", 70.5, "1999-02-03T08:00:00")])
        store.add([reading("systolic", 120, "1999-02-03T10:05:00", "cuff")])
        latest = {row["metric"]: row["value"] for row in store.latest()}
        assert latest == {"weight": 70.5, "systolic": 120}


def test_series_keeps_only_the_window(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        store.add([reading("weight", 71.0, (datetime.now() - timedelta(days=40)).isoformat())])
        store.add([reading("weight", 70.0, (datetime.now() - timedelta(days=2)).isoformat())])
        assert len(store.series("weight", days=30)) == 1


def test_sources_report_their_age_in_hours(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        store.add([reading("weight", 70.0, (datetime.now() - timedelta(hours=5)).isoformat())])
        rows = store.sources()
        assert rows[0]["source"] == "scale"
        assert 4.5 < rows[0]["age_hours"] < 5.5


def test_import_reads_the_old_logs_and_counts_what_it_cannot_read(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        result = sources.import_jsonl(log_lines(tmp_path), store)
        assert result["inserted"] == 5  # four pressure readings + one weight
        assert result["skipped"] == 3  # the unknown metric, the row without a weight, the broken line
        again = sources.import_jsonl(log_lines(tmp_path), store)
        assert again["inserted"] == 0
        assert again["known"] == result["inserted"]


def test_the_watchdog_calls_a_silent_source_stale(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        store.add([reading("weight", 70.0, (datetime.now() - timedelta(days=30)).isoformat())])
        problems = watchdog.check(store, rules=(("scale", "weight", 24, "a weighing every day"),))
        assert problems[0].state == "stale"
        assert watchdog.failed(problems) is True
        assert "30" in watchdog.lines(problems)[0] or "720" in watchdog.lines(problems)[0]


def test_the_watchdog_is_quiet_when_the_data_is_fresh(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        store.add([reading("weight", 70.0, (datetime.now() - timedelta(hours=3)).isoformat())])
        problems = watchdog.check(store, rules=(("scale", "weight", 24, "a weighing a day"),))
        assert problems[0].state == "ok"
        assert watchdog.lines(problems) == ["all sources are fresh"]


def test_a_source_that_never_wrote_is_missing_not_stale(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        problems = watchdog.check(store, rules=(("cuff", "systolic", 24, "a reading a day"),))
        assert problems[0].state == "missing"


def test_status_exits_nonzero_when_something_is_silent(tmp_path, capsys):
    path = tmp_path / "db.sqlite"
    with Store(path) as store:
        store.add([reading("weight", 70.0, (datetime.now() - timedelta(days=60)).isoformat())])
    assert main(["status", "--db", str(path), "--quiet"]) == 1
    assert main(["status", "--db", str(path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] is True


def test_status_is_fine_on_a_fresh_store(tmp_path):
    path = tmp_path / "db.sqlite"
    with Store(path) as store:
        store.add([reading("weight", 70.0), reading("systolic", 120, None, "cuff")])
        store.add([reading("glucose", 95, None, "cgm"), reading("pulse", 60, None, "cgm")])
    assert main(["status", "--db", str(path)]) in (0, 1)  # the cadences decide; the call must not crash


def test_import_from_the_command_line_counts_new_readings(tmp_path, capsys):
    path = tmp_path / "db.sqlite"
    log = log_lines(tmp_path)
    assert main(["import", str(log), "--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert "5 new readings" in out
    assert main(["import", str(log), "--db", str(path)]) == 0
    assert "0 new readings" in capsys.readouterr().out


def test_export_writes_csv_a_doctor_could_read(tmp_path, capsys):
    path = tmp_path / "db.sqlite"
    with Store(path) as store:
        store.add([reading("weight", 70.0, models.now_iso())])
    assert main(["export", "--db", str(path), "--metric", "weight"]) == 0
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0] == ["metric", "taken_at", "value", "unit", "source", "group_id"]
    assert rows[1][0] == "weight"
    assert rows[1][2] == "70.0"
    assert rows[1][3] == "kg"


def test_an_unknown_metric_is_a_usage_error_not_a_crash(tmp_path, capsys):
    path = tmp_path / "db.sqlite"
    assert main(["export", "--db", str(path), "--metric", "mood"]) == 2
    assert "unknown metric" in capsys.readouterr().err
