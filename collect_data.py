from pathlib import Path

FILE = Path("k260901.lzh")

print("大村競艇AI：競走成績ファイル確認")

if not FILE.exists():
    print("ファイルがまだGitHubにありません")
    print("次の手順でアップロードします")
else:
    data = FILE.read_bytes()
    print("ファイル名:", FILE.name)
    print("ファイルサイズ:", len(data), "bytes")

    if b"-lh" in data[:100]:
        print("LZH形式のファイルを確認しました")
    else:
        print("ファイル形式を確認してください")

print("確認終了")
