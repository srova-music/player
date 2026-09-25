import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services.spotify_soloist_listener_resolver import (  # noqa: E402
    SpotifySoloistLanListenerResolver,
    SpotifySoloistListenerResolutionError,
)


HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"


def _tcp(address_hex, port, inode, state="0A"):
    return (
        f"  0: {address_hex}:{port:04X} 00000000:0000 {state} "
        f"00000000:00000000 00:00000000 00000000 1000 0 {inode}\n"
    )


class FakeClock:
    def __init__(self):
        self.now = 10.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _resolver(*, tables, links=None, clock=None, listdir=None):
    remaining = list(tables)
    links = links or {"3": "socket:[100]"}
    clock = clock or FakeClock()

    def read_text(_path):
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    def readlink(path):
        return links[Path(path).name]

    return SpotifySoloistLanListenerResolver(
        timeout_seconds=0.2,
        poll_seconds=0.05,
        read_text=read_text,
        readlink=readlink,
        listdir=listdir or (lambda _path: list(links)),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    ), clock


def test_wildcard_process_owned_listener_is_resolved():
    resolver, _clock = _resolver(tables=[HEADER + _tcp("00000000", 43123, 100)])

    assert resolver.resolve(process_id=4321) == 43123


def test_exact_non_loopback_listener_is_resolved():
    resolver, _clock = _resolver(tables=[HEADER + _tcp("B944A8C0", 42000, 100)])

    assert resolver.resolve(process_id=4321) == 42000


def test_loopback_control_websocket_is_excluded_from_lan_listener():
    resolver, _clock = _resolver(
        tables=[
            HEADER
            + _tcp("0100007F", 43123, 100)
            + _tcp("00000000", 42000, 101)
        ],
        links={"3": "socket:[100]", "4": "socket:[101]"},
    )

    assert resolver.resolve(process_id=4321) == 42000


def test_unrelated_valid_tcp_state_outside_old_allowlist_is_ignored():
    resolver, _clock = _resolver(
        tables=[
            HEADER
            + _tcp("00000000", 41000, 100, state="FE")
            + _tcp("00000000", 42000, 101)
        ],
        links={"3": "socket:[100]", "4": "socket:[101]"},
    )

    assert resolver.resolve(process_id=4321) == 42000


def test_duplicate_owned_listener_rows_for_same_port_resolve_once():
    resolver, _clock = _resolver(
        tables=[
            HEADER
            + _tcp("00000000", 42000, 100)
            + _tcp("B944A8C0", 42000, 101)
        ],
        links={"3": "socket:[100]", "4": "socket:[101]"},
    )

    assert resolver.resolve(process_id=4321) == 42000


def test_unowned_listener_is_ignored():
    resolver, clock = _resolver(
        tables=[HEADER + _tcp("00000000", 42000, 999)],
    )

    with pytest.raises(SpotifySoloistListenerResolutionError):
        resolver.resolve(process_id=4321)
    assert clock.sleeps


def test_multiple_qualifying_listeners_fail_closed_without_polling():
    resolver, clock = _resolver(
        tables=[
            HEADER
            + _tcp("00000000", 42000, 100)
            + _tcp("B944A8C0", 42001, 101)
        ],
        links={"3": "socket:[100]", "4": "socket:[101]"},
    )

    with pytest.raises(SpotifySoloistListenerResolutionError):
        resolver.resolve(process_id=4321)
    assert clock.sleeps == []


def test_listener_appearance_is_polled_with_bounded_sleep():
    resolver, clock = _resolver(
        tables=[HEADER, HEADER + _tcp("00000000", 42000, 100)],
    )

    assert resolver.resolve(process_id=4321) == 42000
    assert clock.sleeps == [0.05]


def test_pid_must_remain_live_after_table_resolution():
    calls = {"count": 0}

    def listdir(_path):
        calls["count"] += 1
        if calls["count"] > 1:
            raise FileNotFoundError
        return ["3"]

    resolver, _clock = _resolver(
        tables=[HEADER + _tcp("00000000", 42000, 100)],
        listdir=listdir,
    )

    with pytest.raises(SpotifySoloistListenerResolutionError):
        resolver.resolve(process_id=4321)


@pytest.mark.parametrize(
    "table",
    [
        "",
        "bad header\n",
        HEADER + "short\n",
        HEADER + _tcp("GG000000", 42000, 100),
        HEADER + _tcp("00000000", 0, 100),
        HEADER + _tcp("00000000", 42000, 100, state="GZ"),
    ],
)
def test_malformed_proc_tcp_fails_closed(table):
    resolver, _clock = _resolver(tables=[table])

    with pytest.raises(SpotifySoloistListenerResolutionError):
        resolver.resolve(process_id=4321)


@pytest.mark.parametrize("process_id", [0, -1, True, "12"])
def test_invalid_pid_is_rejected(process_id):
    resolver, _clock = _resolver(tables=[HEADER])

    with pytest.raises(SpotifySoloistListenerResolutionError):
        resolver.resolve(process_id=process_id)


def test_source_avoids_cmdline_and_external_process_tools():
    source = Path(
        sys.modules[SpotifySoloistLanListenerResolver.__module__].__file__
    ).read_text(encoding="utf-8").lower()
    for forbidden in (
        "/cmdline",
        "subprocess.",
        "os.system",
        "shell=true",
        '"lsof"',
        '"fuser"',
        '"ss"',
        '"ps"',
    ):
        assert forbidden not in source
