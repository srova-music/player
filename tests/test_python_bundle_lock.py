from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "packaging" / "python-bundle-requirements.lock"
PACKAGE_SH = ROOT / "package.sh"


EXPECTED = {
    "certifi": "2026.7.22",
    "idna": "3.18",
    "isodate": "0.7.2",
    "mpegdash": "0.4.1",
    "pyaes": "1.6.1",
    "pystray": "0.19.5",
    "python-dateutil": "2.9.0.post0",
    "python-xlib": "0.33",
    "qrcode": "8.2",
    "ratelimit": "2.2.1",
    "requests": "2.34.2",
    "six": "1.17.0",
    "tidalapi": "0.8.11",
    "typing-extensions": "4.16.0",
    "urllib3": "2.7.0",
}


def read_lock():
    rows = []

    for raw in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        rows.append(line)

    return rows


def test_python_bundle_lock_contains_only_exact_unique_pins():
    rows = read_lock()
    parsed = {}

    assert len(rows) == 15

    for row in rows:
        match = re.fullmatch(
            r"([a-z0-9][a-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+-]*)",
            row,
        )

        assert match, f"Non-exact package lock entry: {row}"

        name = match.group(1).lower().replace("_", "-")
        version = match.group(2)

        assert name not in parsed, f"Duplicate package: {name}"
        parsed[name] = version

    assert parsed == EXPECTED


def test_package_script_uses_lock_without_dependency_resolution():
    text = PACKAGE_SH.read_text(encoding="utf-8")

    assert (
        'PYTHON_BUNDLE_LOCK="${SROVA_PYTHON_BUNDLE_LOCK:-'
        'packaging/python-bundle-requirements.lock}"'
        in text
    )

    assert '--requirement "$PYTHON_BUNDLE_LOCK"' in text
    assert "--no-deps" in text
    assert 'STRICT_PYTHON_BUNDLE="${SROVA_STRICT_PYTHON_BUNDLE:-0}"' in text
    assert 'if [ "$STRICT_PYTHON_BUNDLE" = "1" ]; then' in text

    assert (
        "pip3 install tidalapi requests urllib3 pystray"
        not in text
    )

def test_compiled_python_dependencies_are_system_supplied():
    rows = read_lock()
    text = PACKAGE_SH.read_text(encoding="utf-8")

    assert not any(
        row.startswith("pillow==")
        for row in rows
    )

    assert not any(
        row.startswith("charset-normalizer==")
        for row in rows
    )

    assert text.count("python3-pil") == 2
    assert text.count("python3-charset-normalizer") == 2

    assert (
        re.search(
            r'^[ \t]*"PIL",[ \t]*$',
            text,
            re.MULTILINE,
        )
        is None
    )

    assert (
        re.search(
            r'^[ \t]*"charset_normalizer",[ \t]*$',
            text,
            re.MULTILINE,
        )
        is None
    )

    assert "-name '*.cpython-*.so'" in text
    assert '"$INSTALL_DIR/libs/PIL"' in text
    assert '"$INSTALL_DIR/libs/pillow.libs"' in text
    assert '"$INSTALL_DIR/libs/charset_normalizer"' in text
    assert "-iname 'pillow-*.dist-info'" in text
    assert "-iname 'charset_normalizer-*.dist-info'" in text

    assert (
        "Portable Python bundle contains no build-host "
        "CPython extensions"
        in text
    )

