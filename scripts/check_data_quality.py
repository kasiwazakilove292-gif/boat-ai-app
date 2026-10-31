#!/usr/bin/env python3
"""Read-only integrity checks for BOAT AI LAB historical CSVs.

Run: python scripts/check_data_quality.py
No network access, third-party dependencies, or file writes.
"""
import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/omura_results.csv"
MOTORS = ROOT / "data/omura_motor_history.csv"


def read_rows(path, required):
    errors = []
    if not path.is_file():
        return [], [f"{path.name}: file missing"]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = set(required) - fields
        if missing:
            return [], [f"{path.name}: missing columns {sorted(missing)}"]
        return list(reader), errors


def check_results():
    rows, errors = read_rows(RESULTS, ("date", "race", "trifecta", "payout_yen"))
    seen = set()
    for line, row in enumerate(rows, 2):
        try:
            day = date.fromisoformat(row["date"])
            race = int(row["race"])
            payout = int(row["payout_yen"])
            order = [int(x) for x in row["trifecta"].split("-")]
            if not 1 <= race <= 12 or payout < 0 or len(order) != 3 or len(set(order)) != 3 or any(not 1 <= x <= 6 for x in order):
                raise ValueError("invalid race, payout, or trifecta")
            key = (day, race)
            if key in seen:
                raise ValueError("duplicate date/race")
            seen.add(key)
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(f"{RESULTS.name}:{line}: {exc}")
    return len(rows), errors


def check_motors():
    rows, errors = read_rows(MOTORS, ("as_of_date", "motor_no", "period_start", "period_end", "win_rate", "second_rate", "starts"))
    seen = set()
    for line, row in enumerate(rows, 2):
        try:
            as_of = date.fromisoformat(row["as_of_date"])
            start = date.fromisoformat(row["period_start"])
            end = date.fromisoformat(row["period_end"])
            motor = int(row["motor_no"])
            win = float(row["win_rate"])
            second = float(row["second_rate"])
            starts = int(row["starts"])
            if not start <= end <= as_of or motor <= 0 or starts < 0 or not 0 <= second <= 100 or not 0 <= win <= 10:
                raise ValueError("invalid motor statistics or period")
            key = (row.get("collected_at"), as_of, motor, start, end)
            if key in seen:
                raise ValueError("duplicate motor snapshot")
            seen.add(key)
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(f"{MOTORS.name}:{line}: {exc}")
    return len(rows), errors


def main():
    total_errors = []
    for name, check in (("results", check_results), ("motors", check_motors)):
        count, errors = check()
        print(f"{name}: {count} rows, {len(errors)} errors")
        total_errors.extend(errors)
    for message in total_errors[:30]:
        print("ERROR:", message, file=sys.stderr)
    if len(total_errors) > 30:
        print(f"... and {len(total_errors) - 30} more errors", file=sys.stderr)
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
