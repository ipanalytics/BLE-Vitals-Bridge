"""Watch the sources, not the person: each device is expected to write at its own pace.

A bridge breaks quietly. The cuff gets moved, the battery dies, the phone walks out of range —
and from the store's side nothing looks wrong, because nothing arrives and nothing complains.
So every source gets an expected cadence, and the watchdog turns silence into a line of text with
a number in it.

The cadences are per metric, not per device, so replacing a cuff with another cuff needs no code
change: the question is always "when did a systolic reading last arrive".
"""

from __future__ import annotations

from dataclasses import dataclass

from . import models

DEFAULT_RULES = (
    ("scale", models.WEIGHT, 14 * 24, "step on the scale at least every two weeks"),
    ("cuff", models.SYSTOLIC, 7 * 24, "a blood-pressure reading at least once a week"),
    ("cgm", models.GLUCOSE, 36, "a glucose reading at least every day and a half"),
    ("cgm", models.PULSE, 36, "a pulse reading from the sensor every day and a half"),
)


@dataclass
class Problem:
    source: str
    metric: str
    state: str  # "missing" | "stale" | "ok"
    detail: str
    age_hours: float | None = None

    @property
    def failed(self) -> bool:
        return self.state != "ok"


def check(store, rules=DEFAULT_RULES) -> list:
    """Match each expected metric against what the store has: missing, stale, or fine."""
    seen: dict = {}
    for row in store.sources():
        seen[(row["source"], row["metric"])] = row
    problems = []
    for source, metric, max_hours, why in rules:
        row = seen.get((source, metric))
        if row is None:
            age = None
            for (other_source, other_metric), candidate in seen.items():
                if other_metric == metric:
                    row, age = candidate, candidate["age_hours"]
                    source = other_source
                    break
        else:
            age = row["age_hours"]
        if row is None:
            problems.append(Problem(source, metric, "missing", f"nothing stored yet: expect {why}", None))
        elif age is None or age > max_hours:
            problems.append(
                Problem(
                    source, metric, "stale", f"last reading {age:.1f} h ago, limit {max_hours} h: expect {why}", age
                )
            )
        else:
            problems.append(Problem(source, metric, "ok", f"last reading {age:.1f} h ago", age))
    return problems


def lines(problems, *, only_failed: bool = True) -> list:
    out = []
    for problem in problems:
        if only_failed and not problem.failed:
            continue
        out.append(f"{problem.state}: {problem.source}/{problem.metric} — {problem.detail}")
    if not out:
        out.append("all sources are fresh")
    return out


def failed(problems) -> bool:
    return any(problem.failed for problem in problems)
