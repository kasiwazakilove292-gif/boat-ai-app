from urllib.request import Request, urlopen
from html.parser import HTMLParser
from urllib.parse import urljoin

URL = "https://www1.mbrace.or.jp/od2/K/dindex.html"

class LinkFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(urljoin(URL, href))

print("公式サイトのリンクを確認中...")

request = Request(
    URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

with urlopen(request, timeout=30) as response:
    html = response.read()

parser = LinkFinder()
parser.feed(html.decode("cp932", errors="replace"))

print("見つかったリンク数:", len(parser.links))

for link in parser.links[:30]:
    print(link)

print("リンク確認完了")
