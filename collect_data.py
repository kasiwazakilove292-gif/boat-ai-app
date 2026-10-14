from pathlib import Path
import subprocess
import shutil
import re
import csv

import os

from datetime import datetime

date_str = os.getenv("RACE_DATE", "2026-09-01")

race_date = datetime.strptime(date_str, "%Y-%m-%d")

file_code = race_date.strftime("%y%m%d")

archive = Path(f"k{file_code}.lzh")
output_dir = Path("data")
output_dir.mkdir(exist_ok=True)

if not archive.exists():
    raise FileNotFoundError("LZHファイルが見つかりません")

if not shutil.which("bsdtar"):
    raise RuntimeError("bsdtarが見つかりません")

subprocess.run(
    ["bsdtar", "-xf", str(archive), "-C", str(output_dir)],
    check=True
)

txt_file = output_dir / f"K{file_code}.TXT"
text = txt_file.read_bytes().decode("cp932")

# 会場ごとのデータを分ける
headers = list(re.finditer(
    r"^.*\d{4}/\s*\d{1,2}/\s*\d{1,2}.*ボートレース.*$",
    text,
    re.MULTILINE
))

omura = None

for i, match in enumerate(headers):
    end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
    section = text[match.start():end]
    header = match.group().replace("\u3000", "").replace(" ", "")

    if "ボートレース大村" in header:
        omura = section
        break

if omura is None:
    raise RuntimeError("大村のレースデータが見つかりません")

# 払戻金一覧から3連単を抽出
results = []

for line in omura.splitlines():
    match = re.match(
        r"^\s*(\d{1,2})R\s+([1-6]-[1-6]-[1-6])\s+(\d+)",
        line
    )
    if match:
        results.append([
            "2026-09-01",
            int(match.group(1)),
            match.group(2),
            int(match.group(3))
        ])

if len(results) != 12:
    raise RuntimeError(
        f"抽出件数が想定と違います: {len(results)}件"
    )

csv_file = output_dir / "omura_results.csv"

with csv_file.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["date", "race", "trifecta", "payout_yen"])
    writer.writerows(results)

print("大村の3連単データ抽出成功！")
print("抽出レース数:", len(results))
print("CSV保存先:", csv_file)

for row in results:
    print(row)

print("CSV変換完了")
