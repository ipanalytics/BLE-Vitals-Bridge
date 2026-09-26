"""bridge — one command for a cuff, a scale and a sensor, and one file they all write into.

    bridge watch cuff          wait for one blood-pressure frame and store it
    bridge watch scale         wait for one weighing and store it
    bridge import FILE...      read old JSON-lines logs (idempotent, safe to repeat)
    bridge status              when each source last wrote, and what a watchdog would say
    bridge export --metric M   take the numbers out as CSV, for a chart or a doctor

Exit codes: 0 fine, 1 nothing arrived or a source is stale, 2 usage or configuration.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from . import models, sources, watchdog
from .store import Store

EXIT_OK, EXIT_PROBLEM, EXIT_USAGE = 0, 1, 2
DEFAULT_DB = "~/.local/share/ble-vitals-bridge/readings.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridge", description="One local store for a cuff, a scale and a CGM.")
    parser.add_argument("command", choices=["watch", "import", "status", "export", "metrics"])
    parser.add_argument("target", nargs="?", help="watch: cuff or scale; import: the log files")
    parser.add_argument("files", nargs="*", help="import: further log files")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite file (default: {DEFAULT_DB})")
    parser.add_argument("--address", help="watch: the Bluetooth address, when discovery cannot see it")
    parser.add_argument("--timeout", type=float, default=180.0, help="watch: seconds to wait for a reading")
    parser.add_argument("--source", help="import: name to store the readings under (default: the file name)")
    parser.add_argument("--metric", help="export: which metric")
    parser.add_argument("--days", type=int, default=30, help="export: how far back")
    parser.add_argument("--json", action="store_true", help="print the record instead of lines")
    parser.add_argument("--quiet", action="store_true", help="print nothing, only set the exit code")
    return parser


def run_watch(args, store: Store) -> int:
    if args.target not in ("cuff", "scale"):
        print("bridge: watch needs to be told what to watch: cuff or scale", file=sys.stderr)
        return EXIT_USAGE
    if args.target == "cuff":
        readings = sources.watch_blood_pressure(args.address, args.timeout)
    else:
        readings = sources.watch_scale(args.address, args.timeout)
    if not readings:
        if not args.quiet:
            print(f"bridge: nothing arrived within {args.timeout:.0f}s — device off, or out of range")
        return EXIT_PROBLEM
    added, known = store.add(readings)
    if not args.quiet:
        for reading in readings:
            print(f"{reading.taken_at}  {reading.metric} {reading.value:g} {reading.unit}  ({reading.source})")
        print(f"stored {added}, already known {known}")
    return EXIT_OK


def run_import(args, store: Store) -> int:
    names = [name for name in [args.target, *args.files] if name]
    if not names:
        print("bridge: import needs at least one file", file=sys.stderr)
        return EXIT_USAGE
    total = {"lines": 0, "inserted": 0, "known": 0, "skipped": 0}
    for name in names:
        result = sources.import_jsonl(name, store, source=args.source or "")
        for key in total:
            total[key] += result[key]
        if not args.quiet:
            print(
                f"{result['file']}: {result['lines']} lines, {result['inserted']} new, "
                f"{result['known']} already known, {result['skipped']} unreadable"
            )
    if not args.quiet:
        print(f"total: {total['inserted']} new readings, {total['known']} already known")
    return EXIT_OK


def run_status(args, store: Store) -> int:
    problems = watchdog.check(store)
    failed = watchdog.failed(problems)
    if args.quiet:
        return EXIT_PROBLEM if failed else EXIT_OK
    if args.json:
        payload = {
            "failed": failed,
            "sources": store.sources(),
            "checks": [problem.__dict__ | {"failed": problem.failed} for problem in problems],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for row in store.sources():
            print(
                f"{row['source']:9} {row['metric']:12} {row['readings']:5} readings, last {row['last']} ({row['age_hours']} h)"
            )
        print("")
        for line in watchdog.lines(problems):
            print(line)
    return EXIT_PROBLEM if failed else EXIT_OK


def run_export(args, store: Store) -> int:
    metrics = [args.metric] if args.metric else sorted(models.METRICS)
    writer = csv.writer(sys.stdout)
    writer.writerow(["metric", "taken_at", "value", "unit", "source", "group_id"])
    rows = 0
    for metric in metrics:
        if metric not in models.METRICS:
            print(f"bridge: unknown metric {metric}", file=sys.stderr)
            return EXIT_USAGE
        for row in store.series(metric, days=args.days):
            writer.writerow([metric, row["taken_at"], row["value"], row["unit"], row["source"], row["group_id"]])
            rows += 1
    if not args.quiet:
        print(f"# {rows} readings", file=sys.stderr)
    return EXIT_OK


def run_metrics(args, store: Store) -> int:
    for metric, unit in sorted(models.METRICS.items()):
        print(f"{metric:14} {unit:5} {store.count(metric)} readings")
    return EXIT_OK


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    with Store(args.db) as store:
        if args.command == "watch":
            return run_watch(args, store)
        if args.command == "import":
            return run_import(args, store)
        if args.command == "status":
            return run_status(args, store)
        if args.command == "export":
            return run_export(args, store)
        return run_metrics(args, store)


if __name__ == "__main__":
    raise SystemExit(main())
