"""Build reproducible, retrospective benchmarks from the saved Omura CSVs.

No model is fitted here. The two rules are fixed in advance, use no race
results as inputs, and stake 100 yen on one trifecta per eligible race.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math
import re

from result_coverage import classify, load_context, COVERAGE_FIELDS

ENTRY_FIELDS = {"date", "venue", "race_no", "boat_no", "racer_id",
                "racer_name", "national_win_rate", "collected_at"}
RESULT_FIELDS = {"date", "race", "trifecta", "payout_yen"}
BEFORE_FIELDS = {"date", "venue", "race_no", "boat_no", "racer_name",
                 "exhibition_status", "exhibition_time", "deadline_at",
                 "collected_at", "captured_before_deadline"}
RULES = [
    ("lane_order", "艇番順 1-2-3"),
    ("national_win_rate", "全国勝率の高い順（同率は艇番順）"),
]
JST = timezone(timedelta(hours=9))


def read_rows(path, required, optional=False):
    if optional and not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"{path.name}: 必要なCSV列がありません")
        rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError(f"{path.name}: CSVの列数が一致しません")
    return rows


def race_key(row, race_field="race_no"):
    day = row["date"]
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("日付形式が異なります")
    number = int(row[race_field])
    if not 1 <= number <= 12:
        raise ValueError("レース番号が範囲外です")
    return day, number


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("取得時刻にタイムゾーンがありません")
    return parsed


def finite_rate(value):
    rate = float(value)
    if not math.isfinite(rate) or not 0 <= rate <= 10:
        raise ValueError("勝率が範囲外です")
    return rate


def benchmark(races, rule):
    count = len(races)
    hits = sum(r[rule] == r["trifecta"] for r in races)
    payout = sum(r["payout_yen"] for r in races if r[rule] == r["trifecta"])
    stake = count * 100
    return {"races": count, "hits": hits, "stake_yen": stake,
            "payout_yen": payout, "net_yen": payout - stake,
            "roi_pct": round(payout / stake * 100, 2) if stake else None,
            "hit_pct": round(hits / count * 100, 2) if count else None}


def build(data_dir, *, as_of=None):
    issues = Counter()
    paths = [data_dir / "omura_entries.csv", data_dir / "omura_results.csv"]
    entries = read_rows(paths[0], ENTRY_FIELDS)
    results = read_rows(paths[1], RESULT_FIELDS)
    groups = defaultdict(list)
    invalid_entry_keys = set()
    for row in entries:
        try:
            key = race_key(row)
            if row["venue"] != "24":
                raise ValueError("会場が異なります")
            if not 1 <= int(row["boat_no"]) <= 6:
                raise ValueError("艇番が範囲外です")
            groups[key].append(row)
        except (KeyError, ValueError, TypeError):
            issues["invalid_entry_rows"] += 1
            try:
                invalid_entry_keys.add(race_key(row))
            except (KeyError, ValueError, TypeError):
                pass

    complete = {}
    for key, rows in groups.items():
        if (key not in invalid_entry_keys and len(rows) == 6
                and {int(r["boat_no"]) for r in rows} == set(range(1, 7))
                and len({r["racer_id"] for r in rows}) == 6
                and all(re.fullmatch(r"\d{4}", r["racer_id"]) for r in rows)):
            complete[key] = rows
        else:
            issues["incomplete_or_duplicate_entry_races"] += 1

    # Duplicate result keys are excluded entirely, even when their values match.
    result_groups = defaultdict(list)
    invalid_result_keys = set()
    for row in results:
        try:
            key = race_key(row, "race")
        except (KeyError, ValueError, TypeError):
            issues["invalid_result_rows"] += 1
            continue
        try:
            boats = row["trifecta"].split("-")
            if (len(boats) != 3 or len(set(boats)) != 3
                    or not all(re.fullmatch(r"[1-6]", n) for n in boats)
                    or not re.fullmatch(r"[1-9]\d*", row["payout_yen"])):
                raise ValueError("着順または払戻が不正です")
            result_groups[key].append(row)
        except (KeyError, ValueError, TypeError):
            issues["invalid_result_rows"] += 1
            invalid_result_keys.add(key)
    valid_results = {}
    for key, rows in result_groups.items():
        if len(rows) != 1 or key in invalid_result_keys:
            issues["duplicate_or_invalid_result_races"] += 1
        else:
            valid_results[key] = rows[0]

    # Inspect archived snapshots, not only the final (often post-race) snapshot.
    before_paths = sorted((data_dir / "beforeinfo").glob("*.csv"))
    current = data_dir / "omura_beforeinfo.csv"
    if current.exists():
        before_paths.append(current)
    paths.extend(before_paths)
    saved_before_keys = set()
    snapshots = defaultdict(dict)
    for path in before_paths:
        for row in read_rows(path, BEFORE_FIELDS):
            try:
                if row["venue"] != "24":
                    raise ValueError("会場が異なります")
                key = race_key(row)
                boat = int(row["boat_no"])
                if not 1 <= boat <= 6:
                    raise ValueError("艇番が範囲外です")
                saved_before_keys.add(key)
                if (row["exhibition_status"] != "published"
                        or row["captured_before_deadline"] != "true"):
                    continue
                captured = timestamp(row["collected_at"])
                deadline = timestamp(row["deadline_at"])
                if (captured >= deadline or deadline.date().isoformat() != key[0]
                        or captured.astimezone(deadline.tzinfo).date() != deadline.date()
                        or not math.isfinite(float(row["exhibition_time"]))
                        or not 5 <= float(row["exhibition_time"]) <= 10):
                    raise ValueError("締切前の展示として使えません")
                # All boats must share a deadline. A changed deadline creates
                # a separate group rather than mixing incompatible snapshots.
                snapshot_key = (*key, deadline.isoformat())
                old = snapshots[snapshot_key].get(boat)
                if old is None or captured > timestamp(old["collected_at"]):
                    snapshots[snapshot_key][boat] = row
            except (KeyError, ValueError, TypeError):
                issues["invalid_beforeinfo_rows"] += 1

    before_ready = set()
    for snapshot_key, boats in snapshots.items():
        key = snapshot_key[:2]
        if set(boats) != set(range(1, 7)) or key not in complete:
            continue
        names = {int(r["boat_no"]): r["racer_name"] for r in complete[key]}
        if all(names[n] == r["racer_name"] for n, r in boats.items()):
            before_ready.add(key)
        else:
            issues["beforeinfo_identity_mismatch_races"] += 1

    cursor, voids = load_context(data_dir)
    coverage = classify(complete, valid_results, set(result_groups) | invalid_result_keys,
                        voids, as_of or datetime.now(JST).date(), cursor)
    for optional in ("history_cursor.txt", "omura_void_races.csv"):
        if (data_dir / optional).exists():
            paths.append(data_dir / optional)

    joined = []
    missing_entries = 0
    missing_rates = 0
    for key, result in sorted(valid_results.items()):
        rows = complete.get(key)
        if rows is None:
            missing_entries += 1
            continue
        try:
            ranked = sorted(rows, key=lambda r: (-finite_rate(r["national_win_rate"]),
                                                 int(r["boat_no"])))
        except (ValueError, TypeError):
            missing_rates += 1
            continue
        after = False
        unknown_time = False
        for row in rows:
            try:
                fetched = timestamp(row["collected_at"])
                # This proves retrieval happened after the race day. Same-day
                # retrieval alone does not prove it happened before the race.
                after |= fetched.astimezone(JST).date().isoformat() > key[0]
            except (ValueError, TypeError):
                unknown_time = True
        joined.append({"date": key[0], "race": key[1],
                       "trifecta": result["trifecta"],
                       "payout_yen": int(result["payout_yen"]),
                       "lane_order": "1-2-3",
                       "national_win_rate": "-".join(str(int(r["boat_no"])) for r in ranked[:3]),
                       "predeadline_exhibition": key in before_ready,
                       "entries_retrieved_after_race_day": after,
                       "entry_timestamp_unknown": unknown_time})

    days = sorted({r["date"] for r in joined})
    holdout_days = max(1, math.ceil(len(days) * .2)) if days else 0
    holdout_start = days[-holdout_days] if days else None
    recent = [r for r in joined if r["date"] >= holdout_start] if days else []
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": {"kind": "retrospective_fixed_rules", "stake_per_race_yen": 100,
                   "bet_type": "3連単", "uses_exhibition": False,
                   "refunds": "unavailable_assumed_zero",
                   "holdout_fraction_of_race_days": .2},
        "sources": [{"file": str(p.relative_to(data_dir)),
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                    for p in paths],
        "data": {"entry_rows": len(entries), "entry_races": len(groups),
                 "complete_entry_races": len(complete), "result_rows": len(results),
                 "valid_result_races": len(valid_results), "eligible_races": len(joined),
                 "result_races_without_complete_entries": missing_entries,
                 "joined_races_without_valid_rates": missing_rates,
                 "entry_races_without_results": len(set(complete) - set(valid_results)),
                 "beforeinfo_races": len(saved_before_keys),
                 "predeadline_exhibition_races": len(before_ready),
                 "predeadline_exhibition_with_result": len(before_ready & valid_results.keys()),
                 "retrospective_entry_races": sum(r["entries_retrieved_after_race_day"] for r in joined),
                 "entry_timestamp_unknown_races": sum(r["entry_timestamp_unknown"] for r in joined),
                 "race_days": len(days), "first_date": days[0] if days else None,
                 "last_date": days[-1] if days else None,
                 "recent_start": holdout_start, "recent_days": holdout_days},
        "result_coverage": coverage,
        "issues": dict(sorted(issues.items())),
        "benchmarks": [{"id": rule, "label": label,
                        "all": benchmark(joined, rule),
                        "recent": benchmark(recent, rule)} for rule, label in RULES],
    }
    return summary, joined


def write_outputs(data_dir, summary, joined):
    output = data_dir / "validation_summary.json"
    document = {**summary, "result_coverage": {k: v for k, v in summary["result_coverage"].items()
                                              if k != "races"}}
    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            old_time = previous.pop("generated_at", None)
            current = {k: v for k, v in document.items() if k != "generated_at"}
            if old_time and previous == current:
                summary["generated_at"] = old_time
                document["generated_at"] = old_time
        except (ValueError, TypeError, AttributeError):
            pass
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(output)
    output = data_dir / "validation_races.csv"
    temporary = output.with_suffix(".tmp")
    fields = ["date", "race", "trifecta", "payout_yen", "lane_order",
              "national_win_rate", "predeadline_exhibition",
              "entries_retrieved_after_race_day", "entry_timestamp_unknown"]
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(joined)
    temporary.replace(output)
    output = data_dir / "result_coverage.csv"
    temporary = output.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COVERAGE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary["result_coverage"]["races"])
    temporary.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    summary, joined = build(args.data_dir)
    write_outputs(args.data_dir, summary, joined)
    print(json.dumps(summary["data"], ensure_ascii=False, indent=2))
    print("検証上の問題:", summary["issues"] or "なし")


if __name__ == "__main__":
    main()
