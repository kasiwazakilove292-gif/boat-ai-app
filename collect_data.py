from pathlib import Path
from datetime import datetime
import csv
import os
import re
import shutil
import subprocess
import urllib.request

# 取得する日付
date_str = os.getenv("RACE_DATE", "2026-09-01")
race_date = datetime.strptime(date_str, "%Y-%m-%d")
file_code = race_date.strftime("%y%m%d")

archive = Path(f"k{file_code}.lzh")
output_dir = Path("data")
output_dir.mkdir(exist_ok=True)

# LZHファイルを自動ダウンロード
if not archive.exists():
    url = (
        f"https://www1.mbrace.or.jp/od2/K/"
        f"{race_date.strftime('%Y%m')}/"
        f"k{file_code}.lzh"
    )

    print("ダウンロード開始:", url)
    urllib.request.urlretrieve(url, archive)
    print("ダウンロード完了:", archive)

# 解凍ツールを確認
if not shutil.which("bsdtar"):
    raise RuntimeError("bsdtarが見つかりません")

# LZHファイルを解凍
subprocess.run(
    ["bsdtar", "-xf", str(archive), "-C", str(output_dir)],
    check=True
)

txt_file = output_dir / f"K{file_code}.TXT"
text = txt_file.read_bytes().decode("cp932")

# 会場ごとのデータを分ける
# 以前成功したコードの正規表現を使用
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
    raise RuntimeError("大村のレースデータが見つかりません")

# 3連単の結果を抽出
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
        f"抽出件数が想定と違います: {len(results)}件"
    )

# 過去に保存したCSVを読み込む
csv_file = output_dir / "omura_results.csv"
all_results = {}

if csv_file.exists():
    with csv_file.open(
        "r", newline="", encoding="utf-8-sig"
    ) as f:
        reader = csv.DictReader(f)

        for row in reader:
            key = (row["date"], int(row["race"]))

            all_results[key] = [
                row["date"],
                int(row["race"]),
                row["trifecta"],
                int(row["payout_yen"])
            ]

# 同じ日付・レース番号は重複させない
for row in results:
    key = (row[0], row[1])
    all_results[key] = row

# 日付順にCSV保存
with csv_file.open(
    "w", newline="", encoding="utf-8-sig"
) as f:
    writer = csv.writer(f)

    writer.writerow([
        "date",
        "race",
        "trifecta",
        "payout_yen"
    ])

    for key in sorted(all_results):
        writer.writerow(all_results[key])

print("大村の3連単データ抽出成功！")
print("今回の抽出レース数:", len(results))
print("CSV合計レース数:", len(all_results))
print("CSV保存先:", csv_file)

for row in results:
    print(row)

print("CSV変換完了")
