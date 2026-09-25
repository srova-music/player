import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services.spotify_endpoint_network_access import (  # noqa: E402
    SpotifyEndpointNetworkAccess,
    SpotifyEndpointNetworkAccessError,
)
from services.spotify_firewall_manager import FirewallClassification  # noqa: E402
from services.spotify_lan_network_resolver import SpotifyLanNetwork  # noqa: E402


class Firewall:
    def __init__(self, classification=FirewallClassification.UFW_ACTIVE):
        self.classification = classification
        self.events = []
        self.lease_active = False
        self.fail_inspect = False
        self.fail_release = False

    def inspect(self):
        self.events.append("inspect")
        if self.fail_inspect:
            raise RuntimeError("private firewall detail")
        return self.classification

    def cleanup_stale(self):
        self.events.append("cleanup")
        self.lease_active = False
        return True

    def prepare(self, **lease):
        self.events.append(("prepare", lease))
        changed = not self.lease_active
        self.lease_active = True
        return changed

    def release(self):
        self.events.append("release")
        if self.fail_release:
            raise RuntimeError("private release detail")
        changed = self.lease_active
        self.lease_active = False
        return changed

    def status_snapshot(self):
        self.events.append("status")
        return {
            "classification": self.classification.value,
            "compatible": True,
            "helper_required": True,
            "lease_active": self.lease_active,
            "error": False,
        }


class Resolver:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def resolve(self, **_kwargs):
        self.calls += 1
        return self.value


class SequencedSupervisor:
    def __init__(self, *values):
        self.values = list(values)
        self.reads = 0

    @property
    def process_id(self):
        value = self.values[min(self.reads, len(self.values) - 1)]
        self.reads += 1
        if isinstance(value, Exception):
            raise value
        return value


def _access(classification=FirewallClassification.UFW_ACTIVE):
    firewall = Firewall(classification)
    network = Resolver(SpotifyLanNetwork("enp2s0", "192.168.50.0/24", "192.168.50.10"))
    listener = Resolver(43123)
    soloist = SimpleNamespace(process_id=4321)
    access = SpotifyEndpointNetworkAccess(
        firewall_manager=firewall,
        lan_network_resolver=network,
        listener_resolver=listener,
        soloist_supervisor=soloist,
    )
    return access, firewall, network, listener, soloist


@pytest.mark.parametrize(
    "classification",
    [FirewallClassification.NO_FIREWALL, FirewallClassification.UFW_INACTIVE],
)
def test_compatible_firewall_noop_never_resolves_listener(classification):
    access, firewall, network, listener, _soloist = _access(classification)

    assert access.preflight() is False
    assert access.activate() is False
    assert firewall.events == ["inspect", "inspect"]
    assert network.calls == 0
    assert listener.calls == 0


def test_active_ufw_preflight_cleans_stale_owned_rules_once():
    access, firewall, _network, _listener, _soloist = _access()

    assert access.preflight() is True
    assert firewall.events == ["inspect", "cleanup"]


def test_active_ufw_opens_exact_dynamic_lease_and_verifies_it():
    access, firewall, network, listener, _soloist = _access()
    soloist = SequencedSupervisor(4321, 4321)
    access._soloist_supervisor = soloist
    access.preflight()
    firewall.events.clear()

    assert access.activate() is True
    assert firewall.events == [
        "inspect",
        (
            "prepare",
            {
                "interface": "enp2s0",
                "source_cidr": "192.168.50.0/24",
                "destination_ipv4": "192.168.50.10",
                "port": 43123,
            },
        ),
        "status",
    ]
    assert network.calls == 1
    assert listener.calls == 1
    assert soloist.reads == 2
    assert access.status_snapshot() == {"lease_active": True}


@pytest.mark.parametrize(
    "replacement",
    [None, 9876, True, RuntimeError("private PID 4321 inspection detail")],
    ids=["disappears", "changes", "invalid", "inspection-fails"],
)
def test_pid_revalidation_failure_never_prepares_or_exposes_pid(replacement):
    access, firewall, _network, listener, _soloist = _access()
    soloist = SequencedSupervisor(4321, replacement)
    access._soloist_supervisor = soloist

    with pytest.raises(SpotifyEndpointNetworkAccessError) as raised:
        access.activate()

    assert listener.calls == 1
    assert soloist.reads == 2
    assert not any(
        isinstance(event, tuple) and event[0] == "prepare"
        for event in firewall.events
    )
    assert "4321" not in str(raised.value)
    assert "9876" not in str(raised.value)
    snapshot = access.status_snapshot()
    assert set(snapshot) == {"lease_active"}
    assert "4321" not in repr(snapshot)
    assert "9876" not in repr(snapshot)


def test_repeated_activation_is_idempotent_for_same_endpoint():
    access, firewall, _network, _listener, _soloist = _access()
    access.preflight()
    assert access.activate() is True

    assert access.preflight() is False
    assert access.activate() is False
    assert [event for event in firewall.events if event == "cleanup"] == ["cleanup"]


def test_dynamic_listener_change_delegates_exact_lease_replacement():
    access, firewall, _network, listener, _soloist = _access()
    access.preflight()
    access.activate()
    listener.value = 44000

    access.activate()

    prepare_calls = [event for event in firewall.events if isinstance(event, tuple)]
    assert prepare_calls[-1][1]["port"] == 44000


@pytest.mark.parametrize(
    "classification",
    [FirewallClassification.UNSUPPORTED_FIREWALL, FirewallClassification.UNKNOWN],
)
def test_incompatible_firewall_fails_closed(classification):
    access, _firewall, _network, _listener, _soloist = _access(classification)

    with pytest.raises(SpotifyEndpointNetworkAccessError):
        access.preflight()


def test_missing_live_process_fails_before_proc_resolution():
    access, _firewall, _network, listener, soloist = _access()
    soloist.process_id = None

    with pytest.raises(SpotifyEndpointNetworkAccessError):
        access.activate()
    assert listener.calls == 0


def test_release_is_idempotent_and_sanitized():
    access, firewall, _network, _listener, _soloist = _access()
    access.preflight()
    access.activate()

    assert access.release() is True
    assert access.release() is False
    firewall.fail_release = True
    with pytest.raises(SpotifyEndpointNetworkAccessError) as raised:
        access.release()
    assert "private" not in str(raised.value)


def test_status_contains_no_network_identity_or_port():
    access, _firewall, _network, _listener, _soloist = _access()

    assert set(access.status_snapshot()) == {"lease_active"}
