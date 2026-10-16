from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
import csv
import os
import re
import time
import unicodedata

JST = timezone(timedelta(hours=9))
OUTPUT = Path("data/omura_entries.csv")
FIELDS = [
    "date", "venue", "race_no", "boat_no", "racer_id", "racer_name",
    "racer_class", "f_count", "l_count", "average_st",
    "national_win_rate", "national_2rate", "national_3rate",
    "local_win_rate", "local_2rate", "local_3rate",
    "motor_no", "motor_2rate", "motor_3rate",
    "boat_id", "boat_2rate", "boat_3rate", "collected_at",
]


class EntryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = []
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        elif tag == "td":
            self.cell = [dict(attrs), []]

    def handle_data(self, data):
        if self.cell is not None:
            self.cell[1].append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            attrs, parts = self.cell
            value = unicodedata.normalize("NFKC", " ".join(parts))
            self.cells.append((attrs, " ".join(value.split())))
            self.cell = None
        elif tag == "tr" and len(self.cells) >= 8:
            attrs = self.cells[0][0]
            if (attrs.get("rowspan") == "4"
                    and re.search(r"\bis-boatColor[1-6]\b", attrs.get("class", ""))):
                self.rows.append([value for _, value in self.cells])


def triple(value):
    parts = value.split()
    if len(parts) != 3:
        raise ValueError(f"数値欄の形式が変わっています: {value}")
    for part in parts:
        if part != "-":
            float(part)
    return ["" if part == "-" else part for part in parts]


def parse_entries(html, day, race_no):
    parser = EntryParser()
    parser.feed(html)
    if not parser.rows:
        if "データがありません。" in html:
            return []
        raise ValueError("出走表を解析できませんでした")

    result = []
    for cells in parser.rows:
        identity = re.fullmatch(
            r"(\d{4})\s*/\s*(A1|A2|B1|B2)\s+(.+?)\s+"
            r"\S+/\S+\s+\d+歳/[\d.]+kg", cells[2]
        )
        if not identity:
            raise ValueError(f"選手欄の形式が変わっています: {cells[2]}")
        racer_id, grade, name = identity.groups()

        starts = re.fullmatch(r"F(\d+)\s+L(\d+)\s+(-|[\d.]+)", cells[3])
        if not starts:
            raise ValueError(f"ST欄の形式が変わっています: {cells[3]}")
        f_count, l_count, average_st = starts.groups()

        values = [
            day.isoformat(), "24", race_no, int(cells[0]),
            racer_id, name.replace(" ", ""), grade, f_count, l_count,
            "" if average_st == "-" else average_st,
            *triple(cells[4]), *triple(cells[5]),
            *triple(cells[6]), *triple(cells[7]),
            datetime.now(JST).isoformat(timespec="seconds"),
        ]
        result.append(dict(zip(FIELDS, values)))

    lanes = [row["boat_no"] for row in result]
    if len(lanes) != len(set(lanes)) or not all(1 <= n <= 6 for n in lanes):
        raise ValueError("艇番の重複または範囲異常があります")
    return result


def fetch(day, race_no):
    url = ("https://www.boatrace.jp/owpc/pc/race/racelist"
           f"?rno={race_no}&jcd=24&hd={day:%Y%m%d}")
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=30) as response:
                html = response.read().decode("utf-8")
            return parse_entries(html, day, race_no)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def save(rows):
    if not rows:
        return

    existing = []
    if OUTPUT.exists():
        with OUTPUT.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != FIELDS:
                raise ValueError("既存CSVの列が異なります。上書きを停止しました")
            existing = list(reader)

    def key(row):
        return (
            row["date"], row["venue"],
            int(row["race_no"]), int(row["boat_no"]),
        )

    merged = {key(row): row for row in existing + rows}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(merged[k] for k in sorted(merged))
    temporary.replace(OUTPUT)


def main():
    date_text = os.getenv("RACE_DATE", "").strip()
    start = (datetime.strptime(date_text, "%Y-%m-%d").date()
             if date_text else datetime.now(JST).date())
    days = int(os.getenv("COLLECT_DAYS", "1"))
    if not 1 <= days <= 7:
        raise ValueError("COLLECT_DAYSは1〜7にしてください")

    failures = []
    count = 0
    for offset in range(days):
        day = start + timedelta(days=offset)
        for race_no in range(1, 13):
            try:
                rows = fetch(day, race_no)
                save(rows)
                count += len(rows)
                print(f"{day} 大村 {race_no}R: {len(rows)}艇", flush=True)
            except Exception as error:
                failures.append(f"{day} {race_no}R: {error}")
                print(f"取得失敗: {failures[-1]}", flush=True)
            time.sleep(1)

    print(f"完了: {count}艇 / 失敗: {len(failures)}件", flush=True)
    if failures:
        raise RuntimeError("一部の取得に失敗しました。実行ログを確認してください")


if __name__ == "__main__":
    main()
