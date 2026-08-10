from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
UI_WEB = ROOT / "src" / "ui_web"
INDEX = UI_WEB / "index.html"
SROVA_CSS = UI_WEB / "srova.css"


class LocalAssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("href"):
            self.assets.append(values["href"])
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"])


def test_index_local_browser_assets_exist():
    parser = LocalAssetParser()
    parser.feed(INDEX.read_text(encoding="utf-8"))

    local_assets = [
        urlparse(asset).path
        for asset in parser.assets
        if urlparse(asset).path.startswith("/ui_web/")
    ]

    assert local_assets
    for asset in local_assets:
        assert (ROOT / "src" / asset.lstrip("/")).is_file(), asset


def test_removed_legacy_stylesheet_is_not_referenced():
    index = INDEX.read_text(encoding="utf-8")
    css = SROVA_CSS.read_text(encoding="utf-8")

    assert "/ui_web/ui.css" not in index
    assert "ui.css" not in css
