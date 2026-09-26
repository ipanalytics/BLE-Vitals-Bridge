"""What a reading is, and which measurements the bridge is willing to store.

One rule keeps this small: a reading is a single number with a unit, a moment and a source. A
blood-pressure frame produces three readings that share a ``group_id``; a scale frame produces
one or two. Everything downstream — deduplication, freshness, export — works on readings, so
adding a device never means touching the store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

SYSTOLIC = "systolic"
DIASTOLIC = "diastolic"
MEAN_ARTERIAL = "mean_arterial"
PULSE = "pulse"
WEIGHT = "weight"
BODY_FAT = "body_fat"
GLUCOSE = "glucose"

MMHG = "mmHg"
BPM = "bpm"
KG = "kg"
PERCENT = "%"
MGDL = "mg/dL"

METRICS = {
    SYSTOLIC: MMHG,
    DIASTOLIC: MMHG,
    MEAN_ARTERIAL: MMHG,
    PULSE: BPM,
    WEIGHT: KG,
    BODY_FAT: PERCENT,
    GLUCOSE: MGDL,
}
KG_PER_POUND = 0.45359237


def now_iso() -> str:
    """Local time without a zone, because the device clocks we trust also have none."""
    return datetime.now().replace(microsecond=0).isoformat()


def normalize_moment(value: str | None) -> str:
    """Accept what devices send: '2026-09-26T11:03', ISO with Z, or nothing at all."""
    if not value:
        return now_iso()
    text = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return now_iso()
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.replace(microsecond=0).isoformat()


@dataclass
class Reading:
    """One number, one moment, one source. ``group_id`` ties the parts of a single frame."""

    metric: str
    value: float
    taken_at: str | None
    source: str
    unit: str = ""
    device: str = ""
    group_id: str = ""
    raw: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.metric not in METRICS:
            raise ValueError(f"unknown metric: {self.metric}")
        self.unit = self.unit or METRICS[self.metric]
        self.taken_at = normalize_moment(self.taken_at)
        self.value = round(float(self.value), 3)

    @property
    def dedupe_key(self) -> str:
        """What makes two readings the same event: source, metric, moment, value."""
        return "|".join([self.source, self.metric, str(self.taken_at or ""), f"{self.value:g}"])

    def as_row(self) -> dict:
        return {
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "taken_at": self.taken_at,
            "source": self.source,
            "device": self.device,
            "group_id": self.group_id,
            "dedupe_key": self.dedupe_key,
            "raw": self.raw,
        }


def from_blood_pressure(frame: dict, source: str, device: str = "") -> list[Reading]:
    """A parsed frame from a BP monitor into readings, in the order a human reads them."""
    group = f"{source}:{normalize_moment(frame.get('timestamp'))}"
    out = []
    for metric, key in ((SYSTOLIC, "systolic"), (DIASTOLIC, "diastolic"), (MEAN_ARTERIAL, "map"), (PULSE, "pulse")):
        value = frame.get(key)
        if value:
            out.append(Reading(metric, value, frame.get("timestamp"), source, device=device, group_id=group, raw=frame))
    return out


def from_scale(frame: dict, source: str, device: str = "") -> list[Reading]:
    """Weight and, when the scale reports it, body fat. Imperial frames arrive already in kg."""
    group = f"{source}:{normalize_moment(frame.get('ts_device'))}"
    out = []
    if frame.get("weight"):
        out.append(
            Reading(WEIGHT, frame["weight"], frame.get("ts_device"), source, device=device, group_id=group, raw=frame)
        )
    for key, metric in (("body_fat", BODY_FAT), ("fat_percent", BODY_FAT)):
        if frame.get(key):
            out.append(
                Reading(metric, frame[key], frame.get("ts_device"), source, device=device, group_id=group, raw=frame)
            )
            break
    return out
