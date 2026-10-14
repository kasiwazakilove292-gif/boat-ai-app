from pathlib import Path
import subprocess
import shutil

archive = Path("k260901.lzh")
output_dir = Path("data")
output_dir.mkdir(exist_ok=True)

print("大村競艇AI：競走成績の解凍開始")

if not archive.exists():
    raise FileNotFoundError("k260901.lzh が見つかりません")

if not shutil.which("bsdtar"):
    raise RuntimeError("bsdtar が必要です")

subprocess.run(
    ["bsdtar", "-xf", str(archive), "-C", str(output_dir)],
    check=True
)

print("解凍成功！")

for file in output_dir.iterdir():
    print("取り出したファイル:", file.name)
    print("ファイルサイズ:", file.stat().st_size, "bytes")

print("解凍処理完了")
