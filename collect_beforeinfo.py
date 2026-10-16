from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen
from collect_entries import EntryParser
import csv
import os
import re
import time
import unicodedata

JST = timezone(timedelta(hours=9))
OUTPUT = Path("data/omura_beforeinfo.csv")
HISTORY = Path("data/beforeinfo")

FIELDS = [
    "date", "venue", "race_no", "boat_no", "racer_name",
    "weight_kg", "exhibition_time", "tilt", "propeller", "parts",
    "exhibition_course", "exhibition_st", "exhibition_status",
    "weather", "air_temperature", "water_temperature",
    "wind_speed", "wind_direction_code", "wave_height", "weather_as_of",
    "deadline_at", "collected_at", "captured_before_deadline",
]


def plain(value):
    value = unescape(re.sub(r"<[^>]+>", " ", value))
    return " ".join(
        unicodedata.normalize("NFKC", value).split()
    )


def number(value):
    match = re.fullmatch(
        r"(-?\d+(?:\.\d+)?)(?:kg)?",
        value.strip()
    )
    if match:
        return match.group(1)
    if value.strip() in ("", "-", "欠場", "欠", "取消"):
        return ""
    raise ValueError(f"数値欄の形式が変わっています: {value}")


def parse_page(html, day, race_no, captured_at=None):
    parser = EntryParser()
    parser.feed(html)

    if not parser.rows:
        if "データがありません。" in html:
            return []
        raise ValueError("直前情報を解析できませんでした")

    now = captured_at or datetime.now(JST)

    # レースごとの締切予定時刻
    cutoff = re.search(
        r"締切予定時刻</td>(.*?)</tr>",
        html,
        re.S
    )
    times = (
        re.findall(
            r"\b\d{1,2}:\d{2}\b",
            plain(cutoff.group(1))
        )
        if cutoff else []
    )

    deadline = None
    if len(times) == 12:
        deadline = datetime.fromisoformat(
            f"{day.isoformat()}T{times[race_no - 1]}:00+09:00"
        )

    # 水面気象情報
    start = html.find('<div class="weather1">')
    weather_html = html[start:] if start >= 0 else ""
    weather_text = plain(
        weather_html.split('class="weather1_stand"')[0]
    )

    weather = {}
    for field, label, unit in [
        ("air_temperature", "気温", "℃"),
        ("water_temperature", "水温", "℃"),
        ("wind_speed", "風速", "m"),
        ("wave_height", "波高", "cm"),
    ]:
        unit = re.escape(
            unicodedata.normalize("NFKC", unit)
        )
        match = re.search(
            label + r"\s*(-?\d+(?:\.\d+)?)\s*" + unit,
            weather_text
        )
        weather[field] = match.group(1) if match else ""

    match = re.search(
        r'weather1_title[^>]*>(.*?)</p>',
        weather_html,
        re.S
    )
    weather["weather_as_of"] = (
        plain(match.group(1))
        .replace("水面気象情報", "")
        .strip()
        if match else ""
    )

    match = re.search(
        r'\bis-wind(\d+)\b',
        weather_html
    )
    weather["wind_direction_code"] = (
        match.group(1) if match else ""
    )

    match = re.search(
        r'weather1_bodyUnit is-weather"[^>]*>(.*?)</div>',
        weather_html,
        re.S
    )
    weather["weather"] = (
        plain(match.group(1)) if match else ""
    )

    # スタート展示。Fなどの表記はそのまま保存
    starts = {}
    blocks = re.findall(
        r'<div class="table1_boatImage1">(.*?)</div>',
        html,
        re.S
    )

    for course, block in enumerate(blocks, 1):
        boat = re.search(
            r'table1_boatImage1Number is-type([1-6])',
            block
        )
        st = re.search(
            r'table1_boatImage1Time[^>]*>(.*?)</span>',
            block,
            re.S
        )
        if boat and st:
            starts[int(boat.group(1))] = (
                course,
                plain(st.group(1))
            )

    result = []

    for cells in parser.rows:
        boat_no = int(cells[0])
        course, st = starts.get(boat_no, ("", ""))
        exhibition = number(cells[4])

        row = dict.fromkeys(FIELDS, "")
        row.update(weather)
        row.update({
            "date": day.isoformat(),
            "venue": "24",
            "race_no": race_no,
            "boat_no": boat_no,
            "racer_name": cells[2].replace(" ", ""),
            "weight_kg": number(cells[3]),
            "exhibition_time": exhibition,
            "tilt": number(cells[5]),
            "propeller": cells[6],
            "parts": cells[7],
            "exhibition_course": course,
            "exhibition_st": st,
            "exhibition_status": (
                "published" if exhibition else "pending"
            ),
            "deadline_at": (
                deadline.isoformat() if deadline else ""
            ),
            "collected_at": now.isoformat(timespec="seconds"),
            "captured_before_deadline": (
                str(now < deadline).lower()
                if deadline else "unknown"
            ),
        })
        result.append(row)

    lanes = [row["boat_no"] for row in result]
    if (
        len(lanes) != len(set(lanes))
        or not all(1 <= n <= 6 for n in lanes)
    ):
        raise ValueError("艇番の重複または範囲異常があります")

    return result


def fetch(day, race_no):
    url = (
        "https://www.boatrace.jp/owpc/pc/race/beforeinfo"
        f"?rno={race_no}&jcd=24&hd={day:%Y%m%d}"
    )

    for attempt in range(3):
        try:
            request = Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urlopen(request, timeout=30) as response:
                html = response.read().decode("utf-8")
            return parse_page(html, day, race_no)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def read_csv(path):
    if not path.exists():
        return []

    with path.open(
        encoding="utf-8-sig",
        newline=""
    ) as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"CSVの列が異なります: {path}")
        return list(reader)


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")

    with temporary.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS
        )
        writer.writeheader()
        writer.writerows(rows)

    temporary.replace(path)


def key(row):
    return (
        row["date"],
        row["venue"],
        int(row["race_no"]),
        int(row["boat_no"]),
    )


def save(rows, day):
    if not rows:
        return

    merged = {
        key(row): row
        for row in read_csv(OUTPUT)
    }
    merged.update({
        key(row): row
        for row in rows
    })

    # 変更された情報を日付別の履歴にも残す
    archive = HISTORY / f"{day.isoformat()}.csv"
    history = read_csv(archive)
    previous = {
        key(row): row
        for row in history
    }

    for row in rows:
        old = previous.get(key(row))
        if old is None or any(
            str(row[field]) != str(old[field])
            for field in FIELDS
            if field != "collected_at"
        ):
            history.append(row)
            previous[key(row)] = row

    write_csv(archive, history)
    write_csv(
        OUTPUT,
        [merged[k] for k in sorted(merged)]
    )


def main():
    date_text = os.getenv("RACE_DATE", "").strip()
    day = (
        datetime.strptime(date_text, "%Y-%m-%d").date()
        if date_text else datetime.now(JST).date()
    )

    failures = []
    count = 0

    for race_no in range(1, 13):
        try:
            rows = fetch(day, race_no)
            save(rows, day)

            ready = sum(
                row["exhibition_status"] == "published"
                for row in rows
            )
            count += len(rows)

            print(
                f"{day} 大村 {race_no}R: "
                f"{len(rows)}艇 / 展示公開 {ready}艇",
                flush=True
            )
        except Exception as error:
            failures.append(f"{race_no}R: {error}")
            print(
                f"取得失敗: {failures[-1]}",
                flush=True
            )

        time.sleep(1)

    print(
        f"完了: {count}艇 / 失敗: {len(failures)}件",
        flush=True
    )

    if failures:
        raise RuntimeError(
            "一部の取得に失敗しました。実行ログを確認してください"
        )


if __name__ == "__main__":
    main()
