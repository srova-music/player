import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import subprocess
from pathlib import Path
from unittest import mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "packaging/network/srova-spotify-firewall-helper"
loader = importlib.machinery.SourceFileLoader(
    "srova_spotify_firewall_helper", str(HELPER_PATH)
)
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

UFW = "/usr/sbin/ufw"
LEASE = {
    "interface": "enp2s0",
    "source_cidr": "192.168.50.0/24",
    "destination_ipv4": "192.168.50.10",
    "port": 43123,
}


class FakeUfw:
    def __init__(self, *, active=True):
        self.active = active
        self.entries = ["22/tcp ALLOW IN Anywhere # USER-SSH"]
        self.calls = []

    def add_owned(self, marker):
        self.entries.append(f"43123/tcp ALLOW IN 192.168.50.0/24 # {marker}")

    def run(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if argv == [UFW, "status"]:
            state = "active" if self.active else "inactive"
            return subprocess.CompletedProcess(argv, 0, f"Status: {state}\n", "")
        if argv == [UFW, "status", "numbered"]:
            lines = [f"Status: {'active' if self.active else 'inactive'}"]
            lines.extend(
                f"[ {number}] {entry}"
                for number, entry in enumerate(self.entries, start=1)
            )
            return subprocess.CompletedProcess(argv, 0, "\n".join(lines) + "\n", "")
        if len(argv) >= 2 and argv[1] == "allow":
            self.add_owned(argv[-1])
            return subprocess.CompletedProcess(argv, 0, "Rule added\n", "")
        if argv[1:3] == ["--force", "delete"]:
            self.entries.pop(int(argv[3]) - 1)
            return subprocess.CompletedProcess(argv, 0, "Rule deleted\n", "")
        raise AssertionError(argv)


@pytest.fixture
def fake_ufw():
    fake = FakeUfw()
    with mock.patch.object(helper, "select_ufw", return_value=UFW), mock.patch.object(
        helper, "run_command", side_effect=fake.run
    ):
        yield fake


def test_invalid_action_is_rejected():
    with pytest.raises(helper.HelperError, match="invalid action"):
        helper.dispatch("arbitrary", {})


def test_execution_requires_root_before_reading_request(capsys):
    with mock.patch.object(helper.os, "geteuid", return_value=1000), mock.patch.object(
        helper, "read_stdin_json"
    ) as reader:
        assert helper.main(["open"]) == 1
    reader.assert_not_called()
    response = json.loads(capsys.readouterr().out)
    assert response == {"ok": False, "error": "firewall helper operation failed"}


def test_oversized_stdin_is_rejected():
    with pytest.raises(helper.HelperError, match="large"):
        helper.read_stdin_json(io.BytesIO(b"x" * (helper.MAX_STDIN_BYTES + 1)))


@pytest.mark.parametrize("raw", [b"{broken", b"[1,2]", b'"text"'])
def test_malformed_and_non_object_json_is_rejected(raw):
    with pytest.raises(helper.HelperError):
        helper.read_stdin_json(io.BytesIO(raw))


@pytest.mark.parametrize(
    "interface", ["lo", "bad iface", "eth0;id", "-bad", "eth0\n", "x" * 16]
)
def test_unsafe_or_loopback_interface_is_rejected(interface):
    with pytest.raises(helper.HelperError):
        helper.validate_lease({**LEASE, "interface": interface})


@pytest.mark.parametrize(
    "source", ["bad", "192.168.50.7/24", "0.0.0.0/0", "::/64", "127.0.0.0/8"]
)
def test_invalid_non_lan_or_non_ipv4_source_is_rejected(source):
    with pytest.raises(helper.HelperError):
        helper.validate_lease({**LEASE, "source_cidr": source})


@pytest.mark.parametrize(
    "destination", ["bad", "::1", "192.168.51.10", "127.0.0.1"]
)
def test_invalid_non_ipv4_or_outside_destination_is_rejected(destination):
    with pytest.raises(helper.HelperError):
        helper.validate_lease({**LEASE, "destination_ipv4": destination})


@pytest.mark.parametrize("port", [1, 65535])
def test_port_boundaries_are_accepted(port):
    assert helper.validate_lease({**LEASE, "port": port})["port"] == port


@pytest.mark.parametrize("port", [0, 65536, -1, True, False, "43123"])
def test_invalid_ports_including_bool_are_rejected(port):
    with pytest.raises(helper.HelperError):
        helper.validate_lease({**LEASE, "port": port})


@pytest.mark.parametrize(
    "extra", [{"flags": ["--force"]}, {"comment": "mine"}, {"protocol": "udp"}]
)
def test_caller_cannot_supply_flags_comment_or_protocol(extra):
    with pytest.raises(helper.HelperError, match="structure"):
        helper.validate_lease({**LEASE, **extra})


def test_only_trusted_absolute_ufw_paths_are_selected():
    seen = []

    def exists(path):
        seen.append(path)
        return path == "/sbin/ufw"

    assert helper.select_ufw(exists) == "/sbin/ufw"
    assert seen == ["/usr/sbin/ufw", "/sbin/ufw"]


@pytest.mark.parametrize(
    ("output", "expected"),
    [("Status: active\n", True), ("Status: inactive\n", False)],
)
def test_status_parses_only_active_and_inactive(output, expected):
    result = subprocess.CompletedProcess([], 0, output, "")
    with mock.patch.object(helper, "run_command", return_value=result):
        assert helper.ufw_status(UFW) is expected


def test_malformed_status_is_rejected():
    result = subprocess.CompletedProcess([], 0, "Status: uncertain\n", "")
    with mock.patch.object(helper, "run_command", return_value=result), pytest.raises(
        helper.HelperError, match="unknown"
    ):
        helper.ufw_status(UFW)


def test_status_reports_ufw_unavailable_without_command():
    with mock.patch.object(helper, "select_ufw", return_value=None), mock.patch.object(
        helper, "run_command"
    ) as runner:
        assert helper.action_status({}) == {
            "ok": True, "available": False, "active": False
        }
    runner.assert_not_called()


def test_open_refuses_inactive_ufw():
    fake = FakeUfw(active=False)
    with mock.patch.object(helper, "select_ufw", return_value=UFW), mock.patch.object(
        helper, "run_command", side_effect=fake.run
    ), pytest.raises(helper.HelperError, match="inactive"):
        helper.action_open(LEASE)
    assert not any("allow" in call for call in fake.calls)


def test_open_uses_exact_ipv4_tcp_argv_and_generated_comment(fake_ufw):
    result = helper.action_open(LEASE)
    assert result == {"ok": True, "changed": True, "owned": True}
    allow = next(call for call in fake_ufw.calls if "allow" in call)
    marker = helper.ownership_marker(helper.validate_lease(LEASE))
    assert allow == [
        UFW, "allow", "in", "on", "enp2s0", "from", "192.168.50.0/24",
        "to", "192.168.50.10", "port", "43123", "proto", "tcp", "comment",
        marker,
    ]
    assert marker.startswith("SROVA-SPOTIFY-")
    assert "udp" not in allow
    assert "5353" not in allow
    assert ":" not in LEASE["destination_ipv4"]
    assert "-" not in str(LEASE["port"])


def test_open_is_idempotent_for_identical_owned_rule(fake_ufw):
    marker = helper.ownership_marker(helper.validate_lease(LEASE))
    fake_ufw.add_owned(marker)
    assert helper.action_open(LEASE) == {
        "ok": True, "changed": False, "owned": True
    }
    assert not any("allow" in call for call in fake_ufw.calls)


def test_open_removes_stale_owned_rule_but_not_unrelated(fake_ufw):
    fake_ufw.add_owned("SROVA-SPOTIFY-0000000000000000")
    helper.action_open(LEASE)
    assert fake_ufw.entries[0].endswith("# USER-SSH")
    assert not any("0000000000000000" in entry for entry in fake_ufw.entries)


def test_user_rule_containing_prefix_as_non_comment_is_not_owned():
    output = (
        "Status: active\n"
        "[ 1] SROVA-SPOTIFY-0000000000000000/tcp ALLOW IN Anywhere # USER\n"
    )
    result = subprocess.CompletedProcess([], 0, output, "")
    with mock.patch.object(helper, "run_command", return_value=result):
        assert helper.numbered_rules(UFW) == []


def test_close_fails_closed_if_ufw_became_inactive():
    fake = FakeUfw(active=False)
    fake.add_owned(helper.ownership_marker(helper.validate_lease(LEASE)))
    with mock.patch.object(helper, "select_ufw", return_value=UFW), mock.patch.object(
        helper, "run_command", side_effect=fake.run
    ), pytest.raises(helper.HelperError, match="not active"):
        helper.action_close(LEASE)
    assert not any("delete" in call for call in fake.calls)


def test_close_removes_only_exact_owned_rule(fake_ufw):
    exact = helper.ownership_marker(helper.validate_lease(LEASE))
    fake_ufw.add_owned("SROVA-SPOTIFY-0000000000000000")
    fake_ufw.add_owned(exact)
    assert helper.action_close(LEASE)["changed"] is True
    assert fake_ufw.entries[0].endswith("# USER-SSH")
    assert any("0000000000000000" in entry for entry in fake_ufw.entries)
    assert not any(exact in entry for entry in fake_ufw.entries)


def test_close_absent_is_idempotent(fake_ufw):
    assert helper.action_close(LEASE) == {
        "ok": True, "changed": False, "owned": False
    }
    assert not any("delete" in call for call in fake_ufw.calls)


def test_cleanup_removes_only_owned_rules_in_descending_order(fake_ufw):
    fake_ufw.add_owned("SROVA-SPOTIFY-0000000000000001")
    fake_ufw.add_owned("SROVA-SPOTIFY-0000000000000002")
    assert helper.action_cleanup({})["changed"] is True
    deletes = [int(call[-1]) for call in fake_ufw.calls if "delete" in call]
    assert deletes == sorted(deletes, reverse=True)
    assert fake_ufw.entries == ["22/tcp ALLOW IN Anywhere # USER-SSH"]


def _fake_stat(mode=stat.S_IFREG | 0o600, uid=0):
    result = mock.Mock()
    result.st_mode = mode
    result.st_uid = uid
    return result


def test_lock_uses_nofollow_and_private_mode(tmp_path):
    lock = tmp_path / "spotify.lock"
    real_open = os.open
    calls = []

    def recording_open(path, flags, mode):
        calls.append((path, flags, mode))
        return real_open(path, flags, mode)

    with mock.patch.object(helper, "LOCK_FILE", lock), mock.patch.object(
        helper.os, "open", side_effect=recording_open
    ), mock.patch.object(helper.os, "fstat", return_value=_fake_stat()):
        with helper.operation_lock(timeout=0.1):
            pass
    assert calls[0][2] == 0o600
    if hasattr(os, "O_NOFOLLOW"):
        assert calls[0][1] & os.O_NOFOLLOW


@pytest.mark.parametrize(
    "info",
    [_fake_stat(uid=1000), _fake_stat(mode=stat.S_IFDIR | 0o600, uid=0)],
)
def test_lock_rejects_non_root_owner_and_non_regular_file(tmp_path, info):
    lock = tmp_path / "spotify.lock"
    with mock.patch.object(helper, "LOCK_FILE", lock), mock.patch.object(
        helper.os, "fstat", return_value=info
    ), pytest.raises(helper.HelperError, match="unsafe"):
        with helper.operation_lock(timeout=0.01):
            pass


def test_symlink_lock_is_rejected(tmp_path):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW unavailable")
    target = tmp_path / "target"
    target.write_text("unchanged", encoding="utf-8")
    lock = tmp_path / "spotify.lock"
    lock.symlink_to(target)
    with mock.patch.object(helper, "LOCK_FILE", lock), pytest.raises(
        helper.HelperError, match="safely"
    ):
        with helper.operation_lock(timeout=0.01):
            pass
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_subprocess_is_shell_free_and_bounded():
    completed = subprocess.CompletedProcess([], 0, "", "")
    with mock.patch.object(helper.subprocess, "run", return_value=completed) as runner:
        helper.run_command([UFW, "status"])
    kwargs = runner.call_args.kwargs
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == helper.COMMAND_TIMEOUT
    assert helper.COMMAND_TIMEOUT > 0


def test_main_outputs_structured_json_on_success(capsys):
    response = {"ok": True, "available": False, "active": False}
    with mock.patch.object(helper, "require_root"), mock.patch.object(
        helper, "read_stdin_json", return_value={}
    ), mock.patch.object(helper, "operation_lock", return_value=contextlib.nullcontext()), mock.patch.object(
        helper, "dispatch", return_value=response
    ):
        assert helper.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out) == response


def test_errors_are_bounded_and_do_not_leak_exception_text(capsys):
    private = "private-firewall-command-output-never-leak"
    with mock.patch.object(helper, "require_root"), mock.patch.object(
        helper, "read_stdin_json", return_value={}
    ), mock.patch.object(helper, "operation_lock", return_value=contextlib.nullcontext()), mock.patch.object(
        helper, "dispatch", side_effect=RuntimeError(private)
    ):
        assert helper.main(["status"]) == 1
    output = capsys.readouterr().out
    assert private not in output
    assert len(output) < 128
    assert json.loads(output)["ok"] is False


def test_helper_source_has_fixed_actions_and_no_shell_or_raw_firewall_tools():
    source = HELPER_PATH.read_text(encoding="utf-8")
    assert set(helper._ACTIONS) == {"status", "open", "close", "cleanup"}
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "/usr/sbin/nft" not in source
    assert "/usr/sbin/iptables" not in source
