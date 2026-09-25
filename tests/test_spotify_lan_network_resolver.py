import socket
import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services.spotify_lan_network_resolver import (  # noqa: E402
    SpotifyLanNetworkResolutionError,
    SpotifyLanNetworkResolver,
)


HEADER = "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"


class FakeSocket:
    def __init__(self):
        self.closed = False

    def fileno(self):
        return 9

    def close(self):
        self.closed = True


def _route(interface, metric=100, destination="00000000", mask="00000000"):
    return f"{interface} {destination} 0101A8C0 0003 0 0 {metric} {mask} 0 0 0\n"


def _resolver(route_text, *, address="192.168.68.185", netmask="255.255.255.0"):
    descriptor = FakeSocket()

    def ioctl(_fd, request, _payload):
        value = address if request == SpotifyLanNetworkResolver.SIOCGIFADDR else netmask
        return b"\0" * 20 + socket.inet_aton(value) + b"\0" * 8

    resolver = SpotifyLanNetworkResolver(
        read_text=lambda _path: route_text,
        socket_factory=lambda *_args: descriptor,
        ioctl=ioctl,
    )
    return resolver, descriptor


def test_lowest_metric_main_default_route_is_exact_canonical_lan():
    resolver, descriptor = _resolver(
        HEADER
        + _route("enp9s0", 500)
        + _route("enx00e04c680038", 100)
        + _route("tailscale0", 5, "6400000A", "FF0000FF")
    )

    resolved = resolver.resolve()

    assert resolved.interface == "enx00e04c680038"
    assert resolved.source_cidr == "192.168.68.0/24"
    assert resolved.destination_ipv4 == "192.168.68.185"
    assert descriptor.closed is True


def test_tailscale_secondary_interface_cannot_override_main_default():
    resolver, _descriptor = _resolver(
        HEADER
        + _route("enp2s0", 100)
        + _route("tailscale0", 0, "00000064", "000000FF")
    )

    assert resolver.resolve().interface == "enp2s0"


def test_duplicate_same_interface_best_route_is_deterministic():
    resolver, _descriptor = _resolver(
        HEADER + _route("enp2s0", 100) + _route("enp2s0", 100)
    )

    assert resolver.resolve().interface == "enp2s0"


def test_equal_best_distinct_interfaces_are_rejected():
    resolver, _descriptor = _resolver(
        HEADER + _route("enp2s0", 100) + _route("wlan0", 100)
    )

    with pytest.raises(SpotifyLanNetworkResolutionError):
        resolver.resolve()


@pytest.mark.parametrize(
    "routes",
    [
        "",
        "bad header\n",
        HEADER + "short row\n",
        HEADER + _route("lo", 1),
        HEADER + _route("bad iface", 1),
        HEADER + _route("enp2s0", -1),
        HEADER + _route("enp2s0", 1, "nothex"),
    ],
)
def test_malformed_or_unsafe_routes_fail_closed(routes):
    resolver, _descriptor = _resolver(routes)

    with pytest.raises(SpotifyLanNetworkResolutionError):
        resolver.resolve()


@pytest.mark.parametrize(
    ("address", "netmask"),
    [
        ("127.0.0.1", "255.0.0.0"),
        ("0.0.0.0", "255.255.255.0"),
        ("224.0.0.1", "255.255.255.0"),
        ("192.168.1.0", "255.255.255.0"),
        ("192.168.1.255", "255.255.255.0"),
        ("192.168.1.5", "0.0.0.0"),
    ],
)
def test_invalid_interface_address_or_network_fails_closed(address, netmask):
    resolver, _descriptor = _resolver(
        HEADER + _route("enp2s0"),
        address=address,
        netmask=netmask,
    )

    with pytest.raises(SpotifyLanNetworkResolutionError):
        resolver.resolve()


def test_constructor_is_dormant_and_relative_route_path_is_rejected():
    calls = []
    SpotifyLanNetworkResolver(read_text=lambda path: calls.append(path))
    assert calls == []

    with pytest.raises(SpotifyLanNetworkResolutionError):
        SpotifyLanNetworkResolver(route_path="proc/net/route")
