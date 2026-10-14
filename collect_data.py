from urllib.request import Request, urlopen
from html.parser import HTMLParser

URL = "https://www1.mbrace.or.jp/od2/K/dmenu.html"

request = Request(
    URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

with urlopen(request, timeout=30) as response:
    data = response.read()
    print("HTTPステータス:", response.status)
    print("最終URL:", response.url)
    print("データサイズ:", len(data), "bytes")

html = data.decode("cp932", errors="replace")

class PageInspector(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("a", "form", "input", "select", "option", "script"):
            print("タグ:", tag, "属性:", attrs)

print("=== ページ構造の確認 ===")
PageInspector().feed(html)

print("=== HTML先頭500文字 ===")
print(html[:500])

print("調査完了")
