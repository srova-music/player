from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "packaging" / "python-bundle-requirements.lock"
PACKAGE_SH = ROOT / "package.sh"
ARM64_PACKAGE_SH = ROOT / "packaging" / "arm64" / "build_rc1_deb.sh"


EXPECTED = {
    "certifi": "2026.7.22",
    "charset-normalizer": "3.4.9",
    "idna": "3.18",
    "isodate": "0.7.2",
    "mpegdash": "0.4.1",
    "pillow": "12.3.0",
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

    assert len(rows) == 17

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
def test_native_cryptography_is_a_system_package_not_a_portable_bundle():
    package_text = PACKAGE_SH.read_text(encoding="utf-8")
    arm64_text = ARM64_PACKAGE_SH.read_text(encoding="utf-8")

    package_depends = [
        line
        for line in package_text.splitlines()
        if line.startswith("Depends:")
    ]
    arm64_depends = [
        line
        for line in arm64_text.splitlines()
        if line.startswith("Depends:")
    ]

    assert package_depends
    assert arm64_depends

    assert all(
        "python3-cryptography" in line
        for line in package_depends
    )
    assert all(
        "python3-cryptography" in line
        for line in arm64_depends
    )

    locked_names = {
        row.split("==", 1)[0].lower().replace("_", "-")
        for row in read_lock()
    }

    # Public-source portability policy:
    # cryptography is supplied by Debian, never by the portable Python lock.
    assert "cryptography" not in locked_names

    # AMD64 portable-bundle fallback must not manually copy cryptography.
    fallback_match = re.search(
        r"from importlib[.]util import find_spec\s+"
        r"target = sys[.]argv\[1\]\s+"
        r"modules = \[(.*?)\]\s+"
        r"def copy_path",
        package_text,
        re.DOTALL,
    )
    assert fallback_match
    assert '"cryptography"' not in fallback_match.group(1)

    # ARM64 portable bundle copy section must not copy cryptography either.
    arm_bundle_start = 'echo "=== Bundle Python deps into /opt/srova/libs ==="'
    arm_bundle_end = 'echo "=== Write runtime helpers and metadata ==="'

    assert arm_bundle_start in arm64_text
    assert arm_bundle_end in arm64_text

    arm_bundle_text = (
        arm64_text
        .split(arm_bundle_start, 1)[1]
        .split(arm_bundle_end, 1)[0]
    )

    assert "cryptography" not in arm_bundle_text

    # ARM package audit verifies the system module is importable.
    assert '"cryptography",' in arm64_text

    # Preserve the curated Public P1 deletion of private bundle-guard code.
    assert '"$INSTALL_DIR/libs/cryptography"' not in package_text
    assert '"$INSTALL_DIR/libs/cryptography.libs"' not in package_text
    assert "-iname 'cryptography-*.dist-info'" not in package_text

    assert '"$APP/libs/cryptography"' not in arm64_text
    assert '"$APP/libs/cryptography.libs"' not in arm64_text
    assert "-iname 'cryptography-*.dist-info'" not in arm64_text
