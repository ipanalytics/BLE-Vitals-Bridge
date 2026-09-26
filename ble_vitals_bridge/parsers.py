"""Frame parsers, taken from the Bluetooth SIG specifications rather than from a datasheet.

Two devices, two standards, and both have a trap in the first byte:

* Blood Pressure Measurement (0x2A35) is ISO/IEEE 11073: the numbers are 16-bit SFLOATs, not
  integers. Reading them as ``int`` gives 128/84 as 15616/10752 — a mistake that looks like a
  broken cuff, not like a parsing bug.
* Weight Measurement (0x2A9D) is a plain uint16 in units of 0.005 kg, but bit 0 flips the whole
  frame to imperial units, where the unit is 0.01 lb. A scale that reports 0.01 kg steps is a
  scale whose bit 0 was ignored.

Every parser returns a plain dict and raises ValueError on a frame that is too short: the caller
decides whether that is worth a retry.
"""

from __future__ import annotations

from typing import Any

from .models import KG_PER_POUND, normalize_moment


def sfloat(raw: int) -> float:
    """ISO/IEEE 11073 16-bit SFLOAT: 12-bit mantissa, 4-bit signed exponent."""
    mantissa = raw & 0x0FFF
    exponent = raw >> 12
    if exponent >= 0x8:
        exponent -= 0x10
    if mantissa >= 0x800:
        mantissa -= 0x1000
    return float(mantissa * (10**exponent))


def parse_blood_pressure(data: bytes) -> dict:
    """0x2A35: flags(1) + systolic + diastolic + mean + [timestamp] + [pulse] + [user id] + status."""
    if len(data) < 7:
        raise ValueError(f"a blood-pressure frame needs at least 7 bytes, got {len(data)}")
    flags = data[0]
    frame: dict[str, Any] = {
        "systolic": round(sfloat(int.from_bytes(data[1:3], "little")), 1),
        "diastolic": round(sfloat(int.from_bytes(data[3:5], "little")), 1),
        "map": round(sfloat(int.from_bytes(data[5:7], "little")), 1),
    }
    offset = 7
    if flags & 0x02:
        if len(data) < offset + 7:
            raise ValueError("the frame claims a timestamp but is too short to hold one")
        year = int.from_bytes(data[offset : offset + 2], "little")
        frame["timestamp"] = (
            f"{year:04d}-{data[offset + 2]:02d}-{data[offset + 3]:02d}"
            f"T{data[offset + 4]:02d}:{data[offset + 5]:02d}:{data[offset + 6]:02d}"
        )
        offset += 7
    if flags & 0x04:
        if len(data) < offset + 2:
            raise ValueError("the frame claims a pulse but is too short to hold one")
        frame["pulse"] = round(sfloat(int.from_bytes(data[offset : offset + 2], "little")), 1)
        offset += 2
    if flags & 0x08 and len(data) > offset:
        frame["user_id"] = data[offset]
        offset += 1
    if len(data) > offset:
        frame["status"] = int.from_bytes(data[offset : offset + 2], "little")
    frame["moment"] = normalize_moment(frame.get("timestamp"))
    return frame


def parse_weight_measurement(data: bytes) -> dict:
    """0x2A9D: flags(1) + weight(2) [+ timestamp(7)] [+ user id(1)] [+ bmi(2) + height(2)]."""
    if len(data) < 3:
        raise ValueError(f"a weight frame needs at least 3 bytes, got {len(data)}")
    flags = data[0]
    raw = int.from_bytes(data[1:3], "little")
    pounds = bool(flags & 0x01)
    kilograms = raw * (0.01 * KG_PER_POUND if pounds else 0.005)
    frame: dict[str, Any] = {"weight": round(kilograms, 3), "unit": "kg", "flags": flags, "imperial": pounds}
    offset = 3
    if flags & 0x02:
        if len(data) < offset + 7:
            raise ValueError("the frame claims a timestamp but is too short to hold one")
        year = int.from_bytes(data[offset : offset + 2], "little")
        frame["ts_device"] = (
            f"{year:04d}-{data[offset + 2]:02d}-{data[offset + 3]:02d}"
            f"T{data[offset + 4]:02d}:{data[offset + 5]:02d}:{data[offset + 6]:02d}"
        )
        offset += 7
    if flags & 0x04 and len(data) > offset:
        frame["user_id"] = data[offset]
        offset += 1
    if flags & 0x08 and len(data) >= offset + 4:
        frame["bmi"] = round(int.from_bytes(data[offset : offset + 2], "little") * 0.1, 1)
        frame["height_m"] = round(int.from_bytes(data[offset + 2 : offset + 4], "little") * 0.001, 3)
    frame["moment"] = normalize_moment(frame.get("ts_device"))
    return frame


def parse_body_composition(data: bytes) -> dict:
    """0x2A9C: flags(2), then optional fields in a fixed order — we take weight and fat only.

    The order matters and the fields are variable-length, so anything we do not need is still
    consumed: a parser that skips a field it does not understand silently misreads every field
    after it.
    """
    if len(data) < 2:
        raise ValueError(f"a body-composition frame needs at least 2 bytes, got {len(data)}")
    flags = int.from_bytes(data[0:2], "little")
    body = data[2:]
    position = 0

    def take(count: int) -> bytes:
        nonlocal position
        if position + count > len(body):
            raise ValueError("the body-composition frame ended before its flags said it would")
        chunk = body[position : position + count]
        position += count
        return chunk

    frame: dict = {"flags": flags}
    if flags & 0x0001:
        frame["body_fat"] = round(int.from_bytes(take(2), "little") * 0.1, 1)
    if flags & 0x0002:
        stamp = take(7)
        year = int.from_bytes(stamp[0:2], "little")
        frame["ts_device"] = f"{year:04d}-{stamp[2]:02d}-{stamp[3]:02d}T{stamp[4]:02d}:{stamp[5]:02d}:{stamp[6]:02d}"
    if flags & 0x0004:
        frame["user_id"] = take(1)[0]
    if flags & 0x0008:
        take(2)  # basal metabolism — not stored, still consumed
    if flags & 0x0010:
        take(2)  # muscle percentage
    if flags & 0x0020:
        take(2)  # muscle mass
    if flags & 0x0040:
        take(2)  # fat free mass
    if flags & 0x0080:
        take(2)  # soft lean mass
    if flags & 0x0100:
        take(2)  # body water mass
    if flags & 0x0200:
        frame["impedance"] = round(int.from_bytes(take(2), "little") * 0.1, 1)
    if flags & 0x0400:
        frame["weight"] = round(int.from_bytes(take(2), "little") * 0.005, 3)
        frame["unit"] = "kg"
    if flags & 0x0800:
        frame["height_m"] = round(int.from_bytes(take(2), "little") * 0.001, 3)
    frame["moment"] = normalize_moment(frame.get("ts_device"))
    return frame
