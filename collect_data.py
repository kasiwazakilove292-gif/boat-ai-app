from pathlib import Path
from datetime import datetime, timedelta
from urllib.error import HTTPError
import csv
import os
import re
import shutil
import subprocess
import time
import urllib.request

# 取得開始日と日数
start_date = datetime.strptime(
    os.getenv("RACE_DATE", "2026-09-01"),
    "%Y-%m-%d"
)
days = int(os.getenv("COLLECT_DAYS", "1"))

# 最大30日分まで収集可能
if not 1 <= days <= 30:
    raise ValueError("COLLECT_DAYSは1〜30にしてください")

output_dir = Path("data")
output_dir.mkdir(exist_ok=True)
csv_file = output_dir / "omura_results.csv"

if not shutil.which("bsdtar"):
    raise RuntimeError("bsdtarが見つかりません")

# 既存CSVを読み込む
all_results = {}

if csv_file.exists():
    with csv_file.open(
        "r", newline="", encoding="utf-8-sig"
    ) as f:
        for row in csv.DictReader(f):
            key = (row["date"], int(row["race"]))
            all_results[key] = [
                row["date"],
                int(row["race"]),
                row["trifecta"],
                int(row["payout_yen"])
            ]


def collect_one(race_date):
    date_str = race_date.strftime("%Y-%m-%d")
    file_code = race_date.strftime("%y%m%d")
    archive = Path(f"k{file_code}.lzh")

    print(f"\n収集開始: {date_str}", flush=True)

    if not archive.exists():
        url = (
            f"https://www1.mbrace.or.jp/od2/K/"
            f"{race_date.strftime('%Y%m')}/"
            f"k{file_code}.lzh"
        )

        try:
            urllib.request.urlretrieve(url, archive)
            print("ダウンロード完了:", archive)
        except HTTPError as e:
            if e.code in (404, 410):
                print("結果ファイル未公開: スキップ")
                return 0
            raise

    subprocess.run(
        ["bsdtar", "-xf", str(archive), "-C", str(output_dir)],
        check=True
    )

    txt_file = output_dir / f"K{file_code}.TXT"
    text = txt_file.read_bytes().decode("cp932")

    # 会場ごとに分割
    headers = list(re.finditer(
        r"^.*\d{4}/\s*\d{1,2}/\s*\d{1,2}.*ボートレース.*$",
        text,
        re.MULTILINE
    ))

    omura = None

    for i, match in enumerate(headers):
        end = (
            headers[i + 1].start()
            if i + 1 < len(headers)
            else len(text)
        )
        section = text[match.start():end]
        header = match.group().replace("\u3000", "")

        if "ボートレース大村" in header:
            omura = section
            break

    if omura is None:
        print("大村の開催結果なし: スキップ")
        return 0

    results = []

    for line in omura.splitlines():
        match = re.match(
            r"^\s*(\d{1,2})R\s+([1-6]-[1-6]-[1-6])\s+([\d,]+)",
            line
        )
        if match:
            results.append([
                date_str,
                int(match.group(1)),
                match.group(2),
                int(match.group(3).replace(",", ""))
            ])

    if len(results) != 12:
        raise RuntimeError(
            f"{date_str}: 抽出件数が{len(results)}件です"
        )

    for row in results:
        all_results[(row[0], row[1])] = row

    print(f"抽出成功: {len(results)}レース")
    return len(results)


# 指定した日数を順番に収集
total_collected = 0

for i in range(days):
    race_date = start_date + timedelta(days=i)
    total_collected += collect_one(race_date)

    # 公式サイトへの連続アクセスを避ける
    if i < days - 1:
        time.sleep(3)

# すべて正常に処理できたらCSVを保存
with csv_file.open(
    "w", newline="", encoding="utf-8-sig"
) as f:
    writer = csv.writer(f)
    writer.writerow([
        "date", "race", "trifecta", "payout_yen"
    ])

    for key in sorted(all_results):
        writer.writerow(all_results[key])

print("\n収集処理完了！")
print("処理日数:", days)
print("今回抽出したレース数:", total_collected)
print("CSV合計レース数:", len(all_results))
print("CSV保存先:", csv_file)
