"""Where readings come from: a log file today, a radio when the device is in range.

The import path is not a leftover — it is the only way to start: the older per-device scripts
wrote JSON lines, and a bridge that cannot read them begins with an empty database and a story
about a fresh start. Import is idempotent (the store deduplicates), so pointing it at the same
file twice is safe.

Bluetooth lives behind a lazy import: the package installs and every test runs on a machine
without a radio, and the error a user sees when they ask for a device without ``bleak`` installed
says what to install.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import pathlib

from . import models

BP_SERVICE = "00001810-0000-1000-8000-00805f9b34fb"
BP_MEASUREMENT = "00002a35-0000-1000-8000-00805f9b34fb"
WEIGHT_SERVICE = "0000181d-0000-1000-8000-00805f9b34fb"
WEIGHT_MEASUREMENT = "00002a9d-0000-1000-8000-00805f9b34fb"
BODY_COMPOSITION = "00002a9c-0000-1000-8000-00805f9b34fb"

CUFF_HINTS = ("bm59", "bm 59", "beurer", "blood pressure", "tensi")
SCALE_HINTS = ("scale", "xiaomi", "mi scale", "s400", "s800", "renpho", "beurer", "withings", "qardio", "eufy")


def readings_from_record(record: dict, source: str, device: str = "") -> list:
    """A JSON object from a log becomes readings. The keys decide which device wrote it.

    A row this bridge does not understand (a step count, a mood, a device we have not met) is not
    an error: it is left alone and counted, so an import of ten years of mixed logs still reports
    what it did rather than stopping at the first unknown line.
    """
    try:
        if record.get("metric") and record.get("value") is not None:
            moment = record.get("ts") or record.get("timestamp") or record.get("moment")
            return [models.Reading(str(record["metric"]), record["value"], moment, source, device=device, raw=record)]
        if "systolic" in record or "diastolic" in record:
            return models.from_blood_pressure(record, source, device)
        if "weight" in record or "body_fat" in record:
            return models.from_scale(record, source, device)
    except ValueError:
        return []
    return []


def import_jsonl(path, store, source: str = "", device: str = "") -> dict:
    """Read a JSON-lines file into the store. Unreadable lines are counted, never guessed at."""
    target = pathlib.Path(path).expanduser()
    lines = [line.strip() for line in target.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    source = source or target.stem
    inserted = known = skipped = 0
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(record, dict):
            skipped += 1
            continue
        readings = readings_from_record(record, source, device)
        if not readings:
            skipped += 1
            continue
        added, already = store.add(readings)
        inserted += added
        known += already
    return {"file": str(target), "lines": len(lines), "inserted": inserted, "known": known, "skipped": skipped}


def _bleak():
    try:
        import bleak
    except ModuleNotFoundError as exc:  # the base install stays radio-free on purpose
        raise RuntimeError("Bluetooth needs bleak: pip install 'ble-vitals-bridge[ble]'") from exc
    return bleak


async def _find(name_hints, service: str | None, timeout: float):
    bleak = _bleak()
    devices = await bleak.BleakScanner.discover(timeout=timeout)
    for device in devices:
        name = (device.name or "").lower()
        if any(hint in name for hint in name_hints):
            return device
    if service:
        found = await bleak.BleakScanner.discover(timeout=timeout, service_uuids=[service])
        if found:
            return found[0]
    return None


async def _watch(address: str | None, name_hints, service: str | None, notify, timeout: float, parser) -> list:
    """The shared shape of both devices: find, subscribe, wait for one notification, parse."""
    bleak = _bleak()
    if address:
        target = address
    else:
        device = await _find(name_hints, service, min(timeout, 20.0))
        if device is None:
            raise RuntimeError("no device found: switch it on, then try again with --address")
        target = device.address
    received: list = []
    done = asyncio.Event()

    def handle(_sender, data):
        if received:
            return
        received.extend(parser(bytes(data)))
        done.set()

    async with bleak.BleakClient(target) as client:
        for characteristic in notify:
            await client.start_notify(characteristic, handle)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=timeout)
        for characteristic in notify:
            with contextlib.suppress(Exception):  # a client that walked away is not worth raising
                await client.stop_notify(characteristic)
    return received


def watch_blood_pressure(address: str | None = None, timeout: float = 180, source: str = "cuff") -> list:
    from .parsers import parse_blood_pressure

    frames = asyncio.run(
        _watch(
            address,
            CUFF_HINTS,
            BP_SERVICE,
            {BP_MEASUREMENT},
            timeout,
            lambda data: [parse_blood_pressure(data)],
        )
    )
    return models.from_blood_pressure(frames[0], source) if frames else []


def watch_scale(address: str | None = None, timeout: float = 180, source: str = "scale") -> list:
    from .parsers import parse_body_composition, parse_weight_measurement

    def parser(data: bytes) -> list:
        for parse in (parse_weight_measurement, parse_body_composition):
            try:
                return [parse(data)]
            except ValueError:
                continue
        return []

    frames = asyncio.run(
        _watch(address, SCALE_HINTS, WEIGHT_SERVICE, {WEIGHT_MEASUREMENT, BODY_COMPOSITION}, timeout, parser)
    )
    if not frames:
        return []
    frame = frames[0]
    return models.from_scale(frame, source) if "weight" in frame else []
