from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
import csv
import re

URL = "https://omurakyotei.jp/data/motor.php"
OUTPUT = Path("data/omura_motor_history.csv")

JST = timezone(timedelta(hours=9))


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
            self.depth = 1
        elif self.cell is not None:
            self.depth += 1

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            value = " ".join("".join(self.cell).split())
            self.row.append(value)
            self.cell = None
            self.depth = 0
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


def main():
    request = Request(
        URL,
        headers={"User-Agent": "OmuraMotorResearch/1.0"}
    )

    with urlopen(request, timeout=30) as response:
        raw = response.read()
        charset = response.headers.get_content_charset()

    html = raw.decode(charset or "utf-8", errors="replace")

    # 公式ページに記載された集計基準日
    match = re.search(
        r"集計期間\s*[:：]\s*(\d{4})年\s*"
        r"(\d{1,2})月\s*(\d{1,2})日以前",
        re.sub(r"<[^>]+>", "", html)
    )
    if not match:
        raise RuntimeError("集計基準日を確認できません")

    as_of = (
        f"{int(match.group(1)):04d}-"
        f"{int(match.group(2)):02d}-"
        f"{int(match.group(3)):02d}"
    )

    parser = TableParser()
    parser.feed(html)

    collected_at = datetime.now(JST).isoformat(timespec="seconds")

    fields = [
        "collected_at",
        "as_of_date",
        "motor_no",
        "period_start",
        "period_end",
        "win_rate",
        "second_rate",
        "starts"
    ]

    records = []

    for cells in parser.rows:
        # 公式表のデータ行を識別
        if len(cells) < 10:
            continue

        if not re.fullmatch(r"\d{1,2}", cells[0]):
            continue

        period = re.search(
            r"(\d{4})/(\d{1,2})/(\d{1,2})"
            r"\s*[〜～~-]\s*"
            r"(\d{4})/(\d{1,2})/(\d{1,2})",
            cells[1]
        )
        if not period:
            continue

        try:
            period_start = "-".join(
                f"{int(x):02d}" if i else f"{int(x):04d}"
                for i, x in enumerate(period.groups()[:3])
            )
            period_end = "-".join(
                f"{int(x):02d}" if i else f"{int(x):04d}"
                for i, x in enumerate(period.groups()[3:])
            )

            record = {
                "collected_at": collected_at,
                "as_of_date": as_of,
                "motor_no": int(cells[0]),
                "period_start": period_start,
                "period_end": period_end,
                "win_rate": float(cells[3]),
                "second_rate": float(cells[4]),
                "starts": int(cells[9])
            }
            records.append(record)
        except (ValueError, IndexError):
            continue

    # 表の構造が変わった場合は誤ったCSVを保存しない
    if len(records) < 30:
        raise RuntimeError(
            f"モーター情報の抽出が不十分です: {len(records)}件"
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    if OUTPUT.exists():
        with OUTPUT.open(
            "r", newline="", encoding="utf-8-sig"
        ) as f:
            existing = list(csv.DictReader(f))

    # 同じ集計基準日・モーター番号は重複保存しない
    saved = {
        (row["as_of_date"], str(row["motor_no"])): row
        for row in existing
    }

    for record in records:
        key = (
            record["as_of_date"],
            str(record["motor_no"])
        )
        saved[key] = record

    with OUTPUT.open(
        "w", newline="", encoding="utf-8-sig"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            sorted(
                saved.values(),
                key=lambda r: (
                    r["as_of_date"],
                    int(r["motor_no"])
                )
            )
        )

    print("モーター情報収集成功！")
    print("公式集計基準日:", as_of)
    print("今回取得:", len(records), "件")
    print("CSV合計:", len(saved), "件")
    print("保存先:", OUTPUT)


if __name__ == "__main__":
    main()
