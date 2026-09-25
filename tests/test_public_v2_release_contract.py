from pathlib import Path
import xml.etree.ElementTree as ET

from src.version_info import build_version_payload


ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_public_v2_package_identity():
    package = read("version.txt").strip()

    assert package == "2.0-1"
    assert build_version_payload(package) == {
        "package_version": "2.0-1",
        "display_version": "2.0",
    }


def test_public_v2_readme_contract():
    text = read("README.md")

    assert "SROVA Version 2.0" in text
    assert "Debian package version `2.0-1`" in text
    assert "SOURCE 03" in text
    assert "TIDAL" in text
    assert "QOBUZ" in text
    assert "ONLINE" in text
    assert "Spotify/Soloist is not SOURCE 04" in text
    assert "/opt/srova" in text
    assert "8081" in text


def test_public_v2_notice_contract():
    text = read("NOTICE.md")

    assert (
        "7e9d57aed0293aca85b2a707cf3843dde59bb2e5"
        in text
    )
    assert (
        "aa5690e4491507976b56a982025eb4b38ec8e064"
        in text
    )
    assert "MIT License" in text
    assert "SOURCE 04" in text
    assert "not\nredistributed" in text


def test_public_v2_changelog_preserves_public_history():
    text = read("CHANGELOG.md")

    assert "## 2.0 (`2.0-1`) — 2026-09-25" in text
    assert "## 1.4 (`1.4-1`) — 2026-08-28" in text
    assert "## 1.3 (`1.3-1`) — 2026-08-19" in text
    assert "## 1.4 — In development" not in text


def test_public_v2_appstream_history():
    path = ROOT / "flatpak/com.srova.player.metainfo.xml"
    tree = ET.parse(path)

    releases = tree.getroot().find("releases")
    assert releases is not None

    rows = [
        (
            item.attrib.get("version"),
            item.attrib.get("date"),
        )
        for item in releases.findall("release")
    ]

    assert rows[0] == ("2.0-1", "2026-09-25")
    assert ("1.4-1", "2026-08-28") in rows


def test_public_v2_arm64_contract():
    source = read("packaging/arm64/build_rc1_deb.sh")

    assert 'SOURCE_REF="${SROVA_ARM64_SOURCE_REF:-HEAD}"' in source
    assert 'SOURCE_COMMIT=""' in source
    assert 'VERSION="2.0-1"' in source
    assert 'APP="${TREE}/opt/srova"' in source
    assert "WorkingDirectory=/opt/srova" in source
    assert "Environment=SROVA_PORT=8081" in source
    assert "/opt/srova/app" not in source
    assert 'EXPECTED_TAG="v1.0-rc1"' not in source


def test_public_v2_arm64_documentation_contract():
    text = read("packaging/arm64/README.md")

    assert "Debian package version: `2.0-1`" in text
    assert "installed runtime root: `/opt/srova`" in text
    assert "default control port: `8081`" in text
    assert "source default: `HEAD`" in text
    assert "ARM64 RC1 Debian Builder" not in text


def test_public_source_exclusions():
    assert not (ROOT / "AGENTS.md").exists()
    assert not (
        ROOT
        / "docs/design_refs/amber_analog_vu_reference.png"
    ).exists()
    assert not (
        ROOT
        / "src_rust/librust_audio_core.so"
    ).exists()


def test_public_source_shared_library_policy():
    text = read(".gitignore")

    assert "*.so" in text
    assert "!src_rust/librust_audio_core.so" not in text
