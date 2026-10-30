"""Classify unmatched saved races without guessing cancellation or publication."""
from collections import Counter
from datetime import date, datetime
import csv

COVERAGE_FIELDS = ["date", "race", "status", "source_url"]
LABELS = {
    "invalid_result": "結果の重複・形式不正",
    "official_void": "公式確認済みの中止・不成立",
    "current_or_future": "当日・未来（結果待ちを含む）",
    "history_pending": "過去収集の進行待ち",
    "past_unresolved": "過去分の未照合・要確認",
}


def classify(complete_keys, valid_result_keys, raw_result_keys, void_rows,
             today, history_cursor=None):
    voids = {}
    for row in void_rows:
        try:
            day = date.fromisoformat(row["date"])
            race = int(row["race"])
            expected = f"https://www1.mbrace.or.jp/od2/K/{day:%Y%m}/k{day:%y%m%d}.lzh"
            if (day.isoformat() != row["date"] or not 1 <= race <= 12
                    or row["status"] not in ("cancelled", "not_established")
                    or row["source_url"] != expected):
                raise ValueError("中止の出典・形式が不正です")
            checked = datetime.fromisoformat(row["checked_at"])
            if checked.utcoffset() is None:
                raise ValueError("確認時刻のタイムゾーンがありません")
            key = (row["date"], race)
            if key in valid_result_keys:
                raise ValueError("有効な結果と中止情報が矛盾しています")
            if key in voids:
                raise ValueError("中止情報が重複しています")
            voids[key] = expected
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError("公式の中止・不成立CSVを確認してください") from error
    details = []
    for key in sorted(set(complete_keys) - set(valid_result_keys)):
        day, race = key
        if key in raw_result_keys:
            status = "invalid_result"
        elif key in voids:
            status = "official_void"
        elif day >= today.isoformat():
            status = "current_or_future"
        elif history_cursor is not None and day >= history_cursor.isoformat():
            status = "history_pending"
        else:
            status = "past_unresolved"
        details.append({"date": day, "race": race, "status": status,
                        "source_url": voids.get(key, "")})
    counts = Counter(row["status"] for row in details)
    return {
        "as_of_date": today.isoformat(),
        "history_cursor": history_cursor.isoformat() if history_cursor else None,
        "total_unmatched": len(details),
        "categories": [{"status": status, "label": label, "races": counts[status]}
                       for status, label in LABELS.items()],
        "days": [{"date": day, "races": sum(row["date"] == day for row in details)}
                 for day in sorted({row["date"] for row in details})],
        "races": details,
    }


def load_context(data_dir):
    """Optional metadata keeps old repositories readable; malformed files fail."""
    path = data_dir / "history_cursor.txt"
    cursor = None
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        cursor = date.fromisoformat(raw)
        if cursor.isoformat() != raw:
            raise ValueError("結果収集の進行日付が不正です")
    path = data_dir / "omura_void_races.csv"
    voids = []
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if set(reader.fieldnames or []) != {"date", "race", "status", "source_url", "checked_at"}:
                raise ValueError("中止・不成立CSVの列が異なります")
            voids = list(reader)
    return cursor, voids
