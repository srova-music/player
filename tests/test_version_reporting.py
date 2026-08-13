import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from version_info import build_version_payload, display_version_for
from version_info import read_version_payload


def test_final_debian_package_version_has_clean_display_version():
    assert build_version_payload("1.2-1") == {
        "package_version": "1.2-1",
        "display_version": "1.2",
    }


def test_release_candidate_version_remains_readable():
    assert display_version_for("1.2~rc1-1") == "1.2 RC1"


def test_version_reader_uses_first_readable_nonempty_candidate(tmp_path):
    missing = tmp_path / "missing-version.txt"
    empty = tmp_path / "empty-version.txt"
    valid = tmp_path / "version.txt"

    empty.write_text("\n", encoding="utf-8")
    valid.write_text("1.2-1\n", encoding="utf-8")

    assert read_version_payload((missing, empty, valid)) == {
        "package_version": "1.2-1",
        "display_version": "1.2",
    }


def test_about_page_reads_backend_version_instead_of_hardcoding_v1():
    ui_path = REPO_ROOT / "src" / "ui_web" / "ui.js"
    main_path = REPO_ROOT / "src" / "main_headless.py"

    ui = ui_path.read_text(encoding="utf-8")
    main = main_path.read_text(encoding="utf-8")

    assert 'version.textContent = "Ver 1.0";' not in ui
    assert 'fetch("/api/version?_' in ui
    assert 'static_path == "/api/version"' in main
    assert "read_version_payload()" in main


def test_ui_cache_key_tracks_about_version_change():
    index_path = REPO_ROOT / "src" / "ui_web" / "index.html"
    index = index_path.read_text(encoding="utf-8")

    assert (
        '/ui_web/ui.js?v=20260812_v1_2_queue_drag2'
        in index
    )

def test_package_preflight_requires_version_helper():
    package_path = REPO_ROOT / "package.sh"
    package = package_path.read_text(encoding="utf-8")

    assert "HEADLESS_RUNTIME_REQUIRED=(" in package
    assert "    src/version_info.py\n" in package
