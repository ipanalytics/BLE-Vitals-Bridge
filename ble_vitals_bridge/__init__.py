"""ble-vitals-bridge: cuff, scale and sensor into one local file, with a watchdog on top.

Three devices that each shipped their own app, their own cloud and their own idea of a
timestamp. This package keeps the parts that are actually hard:

* **parsing** — the Bluetooth SIG frames, including the two traps: ISO 11073 SFLOATs in the blood
  pressure frame, and the imperial bit in the weight frame (see :mod:`parsers`);
* **deduplication** — one primary key (``source|metric|moment|value``) so the same measurement
  never lands twice, whatever path it took;
* **silence detection** — every source has an expected cadence, and the watchdog turns "nothing
  arrived for nine days" into a line with a number in it (:mod:`watchdog`);
* **honest units** — readings are stored in the units the device meant, never silently converted.
"""

from .models import Reading, from_blood_pressure, from_scale, normalize_moment
from .parsers import parse_blood_pressure, parse_body_composition, parse_weight_measurement, sfloat
from .sources import import_jsonl, readings_from_record, watch_blood_pressure, watch_scale
from .store import Store
from .watchdog import Problem, check, lines

__version__ = "1.0.0"
__all__ = [
    "Problem",
    "Reading",
    "Store",
    "check",
    "from_blood_pressure",
    "from_scale",
    "import_jsonl",
    "lines",
    "normalize_moment",
    "parse_blood_pressure",
    "parse_body_composition",
    "parse_weight_measurement",
    "readings_from_record",
    "sfloat",
    "watch_blood_pressure",
    "watch_scale",
]
