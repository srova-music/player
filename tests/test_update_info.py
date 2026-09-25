import hashlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import update_info


def release(version="v1.3.0", assets=None):
    return {
        "tag_name": version,
        "name": "SROVA " + version,
        "html_url": "https://github.com/srova-music/srova/releases/tag/" + version,
        "assets": assets or [],
    }


def asset(name):
    return {"name": name, "browser_download_url": "https://downloads.example/" + name}


def test_semantic_version_comparison_and_prereleases():
    assert update_info.is_newer_version("1.10", "1.9")
    assert update_info.is_newer_version("v1.3.0", "1.2-1")
    assert update_info.is_newer_version("1.3", "1.3 RC1")
    assert not update_info.is_newer_version("1.3 RC1", "1.3")
    assert not update_info.is_newer_version("garbage", "1.2")


def test_amd64_and_arm64_receive_matching_package():
    item = release(assets=[
        asset("srova_1.3-1_amd64.deb"),
        asset("srova_1.3-1_arm64.deb"),
    ])
    amd = update_info.build_update_payload(item, {"display_version": "1.2"}, "x86_64")
    arm = update_info.build_update_payload(item, {"display_version": "1.2"}, "aarch64")
    assert amd["download_url"].endswith("_amd64.deb")
    assert arm["download_url"].endswith("_arm64.deb")
    assert amd["download_kind"] == arm["download_kind"] == "package"


def test_unknown_architecture_and_missing_asset_fall_back_to_release_page():
    item = release(assets=[asset("srova_1.3-1_amd64.deb")])
    payload = update_info.build_update_payload(item, {"display_version": "1.2"}, "riscv64")
    assert payload["architecture"] == "unknown"
    assert payload["download_kind"] == "release_page"
    assert payload["download_url"] == item["html_url"]


def test_equal_older_and_malformed_latest_do_not_report_update():
    for latest in ("v1.2.0", "v1.1.9", "not-a-version"):
        payload = update_info.build_update_payload(release(latest), {"display_version": "1.2"})
        assert payload["update_available"] is False
        assert payload["download_url"] == ""


class FakeResponse:
    def __init__(self, body):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_update_lookup_is_cached_and_failure_is_neutral(monkeypatch):
    calls = []

    def opener(_request, timeout):
        calls.append(timeout)
        return FakeResponse(
            '<title>SROVA Downloads — Version 1.3</title>'
            '<a href="https://downloads.srova.music/srova_1.3-1_amd64.deb">Download</a>'
        )

    monkeypatch.setattr(update_info, "read_version_payload", lambda: {"display_version": "1.2"})
    update_info.clear_update_cache()
    first = update_info.read_update_payload(now=10, opener=opener, machine="amd64")
    second = update_info.read_update_payload(now=11, opener=lambda *_a, **_k: None, machine="amd64")
    assert first == second
    assert calls == [update_info.UPDATE_TIMEOUT_SECONDS]

    update_info.clear_update_cache()
    failed = update_info.read_update_payload(
        now=20,
        opener=lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError()),
        machine="amd64",
    )
    assert failed["ok"] is False
    assert failed["update_available"] is False


def test_public_download_page_contract_is_parsed():
    item = update_info._downloads_release_from_html(
        '<title>SROVA Downloads — Version 1.3</title>'
        '<a href="https://downloads.srova.music/srova_1.3-1_amd64.deb">AMD64</a>'
        '<a href="https://downloads.srova.music/srova_1.3-1_arm64.deb">ARM64</a>'
    )
    assert item["tag_name"] == "1.3"
    assert [entry["name"] for entry in item["assets"]] == [
        "srova_1.3-1_amd64.deb", "srova_1.3-1_arm64.deb"
    ]


def test_explicit_test_version_bypasses_network_and_uses_download_page(monkeypatch):
    monkeypatch.setenv("SROVA_UPDATE_TEST_VERSION", "1.3")
    monkeypatch.setattr(update_info, "read_version_payload", lambda: {"display_version": "1.2"})
    payload = update_info.read_update_payload(
        opener=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network used")),
        machine="amd64",
    )
    assert payload["update_available"] is True
    assert payload["latest_version"] == "1.3"
    assert payload["download_kind"] == "package"
    assert payload["download_url"] == "https://downloads.srova.music/srova_1.3-1_amd64.deb"


def test_master_dot_asset_and_ui_wiring_are_packaged():
    dot = REPO_ROOT / "src/ui_web/assets/srova-red-update-dot.png"
    assert hashlib.sha256(dot.read_bytes()).hexdigest() == "742643d58c5ec6486084d0c6438d21f06ae24b40c163d312a2eeb1326e68d8e5"
    ui = (REPO_ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
    index = (REPO_ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")
    package = (REPO_ROOT / "package.sh").read_text(encoding="utf-8")
    assert '"/api/update-status"' in ui
    assert "Update available — Version " in ui
    assert 'dot.setAttribute("data-update-kind", tabDef.id);' in ui
    assert "spotifySoloistUpdateAvailableNow()" in ui
    assert "var available = srovaAvailable || soloistAvailable;" in ui
    assert 'label.className = "settingsTabLabel"' in ui
    assert "settingsUpdateDot" in index
    assert "src/update_info.py" in package
