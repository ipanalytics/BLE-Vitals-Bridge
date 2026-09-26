"""``python -m ble_vitals_bridge`` — the same entry point as the ``bridge`` script."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
