import json
import os
import stat
import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services.spotify_secret_store import (  # noqa: E402
    SpotifySecretStore,
    SpotifySecretStoreError,
)


TEST_KEY_1 = "SROVA_TEST_ONLY_SPOTIFY_KEY_ALPHA-123"
TEST_KEY_2 = "SROVA_TEST_ONLY_SPOTIFY_KEY_BETA-456"


def test_absent_state_reports_not_configured_without_creating_files(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    assert store.key_configured() is False
    assert not Path(store.private_dir).exists()
    assert not Path(store.state_file).exists()


def test_set_key_uses_dedicated_private_directory_and_file_modes(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    store.set_api_key(TEST_KEY_1)

    private_dir = Path(store.private_dir)
    state_file = Path(store.state_file)

    assert private_dir == tmp_path / "spotify"
    assert state_file == private_dir / "private_state.json"
    assert stat.S_IMODE(private_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
    assert store.get_api_key() == TEST_KEY_1
    assert store.key_configured() is True


def test_existing_private_directory_mode_is_resecured(tmp_path):
    private_dir = tmp_path / "spotify"
    private_dir.mkdir(mode=0o755)
    os.chmod(private_dir, 0o755)

    store = SpotifySecretStore(config_dir=str(tmp_path))
    store.set_api_key(TEST_KEY_1)

    assert stat.S_IMODE(private_dir.stat().st_mode) == 0o700


def test_existing_state_file_mode_is_resecured_on_read(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))
    store.set_api_key(TEST_KEY_1)

    state_file = Path(store.state_file)
    os.chmod(state_file, 0o644)

    assert store.get_api_key() == TEST_KEY_1
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600


def test_atomic_overwrite_replaces_key_without_temp_residue(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    store.set_api_key(TEST_KEY_1)
    store.set_api_key(TEST_KEY_2)

    assert store.get_api_key() == TEST_KEY_2

    private_dir = Path(store.private_dir)
    leftovers = list(private_dir.glob(".private-state.tmp-*"))
    assert leftovers == []


@pytest.mark.parametrize(
    "value",
    [
        "",
        " leading",
        "trailing ",
        "embedded space",
        "line\nbreak",
        "tab\tbreak",
        "nonascii-\u2603",
    ],
)
def test_invalid_keys_are_rejected_without_state_file(tmp_path, value):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    with pytest.raises(ValueError):
        store.set_api_key(value)

    assert not Path(store.state_file).exists()


def test_oversized_key_is_rejected(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    with pytest.raises(ValueError):
        store.set_api_key("A" * (SpotifySecretStore.MAX_API_KEY_BYTES + 1))

    assert not Path(store.state_file).exists()


def test_non_regular_state_object_is_rejected(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    private_dir = Path(store.private_dir)
    private_dir.mkdir(mode=0o700)
    Path(store.state_file).mkdir()

    with pytest.raises(SpotifySecretStoreError):
        store.get_api_key()


def test_symlink_state_file_is_rejected(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    private_dir = Path(store.private_dir)
    private_dir.mkdir(mode=0o700)

    target = tmp_path / "target.json"
    target.write_text(
        json.dumps({"version": 1, "api_key": TEST_KEY_1}),
        encoding="utf-8",
    )

    Path(store.state_file).symlink_to(target)

    with pytest.raises(SpotifySecretStoreError):
        store.get_api_key()


def test_oversized_state_file_is_rejected(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    private_dir = Path(store.private_dir)
    private_dir.mkdir(mode=0o700)

    Path(store.state_file).write_bytes(
        b"X" * (SpotifySecretStore.MAX_STATE_BYTES + 1)
    )

    with pytest.raises(SpotifySecretStoreError):
        store.get_api_key()


def test_malformed_json_is_not_silently_treated_as_unconfigured(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    private_dir = Path(store.private_dir)
    private_dir.mkdir(mode=0o700)

    Path(store.state_file).write_text(
        "{not-json",
        encoding="utf-8",
    )

    with pytest.raises(SpotifySecretStoreError):
        store.key_configured()


def test_unexpected_payload_fields_are_rejected(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    private_dir = Path(store.private_dir)
    private_dir.mkdir(mode=0o700)

    Path(store.state_file).write_text(
        json.dumps(
            {
                "version": 1,
                "api_key": TEST_KEY_1,
                "unexpected": "value",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SpotifySecretStoreError):
        store.get_api_key()


def test_read_resecures_existing_private_directory_mode(tmp_path):
    store = SpotifySecretStore(config_dir=str(tmp_path))

    private_dir = Path(store.private_dir)
    private_dir.mkdir(mode=0o755)
    os.chmod(private_dir, 0o755)

    state_file = Path(store.state_file)
    state_file.write_text(
        json.dumps(
            {
                "version": 1,
                "api_key": TEST_KEY_1,
            }
        ),
        encoding="utf-8",
    )
    os.chmod(state_file, 0o600)

    assert store.get_api_key() == TEST_KEY_1
    assert stat.S_IMODE(private_dir.stat().st_mode) == 0o700


def test_symlink_private_directory_is_rejected_on_read(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    outside_state = outside / "private_state.json"
    outside_state.write_text(
        json.dumps(
            {
                "version": 1,
                "api_key": TEST_KEY_1,
            }
        ),
        encoding="utf-8",
    )
    os.chmod(outside_state, 0o600)

    private_dir = tmp_path / "spotify"
    private_dir.symlink_to(
        outside,
        target_is_directory=True,
    )

    store = SpotifySecretStore(config_dir=str(tmp_path))

    with pytest.raises(SpotifySecretStoreError):
        store.get_api_key()
