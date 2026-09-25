from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "src"),
)

from services.spotify_alsa_pcm_verifier import (
    SpotifyAlsaPcmVerificationError,
    SpotifyAlsaPcmVerifier,
)


SOURCE = Path(
    "src/services/spotify_alsa_pcm_verifier.py"
).read_text(encoding="utf-8")


def _make_pcm(
    root: Path,
    *,
    card: int = 0,
    device: int = 0,
    statuses=("closed",),
):
    pcm = root / f"card{card}" / f"pcm{device}p"
    pcm.mkdir(parents=True)

    paths = []

    for index, content in enumerate(statuses):
        sub = pcm / f"sub{index}"
        sub.mkdir()
        status = sub / "status"
        status.write_text(
            content,
            encoding="utf-8",
        )
        paths.append(status)

    return pcm, paths


def _verifier(root: Path, **kwargs):
    return SpotifyAlsaPcmVerifier(
        proc_root=str(root),
        wait_timeout_seconds=kwargs.pop(
            "wait_timeout_seconds",
            0.05,
        ),
        poll_seconds=kwargs.pop(
            "poll_seconds",
            0.001,
        ),
        **kwargs,
    )


def test_constructor_is_side_effect_free(tmp_path):
    missing = tmp_path / "not-created"

    verifier = SpotifyAlsaPcmVerifier(
        proc_root=str(missing)
    )

    assert verifier.proc_root == str(missing)
    assert not missing.exists()


def test_default_proc_root():
    verifier = SpotifyAlsaPcmVerifier()

    assert verifier.proc_root == "/proc/asound"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "proc/asound",
        None,
        123,
    ],
)
def test_invalid_proc_root_rejected(value):
    with pytest.raises(ValueError):
        SpotifyAlsaPcmVerifier(
            proc_root=value,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("wait_timeout_seconds", 0),
        ("wait_timeout_seconds", -1),
        ("wait_timeout_seconds", True),
        ("wait_timeout_seconds", float("inf")),
        ("poll_seconds", 0),
        ("poll_seconds", -1),
        ("poll_seconds", False),
        ("poll_seconds", float("nan")),
    ],
)
def test_invalid_seconds_rejected(field, value):
    kwargs = {
        field: value,
    }

    with pytest.raises(ValueError):
        SpotifyAlsaPcmVerifier(
            **kwargs,
        )


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        True,
        1.5,
        "4096",
    ],
)
def test_invalid_max_status_chars_rejected(value):
    with pytest.raises(ValueError):
        SpotifyAlsaPcmVerifier(
            max_status_chars=value,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("card_number", -1),
        ("card_number", True),
        ("card_number", 0.0),
        ("card_number", "0"),
        ("device_number", -1),
        ("device_number", False),
        ("device_number", 0.0),
        ("device_number", "0"),
    ],
)
def test_invalid_pcm_identity_rejected(
    tmp_path,
    field,
    value,
):
    verifier = _verifier(tmp_path)

    kwargs = {
        "card_number": 0,
        "device_number": 0,
    }
    kwargs[field] = value

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(**kwargs)


def test_missing_pcm_root_fails_closed(tmp_path):
    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_pcm_root_symlink_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir(parents=True)

    card = tmp_path / "card0"
    card.mkdir()

    (card / "pcm0p").symlink_to(
        real,
        target_is_directory=True,
    )

    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_no_substreams_fails_closed(tmp_path):
    pcm = tmp_path / "card0" / "pcm0p"
    pcm.mkdir(parents=True)

    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_substream_symlink_rejected(tmp_path):
    pcm = tmp_path / "card0" / "pcm0p"
    pcm.mkdir(parents=True)

    real = tmp_path / "real-sub"
    real.mkdir()
    (real / "status").write_text(
        "closed\n",
        encoding="utf-8",
    )

    (pcm / "sub0").symlink_to(
        real,
        target_is_directory=True,
    )

    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_missing_status_fails_closed(tmp_path):
    pcm = tmp_path / "card0" / "pcm0p"
    sub = pcm / "sub0"
    sub.mkdir(parents=True)

    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_status_symlink_rejected(tmp_path):
    pcm = tmp_path / "card0" / "pcm0p"
    sub = pcm / "sub0"
    sub.mkdir(parents=True)

    real = tmp_path / "status-real"
    real.write_text(
        "closed\n",
        encoding="utf-8",
    )

    (sub / "status").symlink_to(real)

    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


@pytest.mark.parametrize(
    "content",
    [
        "closed",
        "closed\n",
        "  closed  \n",
    ],
)
def test_closed_status_is_free(
    tmp_path,
    content,
):
    _make_pcm(
        tmp_path,
        statuses=[content],
    )

    verifier = _verifier(tmp_path)

    assert verifier.is_free(
        card_number=0,
        device_number=0,
    ) is True


@pytest.mark.parametrize(
    "state",
    [
        "RUNNING",
        "OPEN",
        "SETUP",
        "PREPARED",
        "XRUN",
        "DRAINING",
        "PAUSED",
        "SUSPENDED",
        "DISCONNECTED",
    ],
)
def test_valid_alsa_state_is_busy(
    tmp_path,
    state,
):
    _make_pcm(
        tmp_path,
        statuses=[
            f"state: {state}\nowner_pid   : 123\n"
        ],
    )

    verifier = _verifier(tmp_path)

    assert verifier.is_free(
        card_number=0,
        device_number=0,
    ) is False


def test_real_observed_running_shape_is_busy(
    tmp_path,
):
    _make_pcm(
        tmp_path,
        statuses=[
            (
                "state: RUNNING\n"
                "owner_pid   : 1285137\n"
                "trigger_time: 4409760.114848616\n"
                "tstamp      : 0.000000000\n"
                "delay       : 24456\n"
                "avail       : 0\n"
                "avail_max   : 18000\n"
                "-----\n"
                "hw_ptr      : 504\n"
                "appl_ptr    : 24504\n"
            )
        ],
    )

    verifier = _verifier(tmp_path)

    assert verifier.is_free(
        card_number=0,
        device_number=0,
    ) is False


def test_all_substreams_must_be_closed(tmp_path):
    _make_pcm(
        tmp_path,
        statuses=[
            "closed\n",
            "closed\n",
            "closed\n",
        ],
    )

    verifier = _verifier(tmp_path)

    assert verifier.is_free(
        card_number=0,
        device_number=0,
    ) is True


def test_one_busy_substream_blocks_release(
    tmp_path,
):
    _make_pcm(
        tmp_path,
        statuses=[
            "closed\n",
            "state: RUNNING\nowner_pid: 1\n",
            "closed\n",
        ],
    )

    verifier = _verifier(tmp_path)

    assert verifier.is_free(
        card_number=0,
        device_number=0,
    ) is False


@pytest.mark.parametrize(
    "content",
    [
        "",
        "\n",
        "garbage",
        "RUNNING",
        "state:",
        "state: running",
        "closed\nunexpected",
    ],
)
def test_malformed_status_fails_closed(
    tmp_path,
    content,
):
    _make_pcm(
        tmp_path,
        statuses=[content],
    )

    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_busy_plus_malformed_still_errors(
    tmp_path,
):
    _make_pcm(
        tmp_path,
        statuses=[
            "state: RUNNING\nowner_pid: 1\n",
            "garbage",
        ],
    )

    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_oversized_status_fails_closed(
    tmp_path,
):
    _make_pcm(
        tmp_path,
        statuses=[
            "state: RUNNING\n" + ("x" * 100)
        ],
    )

    verifier = _verifier(
        tmp_path,
        max_status_chars=32,
    )

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_invalid_utf8_fails_closed(tmp_path):
    _pcm, paths = _make_pcm(
        tmp_path,
        statuses=["closed"],
    )

    paths[0].write_bytes(
        b"\xff\xfe\xfd"
    )

    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_nonzero_card_and_device_supported(
    tmp_path,
):
    _make_pcm(
        tmp_path,
        card=3,
        device=2,
        statuses=["closed"],
    )

    verifier = _verifier(tmp_path)

    assert verifier.is_free(
        card_number=3,
        device_number=2,
    ) is True


def test_wait_until_free_returns_immediately(
    tmp_path,
    monkeypatch,
):
    _make_pcm(
        tmp_path,
        statuses=["closed"],
    )

    verifier = _verifier(tmp_path)

    sleeps = []

    monkeypatch.setattr(
        "services.spotify_alsa_pcm_verifier.time.sleep",
        lambda value: sleeps.append(value),
    )

    assert verifier.wait_until_free(
        card_number=0,
        device_number=0,
    ) is True

    assert sleeps == []


def test_wait_until_free_observes_release(
    tmp_path,
    monkeypatch,
):
    _pcm, paths = _make_pcm(
        tmp_path,
        statuses=[
            "state: RUNNING\nowner_pid: 123\n"
        ],
    )

    verifier = _verifier(
        tmp_path,
        wait_timeout_seconds=1.0,
        poll_seconds=0.01,
    )

    clock = [10.0]
    sleeps = []

    monkeypatch.setattr(
        "services.spotify_alsa_pcm_verifier.time.monotonic",
        lambda: clock[0],
    )

    def fake_sleep(value):
        sleeps.append(value)
        paths[0].write_text(
            "closed\n",
            encoding="utf-8",
        )
        clock[0] += value

    monkeypatch.setattr(
        "services.spotify_alsa_pcm_verifier.time.sleep",
        fake_sleep,
    )

    assert verifier.wait_until_free(
        card_number=0,
        device_number=0,
    ) is True

    assert len(sleeps) == 1


def test_wait_until_free_times_out_closed(
    tmp_path,
    monkeypatch,
):
    _make_pcm(
        tmp_path,
        statuses=[
            "state: RUNNING\nowner_pid: 123\n"
        ],
    )

    verifier = _verifier(
        tmp_path,
        wait_timeout_seconds=0.05,
        poll_seconds=0.01,
    )

    clock = [20.0]

    monkeypatch.setattr(
        "services.spotify_alsa_pcm_verifier.time.monotonic",
        lambda: clock[0],
    )

    monkeypatch.setattr(
        "services.spotify_alsa_pcm_verifier.time.sleep",
        lambda value: clock.__setitem__(
            0,
            clock[0] + value,
        ),
    )

    with pytest.raises(
        SpotifyAlsaPcmVerificationError,
        match="did not become free",
    ):
        verifier.wait_until_free(
            card_number=0,
            device_number=0,
        )


def test_wait_until_free_inspection_error_is_not_timeout(
    tmp_path,
):
    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError,
        match="status is unavailable",
    ):
        verifier.wait_until_free(
            card_number=0,
            device_number=0,
        )


def test_errors_do_not_echo_proc_path_or_status(
    tmp_path,
):
    secretish = "PRIVATE-OWNER-DATA"

    _make_pcm(
        tmp_path,
        statuses=[secretish],
    )

    verifier = _verifier(tmp_path)

    with pytest.raises(
        SpotifyAlsaPcmVerificationError
    ) as raised:
        verifier.is_free(
            card_number=0,
            device_number=0,
        )

    message = str(raised.value)

    assert secretish not in message
    assert str(tmp_path) not in message


def test_component_has_no_process_or_spotify_dependencies():
    tree = ast.parse(SOURCE)

    imports = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")

    assert imports == {
        "__future__",
        "math",
        "os",
        "re",
        "stat",
        "time",
        "pathlib",
    }

    lowered = SOURCE.lower()

    for forbidden in (
        "subprocess",
        "fuser",
        "lsof",
        "spotifycoordinator",
        "spotifyruntime",
        "spotifysoloist",
        "spotifysecret",
        "pipewire",
        "websocket",
        "main_headless",
        "systemctl",
        "sudo",
        "shell=true",
    ):
        assert forbidden not in lowered


# BF4_PCM_ABSENCE_IS_NOT_FREE
def test_selected_pcm_absence_is_distinct_from_free_verification(tmp_path):
    verifier = _verifier(tmp_path)

    assert verifier.is_absent(
        card_number=0,
        device_number=0,
    ) is True

    with pytest.raises(SpotifyAlsaPcmVerificationError):
        verifier.is_free(
            card_number=0,
            device_number=0,
        )


def test_existing_pcm_is_not_reported_absent(tmp_path):
    _make_pcm(
        tmp_path,
        statuses=["closed\n"],
    )
    verifier = _verifier(tmp_path)

    assert verifier.is_absent(
        card_number=0,
        device_number=0,
    ) is False
