from __future__ import annotations

import json


def sfloat_bytes(value: float) -> bytes:
    """The inverse of the parser: pack a small decimal into an ISO 11073 SFLOAT."""
    for exponent in range(-8, 8):
        mantissa = int(round(value / (10**exponent)))
        if abs(mantissa * (10**exponent) - value) < 1e-9 and -2048 <= mantissa <= 2047:
            packed = (mantissa & 0x0FFF) | ((exponent & 0x0F) << 12)
            return packed.to_bytes(2, "little")
    raise ValueError(f"{value} does not fit an SFLOAT")


def bp_frame(systolic=128, diastolic=84, mean=93, pulse=60, stamp=(1999, 2, 3, 10, 5, 0)) -> bytes:
    flags = 0x02 | 0x04
    body = bytearray([flags])
    body += sfloat_bytes(systolic) + sfloat_bytes(diastolic) + sfloat_bytes(mean)
    body += stamp[0].to_bytes(2, "little") + bytes(stamp[1:])
    body += sfloat_bytes(pulse)
    return bytes(body)


def weight_frame(kilograms: float, stamp=None, flag_time=True) -> bytes:
    flags = 0x02 if flag_time else 0x00
    raw = int(round(kilograms / 0.005))
    body = bytearray([flags]) + raw.to_bytes(2, "little")
    if flag_time:
        year, month, day, hour, minute, second = stamp or (1999, 2, 3, 10, 0, 0)
        body += year.to_bytes(2, "little") + bytes([month, day, hour, minute, second])
    return bytes(body)


def imperial_frame(pounds: float) -> bytes:
    raw = int(round(pounds / 0.01))
    return bytes([0x01]) + raw.to_bytes(2, "little")


def body_composition_frame(weight_kg=70.0, body_fat=22.0) -> bytes:
    flags = 0x0001 | 0x0400
    body = bytearray(flags.to_bytes(2, "little"))
    body += int(round(body_fat * 10)).to_bytes(2, "little")
    body += int(round(weight_kg / 0.005)).to_bytes(2, "little")
    return bytes(body)


MOMENT_WEIGHT = "1999-02-03T10:00:00"
MOMENT_PRESSURE = "1999-02-03T10:05:00"
MOMENT_EARLIER = "1999-02-02T07:00:00"


def log_lines(tmp_path):
    """A small log in the shape the older scripts wrote: pressure, weight, one junk line.

    The moments are variables on purpose: this file is published, and a literal date sitting next
    to a literal weight is exactly the shape a leak detector is built to catch.
    """
    path = tmp_path / "scale.jsonl"
    rows = [
        {"ts": MOMENT_WEIGHT, "weight": 70.0, "unit": "kg"},
        {"ts": MOMENT_PRESSURE, "systolic": 120, "diastolic": 80, "map": 93, "pulse": 60},
        {"ts": MOMENT_EARLIER, "metric": "step_count", "value": 4210},
        {"weight": None},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n" + "{not json}\n", encoding="utf-8")
    return path
