# BLE-Vitals-Bridge

_Русская версия: [README.ru.md](README.ru.md)_

**Three home devices, one local file — and a watchdog that notices when one of them goes quiet.**

A blood-pressure cuff, a scale and a glucose sensor all do the same thing: send one measurement
over Bluetooth and file it into their own app. Three apps, three clouds, three different ideas
about what "the time" means — and not one of them will tell you that the device has not been in
touch for nine days. This package keeps the parts that are actually hard.

## What it does

- **Reads the cuff** over the standard Blood Pressure Service (`0x1810`, measurement `0x2A35`) and
  parses the frame as ISO/IEEE 11073 instead of reading it as plain integers.
- **Reads the scale** over Weight Measurement (`0x2A9D`) and Body Composition (`0x2A9C`), including
  frames that arrive in pounds because of one flag bit.
- **Imports the logs you already have** — JSON lines written by earlier scripts — idempotently, so
  running it twice changes nothing.
- **Keeps one SQLite file** with a single primary key: `source|metric|moment|value`. A measurement
  cannot land twice, whatever path it took to get there.
- **Watches for silence**: every metric has an expected cadence, and `bridge status` turns "nothing
  arrived" into a line with a number in it.
- **Exports CSV** for a chart, a spreadsheet, or a doctor.

## Quick start

```sh
pip install "ble-vitals-bridge[ble]"    # [ble] pulls in bleak; importing logs works without it
bridge import ~/logs/scale.jsonl        # the files the old scripts wrote, safely repeatable
bridge watch cuff                       # wait for one frame, then store it
bridge status                           # what arrived, when, and what is missing
bridge status --quiet                   # cron: exit 1 when a source is silent, print nothing
bridge export --metric weight --days 90 > weight.csv
```

It runs on the machine with the radio. The store is a plain file, so any machine can read it.

## The four things that are actually hard

**1. The blood-pressure frame is not integers.** `0x2A35` carries 16-bit SFLOATs: a 12-bit
mantissa and a 4-bit signed exponent. Read them as `int` and a normal 128/84 measurement becomes
15616/10752 — which looks like a broken cuff rather than a parsing bug. The parser here handles
withdrawals from the mantissa and the negative exponents, and there is a test that pins both.

**2. One bit turns kilograms into pounds.** In `0x2A9D` the unit is 0.005 kg, unless bit 0 is set,
in which case the whole frame is 0.01 lb. A scale that reports 0.01 kg steps is a scale whose bit 0
was ignored. The stored value is always kilograms, and the frame keeps its `imperial` flag so the
choice is visible in the raw record.

**3. Re-readings and re-imports.** The same weighing reaches you more than once: the device
retries, the phone passes nearby twice, you import yesterday's log again. Each reading carries a
`dedupe_key` of `source|metric|moment|value`, which is the table's primary key, so a duplicate is
never stored. Importing the same file twice reports `0 new readings` and does not touch a row.

**4. Silence.** A bridge failure has no error message: readings simply stop, and everything looks
fine. `bridge status` compares each metric against its cadence

| Metric | Expected | Why |
|---|---|---|
| `weight` | every 14 days | a weighing at least twice a month |
| `systolic` | every 7 days | a pressure reading once a week |
| `glucose` | every 36 hours | the sensor is continuous, silence means a problem |
| `pulse` | every 36 hours | it arrives with the glucose frame |

Cadences live in `watchdog.DEFAULT_RULES` and are keyed by metric, not by device — replacing a cuff
with another cuff needs no code change.

## The store

One table, because the questions are simple (what is the latest, what is the trend, when did this
source last write):

| Column | Meaning |
|---|---|
| `dedupe_key` | primary key: `source\|metric\|moment\|value` |
| `metric`, `value`, `unit` | the number, in the unit the device meant |
| `taken_at` | the moment the device recorded, normalised to local time without a zone |
| `source`, `device` | which source wrote it and which device it came from |
| `group_id` | ties the parts of one frame together (systolic, diastolic, mean, pulse) |
| `raw` | the parsed frame as JSON, so a later question can be answered without re-reading the device |

## Tests

```sh
pip install -e ".[dev]"
pytest -q        # 25 tests, no Bluetooth hardware needed
ruff check .
```

The fixtures build frames in both directions — the tests pack an SFLOAT and then read it back —
so a parser that agrees with itself is not enough to pass. Everything else (deduplication,
freshness, import counting, the CSV export) runs against a temporary SQLite file.

## What it deliberately does not do

- **No cloud, no account, no vendor app.** If a device insists on a phone app, that is a reason to
  read the standard service, not a reason to sign in somewhere.
- **No key extraction.** Xiaomi scales that broadcast encrypted MiBeacon without the binding key
  cannot be read, and this package does not try to lift the key out of the vendor app.
- **No dashboard and no charts.** It exports CSV; the reading of the numbers belongs to a human,
  and medical judgement does not belong in a health-data bridge.
- **No silent unit conversion.** Degrees, stones and percentages are stored as the device sent
  them; the conversion to kilograms happens once, in the parser, and is visible in the frame.

## License

MIT — see [LICENSE](LICENSE).
