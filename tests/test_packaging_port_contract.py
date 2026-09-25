from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AMD64 = (ROOT / "package.sh").read_text(encoding="utf-8")
ARM64 = (
    ROOT / "packaging" / "arm64" / "build_rc1_deb.sh"
).read_text(encoding="utf-8")

FORBIDDEN_PORT = "8080"
AUTHORITATIVE_PORT = "8081"


def _heredoc(source: str, opener: str, terminator: str = "EOF") -> str:
    opener_pos = source.index(opener)
    start = source.index("\n", opener_pos) + 1
    end = source.index(f"\n{terminator}\n", start)
    return source[start:end]


def _assert_no_srova_8080(label: str, surface: str) -> None:
    assert FORBIDDEN_PORT not in surface, (
        f"{label} reintroduced SROVA-owned semantic port "
        f"{FORBIDDEN_PORT}"
    )


def _amd64_open_helper() -> str:
    return _heredoc(
        AMD64,
        'cat <<\'SROVA_OPEN_HELPER\' > "$BIN_DIR/srova-open"',
        "SROVA_OPEN_HELPER",
    )


def _arm64_open_helper() -> str:
    return _heredoc(
        ARM64,
        'cat > "$TREE/usr/bin/srova-open" <<\'EOF\'',
    )


def _arm64_service() -> str:
    return _heredoc(
        ARM64,
        'cat > "$TREE/usr/lib/systemd/system/srova.service" <<\'EOF\'',
    )


def _arm64_env_example() -> str:
    return _heredoc(
        ARM64,
        'cat > "$TREE/etc/srova/srova.env.example" <<\'EOF\'',
    )


def _arm64_readme_debian() -> str:
    return _heredoc(
        ARM64,
        'cat > "$TREE/usr/share/doc/srova/README.Debian" <<\'EOF\'',
    )


def test_amd64_open_helper_is_authoritative_8081_only():
    helper = _amd64_open_helper()

    _assert_no_srova_8080("AMD64 srova-open", helper)

    assert "detect_port() {" in helper
    assert f"echo {AUTHORITATIVE_PORT}" in helper
    assert "ss -ltn" not in helper
    assert "systemctl show" not in helper


def test_arm64_open_helper_preserves_configured_port_with_8081_fallback():
    helper = _arm64_open_helper()

    _assert_no_srova_8080("ARM64 srova-open", helper)

    assert "/var/lib/srova/srova.env" in helper
    assert "SROVA_PORT" in helper
    assert "configured_port" in helper
    assert 'echo "$configured_port"' in helper
    assert f"echo {AUTHORITATIVE_PORT}" in helper

    configured = helper.index('echo "$configured_port"')
    fallback = helper.rindex(f"echo {AUTHORITATIVE_PORT}")
    assert configured < fallback


def test_arm64_service_has_8081_default_and_configurable_runtime_port():
    service = _arm64_service()

    _assert_no_srova_8080("ARM64 systemd service", service)

    assert f"Environment=SROVA_PORT={AUTHORITATIVE_PORT}" in service
    assert "EnvironmentFile=-/var/lib/srova/srova.env" in service
    assert "--port ${SROVA_PORT}" in service


def test_arm64_environment_example_defaults_to_8081():
    env_example = _arm64_env_example()

    _assert_no_srova_8080("ARM64 environment example", env_example)

    assert f"SROVA_PORT={AUTHORITATIVE_PORT}" in env_example


def test_arm64_readme_debian_documents_8081():
    readme = _arm64_readme_debian()

    _assert_no_srova_8080("ARM64 README.Debian", readme)

    assert f"http://<device-ip>:{AUTHORITATIVE_PORT}" in readme
    assert "/var/lib/srova/srova.env" in readme


def test_all_bounded_packaging_port_surfaces_are_free_of_semantic_8080():
    surfaces = {
        "AMD64 srova-open": _amd64_open_helper(),
        "ARM64 srova-open": _arm64_open_helper(),
        "ARM64 systemd service": _arm64_service(),
        "ARM64 environment example": _arm64_env_example(),
        "ARM64 README.Debian": _arm64_readme_debian(),
    }

    for label, surface in surfaces.items():
        _assert_no_srova_8080(label, surface)


def test_semantic_8080_guard_rejects_negative_control_without_source_mutation():
    with pytest.raises(AssertionError, match="reintroduced"):
        _assert_no_srova_8080(
            "negative control",
            "detect_port() {\n  echo 8080\n}\n",
        )
