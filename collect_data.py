from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

url = "https://www1.mbrace.or.jp/od2/K/dindex.html"

print("BOAT RACE公式サイトへの接続テスト")

try:
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urlopen(request, timeout=20) as response:
        print("HTTPステータス:", response.status)
        print("取得データ量:", len(response.read()), "bytes")
        print("接続成功！")

except (HTTPError, URLError, TimeoutError) as error:
    print("接続失敗:", error)
    raise
