"""Collect official Omura results without advancing past unpublished archives."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
import csv
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

RESULT_FIELDS = ["date", "race", "trifecta", "payout_yen"]
VOID_FIELDS = ["date", "race", "status", "source_url", "checked_at"]


def archive_url(day):
    return f"https://www1.mbrace.or.jp/od2/K/{day:%Y%m}/k{day:%y%m%d}.lzh"


def parse_results(text, day):
    """Require all 12 races, including explicitly void races, before saving."""
    headers = list(re.finditer(
        r"^.*\d{4}/\s*\d{1,2}/\s*\d{1,2}.*ボートレース.*$",
        text, re.MULTILINE))
    if not headers:
        raise ValueError("公式結果の会場見出しを解析できません")
    sections = []
    for i, match in enumerate(headers):
        header_day = re.search(r"(\d{4})/\s*(\d{1,2})/\s*(\d{1,2})", match.group())
        if tuple(map(int, header_day.groups())) != (day.year, day.month, day.day):
            raise ValueError("結果ファイルの日付が一致しません")
        if "ボートレース大村" in re.sub(r"\s", "", match.group()):
            section = text[match.start():headers[i + 1].start()
                           if i + 1 < len(headers) else len(text)]
            sections.append(section)
    if not sections:
        return [], []  # Valid nationwide archive without an Omura meeting.
    if len(sections) != 1:
        raise ValueError("大村の会場見出しが重複しています")
    section = sections[0]
    results = []
    for match in re.finditer(
            r"^\s*(\d{1,2})R\s+([1-6]-[1-6]-[1-6])\s+([\d,]+)(?=\s|$)",
            section, re.MULTILINE):
        race, combination, payout = match.groups()
        value = int(payout.replace(",", ""))
        if len(set(combination.split("-"))) != 3 or value <= 0:
            raise ValueError("着順または払戻が不正です")
        results.append({"date": day.isoformat(), "race": int(race),
                        "trifecta": combination, "payout_yen": value})
    voids = [{"date": day.isoformat(), "race": int(m.group(1)),
              "status": "cancelled" if m.group(2) == "中止" else "not_established"}
             for m in re.finditer(r"^\s*(\d{1,2})R\s+(不成立|中止)(?=\s|$)",
                                  section, re.MULTILINE)]
    settled, void = {r["race"] for r in results}, {r["race"] for r in voids}
    if len(settled) != len(results) or len(void) != len(voids):
        raise ValueError("レース番号が重複しています")
    if settled & void or settled | void != set(range(1, 13)):
        raise ValueError(f"12レースの結果・中止を確認できません: {sorted(settled | void)}")
    return results, voids


def read_saved(path, fields):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != fields:
            raise ValueError(f"{path.name}: CSVの列が異なります")
        rows = list(reader)
    result = {}
    for row in rows:
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"{path.name}: CSVの列数が一致しません")
        key = (row["date"], int(row["race"]))
        if key in result:
            raise ValueError(f"{path.name}: レースが重複しています")
        result[key] = row
    return result


def write_saved(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows))
    temporary.replace(path)


def collect_one(day, output_dir, all_results, all_voids):
    print(f"収集開始: {day}", flush=True)
    url = archive_url(day)
    with tempfile.TemporaryDirectory(prefix="omura-results-") as directory:
        archive = Path(directory) / f"k{day:%y%m%d}.lzh"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                archive.write_bytes(response.read())
        except HTTPError as error:
            if error.code in (404, 410):
                raise RuntimeError(f"{day}: 結果ファイル未公開。収集位置を進めず再試行します") from error
            raise
        subprocess.run(["bsdtar", "-xf", str(archive), "-C", directory], check=True)
        text = (Path(directory) / f"K{day:%y%m%d}.TXT").read_bytes().decode("cp932")
    results, voids = parse_results(text, day)
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_results = dict(all_results)
    new_voids = dict(all_voids)
    for row in results:
        key = (row["date"], int(row["race"]))
        new_results[key] = row
        new_voids.pop(key, None)
    for row in voids:
        key = (row["date"], int(row["race"]))
        if key in new_results:
            raise ValueError(f"{day} {key[1]}R: 既存結果と公式の中止記載が矛盾しています")
        row.update(source_url=url, checked_at=checked_at)
        old = new_voids.get(key)
        if old and all(str(old[k]) == str(row[k]) for k in VOID_FIELDS if k != "checked_at"):
            row["checked_at"] = old["checked_at"]
        new_voids[key] = row
    # Preserve each verified day if a later download fails. Cursor advancement
    # still requires the entire requested batch to succeed.
    write_saved(output_dir / "omura_results.csv", new_results, RESULT_FIELDS)
    if new_voids or (output_dir / "omura_void_races.csv").exists():
        write_saved(output_dir / "omura_void_races.csv", new_voids, VOID_FIELDS)
    all_results.clear()
    all_results.update(new_results)
    all_voids.clear()
    all_voids.update(new_voids)
    print(f"{day}: 結果{len(results)}R / 公式の中止・不成立{len(voids)}R" if results or voids
          else f"{day}: 全国結果ファイルに大村の開催なし", flush=True)
    return len(results)


def main():
    start = datetime.strptime(os.getenv("RACE_DATE", "2026-09-01"), "%Y-%m-%d").date()
    days = int(os.getenv("COLLECT_DAYS", "1"))
    if not 1 <= days <= 30:
        raise ValueError("COLLECT_DAYSは1〜30にしてください")
    if not shutil.which("bsdtar"):
        raise RuntimeError("bsdtarが見つかりません")
    output_dir = Path("data")
    all_results = read_saved(output_dir / "omura_results.csv", RESULT_FIELDS)
    all_voids = read_saved(output_dir / "omura_void_races.csv", VOID_FIELDS)
    total = 0
    for offset in range(days):
        total += collect_one(start + timedelta(days=offset), output_dir, all_results, all_voids)
        if offset < days - 1:
            time.sleep(3)
    print(f"収集完了: {days}日 / 今回{total}R / CSV合計{len(all_results)}R", flush=True)


if __name__ == "__main__":
    main()
