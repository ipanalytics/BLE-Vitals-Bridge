from __future__ import annotations

import pytest
from conftest import body_composition_frame, bp_frame, imperial_frame, weight_frame

from ble_vitals_bridge import models, parsers


def test_blood_pressure_frame_reads_the_numbers_not_the_bytes():
    frame = parsers.parse_blood_pressure(bp_frame(128, 84, 93, 60))
    assert (frame["systolic"], frame["diastolic"], frame["map"], frame["pulse"]) == (128, 84, 93, 60)
    assert frame["timestamp"] == "1999-02-03T10:05:00"


def test_a_frame_without_a_timestamp_still_parses():
    frame = parsers.parse_blood_pressure(bytes([0x00]) + bp_frame(120, 80, 93)[1:7])
    assert frame["systolic"] == 120
    assert "timestamp" not in frame


def test_a_short_frame_is_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        parsers.parse_blood_pressure(bytes([0x00, 0x78, 0x00]))


def test_sfloat_is_signed_and_scaled():
    assert parsers.sfloat(120) == 120.0
    assert parsers.sfloat((0x03 << 12) | 120) == 120000.0
    assert parsers.sfloat((0x0E << 12) | 120) == 1.2


def test_metric_weight_frame_is_kilograms():
    frame = parsers.parse_weight_measurement(weight_frame(70.0))
    assert frame["weight"] == pytest.approx(70.0, abs=0.01)
    assert frame["ts_device"] == "1999-02-03T10:00:00"
    assert frame["imperial"] is False


def test_the_imperial_bit_is_what_turns_kilograms_into_pounds():
    frame = parsers.parse_weight_measurement(imperial_frame(188.0))
    assert frame["imperial"] is True
    assert frame["weight"] == pytest.approx(85.28, abs=0.05)


def test_body_composition_consumes_the_fields_it_does_not_need():
    frame = parsers.parse_body_composition(body_composition_frame(70.0, 22.0))
    assert frame["body_fat"] == pytest.approx(22.0, abs=0.05)
    assert frame["weight"] == pytest.approx(70.0, abs=0.01)


def test_readings_keep_units_and_share_a_group():
    frame = parsers.parse_blood_pressure(bp_frame())
    readings = models.from_blood_pressure(frame, "cuff")
    metrics = {reading.metric for reading in readings}
    assert metrics == {"systolic", "diastolic", "mean_arterial", "pulse"}
    assert len({reading.group_id for reading in readings}) == 1
    assert {reading.unit for reading in readings} == {"mmHg", "bpm"}


def test_a_reading_without_a_moment_gets_the_current_one():
    reading = models.Reading("weight", 70.0, None, "scale")
    assert reading.taken_at
    assert reading.dedupe_key.endswith("70")


def test_moments_are_normalised_or_replaced():
    assert models.normalize_moment("1999-02-03T10:00:00Z").startswith("1999-02-03T")
    assert models.normalize_moment("nonsense") != "nonsense"


def test_an_unknown_metric_is_refused():
    with pytest.raises(ValueError):
        models.Reading("mood", 7, None, "diary")
