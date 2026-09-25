import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.spotify_firewall_manager import (  # noqa: E402
    FirewallClassification,
    SpotifyFirewallCompatibilityError,
    SpotifyFirewallManager,
)


UFW = "/usr/sbin/ufw"
CONFIG = "/etc/ufw/ufw.conf"
HELPER = "/usr/lib/srova/srova-spotify-firewall-helper"
SUDO = "/usr/bin/sudo"
FIREWALLD = "/usr/bin/firewall-cmd"
LEASE = {
    "interface": "enp2s0",
    "source_cidr": "192.168.50.0/24",
    "destination_ipv4": "192.168.50.10",
    "port": 43123,
}


class FakeEnvironment:
    def __init__(self, *, enabled="yes", active=True, ufw=True):
        self.paths = {HELPER, SUDO}
        if ufw:
            self.paths.update({UFW, CONFIG})
        self.config = f"ENABLED={enabled}\n"
        self.active = active
        self.calls = []
        self.responses = {}

    def exists(self, path):
        return path in self.paths

    def read(self, path):
        assert path == CONFIG
        return self.config

    def run(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if argv[0] == FIREWALLD:
            return subprocess.CompletedProcess(argv, 0, "running\n", "")
        action = argv[-1]
        response = self.responses.get(action)
        if response is None:
            if action == "status":
                response = {
                    "ok": True,
                    "available": True,
                    "active": self.active,
                }
            else:
                response = {"ok": True, "changed": True}
        if isinstance(response, subprocess.CompletedProcess):
            return response
        output = response if isinstance(response, str) else json.dumps(response)
        return subprocess.CompletedProcess(argv, 0, output, "")

    def manager(self):
        return SpotifyFirewallManager(
            path_exists=self.exists,
            read_text=self.read,
            command_runner=self.run,
        )

    @property
    def helper_actions(self):
        return [argv[-1] for argv, _kwargs in self.calls if argv[0] == SUDO]


def test_no_ufw_binary_or_config_is_no_firewall_and_never_uses_helper():
    env = FakeEnvironment(ufw=False)
    manager = env.manager()
    assert manager.inspect() is FirewallClassification.NO_FIREWALL
    assert manager.prepare(**LEASE) is False
    assert env.calls == []


def test_ufw_enabled_no_is_inactive_and_never_uses_helper():
    env = FakeEnvironment(enabled="no")
    manager = env.manager()
    assert manager.inspect() is FirewallClassification.UFW_INACTIVE
    assert manager.prepare(**LEASE) is False
    assert env.calls == []


@pytest.mark.parametrize(
    "text",
    [" ENABLED = YES \n", "enabled=No\n", "# header\nEnAbLeD = yes # set\n"],
)
def test_config_parsing_is_case_and_whitespace_safe(text):
    env = FakeEnvironment()
    env.config = text
    classification = env.manager().inspect()
    expected = (
        FirewallClassification.UFW_INACTIVE
        if "no" in text.lower()
        else FirewallClassification.UFW_ACTIVE
    )
    assert classification is expected


@pytest.mark.parametrize(
    "text",
    ["ENABLED=maybe\n", "OTHER=yes\n", "ENABLED=yes\nENABLED=no\n", ""],
)
def test_malformed_ufw_config_is_unknown_without_helper(text):
    env = FakeEnvironment()
    env.config = text
    assert env.manager().inspect() is FirewallClassification.UNKNOWN
    assert env.calls == []


def test_enabled_yes_uses_status_for_runtime_confirmation():
    env = FakeEnvironment(active=True)
    assert env.manager().inspect() is FirewallClassification.UFW_ACTIVE
    assert env.helper_actions == ["status"]
    argv, kwargs = env.calls[0]
    assert argv == [SUDO, "-n", HELPER, "status"]
    assert json.loads(kwargs["input"]) == {}
    assert kwargs["shell"] is False


def test_helper_inactive_runtime_means_no_open_mutation():
    env = FakeEnvironment(active=False)
    manager = env.manager()
    assert manager.prepare(**LEASE) is False
    assert env.helper_actions == ["status"]


@pytest.mark.parametrize("bad", ["not-json", "[]", '{"ok":"true"}'])
def test_malformed_or_non_boolean_helper_response_is_rejected(bad):
    env = FakeEnvironment()
    env.responses["status"] = bad
    with pytest.raises(SpotifyFirewallCompatibilityError, match="invalid"):
        env.manager().inspect()


def test_helper_missing_for_enabled_candidate_is_precise_error():
    env = FakeEnvironment()
    env.paths.remove(HELPER)
    with pytest.raises(SpotifyFirewallCompatibilityError, match="unavailable"):
        env.manager().inspect()


def test_sudo_missing_for_enabled_candidate_is_precise_error():
    env = FakeEnvironment()
    env.paths.remove(SUDO)
    with pytest.raises(SpotifyFirewallCompatibilityError, match="privilege"):
        env.manager().inspect()


def test_sudo_nonzero_for_enabled_candidate_is_precise_error():
    env = FakeEnvironment()
    env.responses["status"] = subprocess.CompletedProcess([], 1, "", "private")
    with pytest.raises(SpotifyFirewallCompatibilityError, match="failed") as error:
        env.manager().inspect()
    assert "private" not in str(error.value)


def test_firewalld_active_is_unsupported_without_ufw_helper_call():
    env = FakeEnvironment()
    env.paths.add(FIREWALLD)
    assert env.manager().inspect() is FirewallClassification.UNSUPPORTED_FIREWALL
    assert env.helper_actions == []


def test_nft_and_iptables_binary_presence_does_not_change_no_firewall():
    env = FakeEnvironment(ufw=False)
    env.paths.update({"/usr/sbin/nft", "/usr/sbin/iptables"})
    assert env.manager().inspect() is FirewallClassification.NO_FIREWALL


def test_valid_exact_ipv4_lease_opens_with_structured_json_only():
    env = FakeEnvironment()
    assert env.manager().prepare(**LEASE) is True
    assert env.helper_actions == ["status", "open"]
    argv, kwargs = env.calls[-1]
    assert argv == [SUDO, "-n", HELPER, "open"]
    assert json.loads(kwargs["input"]) == LEASE


@pytest.mark.parametrize(
    "interface", ["lo", "bad iface", "-bad", "eth0;id", "eth0\n", "x" * 16, 4]
)
def test_interface_validation_rejects_unsafe_and_loopback(interface):
    env = FakeEnvironment(ufw=False)
    with pytest.raises(ValueError):
        env.manager().prepare(**{**LEASE, "interface": interface})
    assert env.calls == []


@pytest.mark.parametrize(
    "source", ["bad", "192.168.1.7/24", "::/64", "0.0.0.0/0", "127.0.0.0/8"]
)
def test_source_cidr_validation(source):
    with pytest.raises(ValueError):
        FakeEnvironment(ufw=False).manager().prepare(
            **{**LEASE, "source_cidr": source}
        )


@pytest.mark.parametrize(
    "destination", ["bad", "::1", "192.168.51.10", "127.0.0.1"]
)
def test_destination_ipv4_validation(destination):
    with pytest.raises(ValueError):
        FakeEnvironment(ufw=False).manager().prepare(
            **{**LEASE, "destination_ipv4": destination}
        )


@pytest.mark.parametrize("port", [1, 65535])
def test_port_boundaries_are_accepted(port):
    assert FakeEnvironment(ufw=False).manager().prepare(
        **{**LEASE, "port": port}
    ) is False


@pytest.mark.parametrize("port", [0, 65536, -1, True, False, "43123"])
def test_invalid_ports_are_rejected(port):
    with pytest.raises(ValueError):
        FakeEnvironment(ufw=False).manager().prepare(**{**LEASE, "port": port})


def test_repeated_identical_open_is_idempotent():
    env = FakeEnvironment()
    manager = env.manager()
    assert manager.prepare(**LEASE) is True
    assert manager.prepare(**LEASE) is False
    assert env.helper_actions.count("open") == 1


def test_release_is_idempotent():
    env = FakeEnvironment()
    manager = env.manager()
    assert manager.release() is False
    manager.prepare(**LEASE)
    assert manager.release() is True
    assert manager.release() is False
    assert env.helper_actions.count("close") == 1


def test_different_lease_closes_old_before_opening_new():
    env = FakeEnvironment()
    manager = env.manager()
    manager.prepare(**LEASE)
    manager.prepare(**{**LEASE, "port": 43124})
    assert env.helper_actions == ["status", "open", "status", "close", "open"]
    assert json.loads(env.calls[-2][1]["input"])["port"] == 43123
    assert json.loads(env.calls[-1][1]["input"])["port"] == 43124


def test_cleanup_only_mutates_confirmed_active_ufw():
    active = FakeEnvironment()
    assert active.manager().cleanup() is True
    assert active.helper_actions == ["status", "cleanup"]
    inactive = FakeEnvironment(enabled="no")
    assert inactive.manager().cleanup() is False
    assert inactive.helper_actions == []


def test_status_snapshot_has_no_paths_payloads_or_raw_output():
    env = FakeEnvironment()
    snapshot = env.manager().status_snapshot()
    assert set(snapshot) == {
        "classification", "compatible", "helper_required", "lease_active", "error"
    }
    rendered = json.dumps(snapshot)
    assert "sudo" not in rendered
    assert "192.168" not in rendered
    assert HELPER not in rendered


def test_no_firewall_and_inactive_succeed_without_sudo_or_helper():
    for env in (FakeEnvironment(ufw=False), FakeEnvironment(enabled="no")):
        env.paths.discard(SUDO)
        env.paths.discard(HELPER)
        assert env.manager().prepare(**LEASE) is False
        assert env.calls == []


def test_manager_source_has_no_locked_component_or_raw_firewall_mutation():
    source = (SRC / "services/spotify_firewall_manager.py").read_text(encoding="utf-8")
    forbidden = (
        "spotify_coordinator", "spotify_orchestrator", "spotify_soloist_supervisor",
        "spotify_soloist_event_observer", "spotify_runtime_supervisor",
        "spotify_pipewire_dac_resolver", "spotify_alsa_pcm_verifier",
        "main_headless", "os.system", "shell=True",
    )
    assert not any(item in source for item in forbidden)
    assert not re.search(r"(?:nft|iptables).*(?:add|insert|delete)", source, re.I)


def test_packaging_contains_narrow_helper_and_preserves_network_helper():
    script = (ROOT / "packaging/arm64/build_rc1_deb.sh").read_text(encoding="utf-8")
    install_source = "$EXPORT_ROOT/packaging/network/srova-spotify-firewall-helper"
    assert "install -m 0755" in script
    assert install_source in script
    assert "$TREE/usr/lib/srova/srova-spotify-firewall-helper" in script
    assert "$TREE/etc/sudoers.d/srova-spotify-firewall" in script
    assert "srova ALL=(root) NOPASSWD: /usr/lib/srova/srova-spotify-firewall-helper" in script
    assert 'chmod 0440 "$TREE/etc/sudoers.d/srova-spotify-firewall"' in script
    assert 'visudo -cf "$TREE/etc/sudoers.d/srova-spotify-firewall"' in script
    assert "srova-network-mount-helper" in script
    assert "srova-network-mounts.service" in script
    depends = next(line for line in script.splitlines() if line.startswith("Depends:"))
    assert "pipewire-bin" in depends
    assert "wireplumber" in depends
    assert all(name not in depends for name in ("ufw", "firewalld", "nftables", "iptables"))


def test_amd64_packaging_contains_spotify_firewall_helper_and_runtime_directory():
    script = (ROOT / "package.sh").read_text(encoding="utf-8")

    assert "RuntimeDirectory=srova" in script
    assert "packaging/network/srova-spotify-firewall-helper" in script
    assert "$BUILD_ROOT/usr/lib/srova/srova-spotify-firewall-helper" in script
    assert "$BUILD_ROOT/etc/sudoers.d/srova-spotify-firewall" in script
    assert (
        "srova ALL=(root) NOPASSWD: "
        "/usr/lib/srova/srova-spotify-firewall-helper"
    ) in script
    assert (
        'chmod 0755 '
        '"$BUILD_ROOT/usr/lib/srova/srova-spotify-firewall-helper"'
    ) in script
    assert (
        'chmod 0440 '
        '"$BUILD_ROOT/etc/sudoers.d/srova-spotify-firewall"'
    ) in script
    assert 'visudo -cf "$spotify_sudoers"' in script
    assert "./usr/lib/srova/srova-spotify-firewall-helper" in script
    assert "./etc/sudoers.d/srova-spotify-firewall" in script

    depends_lines = [
        line
        for line in script.splitlines()
        if line.startswith("Depends:")
    ]
    assert depends_lines
    assert all("pipewire-bin" in line for line in depends_lines)
    assert all("wireplumber" in line for line in depends_lines)
    assert all(
        all(
            name not in line
            for name in ("ufw", "firewalld", "nftables", "iptables")
        )
        for line in depends_lines
    )
