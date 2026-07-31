import json
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import network_music
from src.network_root_state import add_exact_managed_root, remove_exact_managed_root


class NetworkMusicTests(unittest.TestCase):
    @property
    def repo_root(self):
        return Path(__file__).resolve().parents[1]

    def test_parsers(self):
        nfs = "Export list for host:\n/Music 192.168.1.0/24\n/Media *\n"
        self.assertEqual(network_music.parse_showmount_exports(nfs), [{"path": "/Music"}, {"path": "/Media"}])
        smb = "Disk|Music|Lossless\nIPC|IPC$|IPC\nPrinter|HP|Printer\nDisk|ADMIN$|Admin\nDisk|Photos|\n"
        self.assertEqual(network_music.parse_smbclient_g(smb), [
            {"name": "Music", "comment": "Lossless"}, {"name": "Photos", "comment": ""}])

    def test_host_validator_blocks_option_and_command_injection(self):
        invalid = ["--help", "-A", "bad\nhost", "bad host", "nas,ro", "bad..name", "bad_label",
                   "999.1.1.1", "1.2.3", "192.168.1.999"]
        for host in invalid:
            with self.subTest(host=repr(host)), self.assertRaises(network_music.NetworkMusicError):
                network_music.validate_host(host)
        for host in ("192.168.1.20", "nas.local", "music-server.example"):
            self.assertEqual(network_music.validate_host(host), host)
        with self.assertRaisesRegex(network_music.NetworkMusicError, "IPv6"):
            network_music.validate_host("2001:db8::1")

    def test_external_share_commands_validate_host_before_running(self):
        with mock.patch.object(network_music, "_run_command") as runner:
            self.assertFalse(network_music.list_nfs_exports("--help")["ok"])
            self.assertFalse(network_music.list_smb_shares("-A")["ok"])
        runner.assert_not_called()

    def test_automatic_candidates_are_lan_shared_or_explicit_local_loopback(self):
        data = [{"addr_info": [
            {"family": "inet", "local": "8.8.8.8", "prefixlen": 24},
            {"family": "inet", "local": "192.168.68.10", "prefixlen": 24},
            {"family": "inet", "local": "100.100.20.3", "prefixlen": 24},
            {"family": "inet", "local": "127.0.0.1", "prefixlen": 8},
        ]}]
        hosts = network_music.host_candidates(ip_addr_data=data,
                                               neigh_hosts=["8.8.4.4", "192.168.68.20", "100.100.20.4"], cap=512)
        self.assertNotIn("8.8.8.8", hosts)
        self.assertNotIn("8.8.8.1", hosts)
        self.assertNotIn("8.8.4.4", hosts)
        self.assertIn("192.168.68.20", hosts)
        self.assertIn("100.100.20.4", hosts)
        self.assertIn("127.0.0.1", hosts)

    def test_discovery_caps_workers_hosts_and_absorbs_probe_errors(self):
        def connector(host, port, timeout):
            if port == 445:
                raise OSError("closed")
            return host == "192.168.1.2"
        data = network_music.discover_servers(candidates=["192.168.1.2", "192.168.1.3"],
                                               total_timeout=1, connect_timeout=.01, workers=1000,
                                               connector=connector)
        self.assertTrue(data["ok"])
        self.assertEqual(data["servers"][0]["protocols"], ["nfs"])

    def test_name_lookup_is_bounded_and_never_mutates_global_socket_timeout(self):
        with mock.patch.object(socket, "setdefaulttimeout", side_effect=AssertionError("global timeout changed")), \
                mock.patch.object(network_music, "_run_command", side_effect=subprocess.TimeoutExpired(["getent"], .1)) as runner:
            self.assertEqual(network_music._safe_name_lookup("192.168.1.2", timeout=.1), "")
        self.assertEqual(runner.call_args.kwargs["timeout"], .1)

    def test_command_runner_never_uses_shell(self):
        with mock.patch.object(network_music.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as runner:
            network_music._run_command(["ip", "-j"], timeout=1)
        self.assertIs(runner.call_args.kwargs["shell"], False)

    def test_missing_commands_and_timeouts_are_not_auth_failures(self):
        with mock.patch.object(network_music, "_run_command", side_effect=FileNotFoundError):
            self.assertIn("showmount", network_music.list_nfs_exports("nas.local")["error"])
            smb = network_music.list_smb_shares("nas.local")
            self.assertFalse(smb["auth_required"])
            self.assertIn("smbclient", smb["error"])
        with mock.patch.object(network_music, "_run_command", side_effect=subprocess.TimeoutExpired(["smbclient"], 1)):
            smb = network_music.list_smb_shares("nas.local")
            self.assertFalse(smb["auth_required"])
            self.assertIn("timed out", smb["error"])

    def test_smb_error_classification(self):
        cases = [
            ("NT_STATUS_LOGON_FAILURE", True, "Authentication"),
            ("Connection refused", False, "unreachable"),
            ("protocol negotiation failed", False, "protocol"),
        ]
        for stderr, auth, message in cases:
            proc = subprocess.CompletedProcess([], 1, "", stderr)
            with self.subTest(stderr=stderr), mock.patch.object(network_music, "_run_command", return_value=proc):
                result = network_music.list_smb_shares("nas.local", password="supersafe")
                self.assertEqual(result["auth_required"], auth)
                self.assertIn(message.lower(), result["error"].lower())
                self.assertNotIn("supersafe", result["error"])

    def test_smb_password_uses_temporary_auth_file_not_argv_and_is_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = Path(directory) / "auth"
            calls = []
            def fake_auth(username, password, domain=""):
                auth.write_text("password = secret\n", encoding="utf-8")
                return str(auth)
            def fake_run(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "Disk|Music|\n", "")
            with mock.patch.object(network_music, "_write_smb_auth_file", side_effect=fake_auth), \
                    mock.patch.object(network_music, "_run_command", side_effect=fake_run):
                result = network_music.list_smb_shares("nas.local", username="u", password="secret")
            self.assertTrue(result["ok"])
            self.assertNotIn("secret", " ".join(calls[0]))
            self.assertFalse(auth.exists())

    def test_smb_password_printable_spaces_are_preserved_exactly(self):
        password = "  secret with spaces  "
        captured = {}

        def fake_run(argv, **_kwargs):
            captured["argv"] = argv
            auth_path = Path(argv[argv.index("-A") + 1])
            captured["auth"] = auth_path.read_text(encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "Disk|Music|\n", "")

        with mock.patch.object(network_music, "_run_command", side_effect=fake_run):
            result = network_music.list_smb_shares("nas.local", username="u", password=password)
        self.assertTrue(result["ok"])
        self.assertIn(f"password = {password}\n", captured["auth"])
        self.assertNotIn(password, " ".join(captured["argv"]))
        self.assertNotIn(password, json.dumps(result))

    def test_helper_password_is_stdin_only_and_errors_are_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "helper"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            seen = {}
            def fake_run(argv, **kwargs):
                seen.update(argv=argv, kwargs=kwargs)
                return subprocess.CompletedProcess(argv, 1, json.dumps({"ok": False, "error": "bad secret"}), "")
            with mock.patch.dict(os.environ, {"SROVA_NETWORK_MOUNT_HELPER": str(executable)}), \
                    mock.patch.object(network_music, "_run_command", side_effect=fake_run):
                result = network_music.call_mount_helper("connect", {"password": "secret"}, timeout=7)
            self.assertNotIn("secret", " ".join(seen["argv"]))
            self.assertEqual(json.loads(seen["kwargs"]["input_text"])["password"], "secret")
            self.assertNotIn("secret", result["error"])

    def test_helper_rejects_invalid_responses_and_prefers_sanitized_stderr(self):
        password = "sudo-secret"
        cases = [
            ("", "sudo: a password is required", "sudo: a password is required"),
            ("", "", "Network mount helper returned an invalid response."),
            ("{}", "", "Network mount helper returned an invalid response."),
            ("{broken", "", "Network mount helper returned an invalid response."),
            ("[]", f"helper failed with {password}", "helper failed with [redacted]"),
            ('{"ok": 1}', "", "Network mount helper returned an invalid response."),
        ]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "helper"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            for stdout, stderr, expected in cases:
                proc = subprocess.CompletedProcess([], 1, stdout, stderr)
                with self.subTest(stdout=stdout, stderr=stderr), \
                        mock.patch.dict(os.environ, {"SROVA_NETWORK_MOUNT_HELPER": str(executable)}), \
                        mock.patch.object(network_music, "_run_command", return_value=proc):
                    result = network_music.call_mount_helper("connect", {"password": password})
                self.assertEqual(result, {"ok": False, "error": expected})
                self.assertNotIn(password, json.dumps(result))

    def test_helper_accepts_valid_boolean_ok_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "helper"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            for response in ({"ok": True, "mounted": True}, {"ok": False, "error": "mount failed"}):
                proc = subprocess.CompletedProcess([], 1, json.dumps(response), "ignored stderr")
                with self.subTest(response=response), \
                        mock.patch.dict(os.environ, {"SROVA_NETWORK_MOUNT_HELPER": str(executable)}), \
                        mock.patch.object(network_music, "_run_command", return_value=proc):
                    result = network_music.call_mount_helper("connect", {})
                self.assertEqual(result, response)

    def test_disconnect_root_state_with_other_roots(self):
        state = remove_exact_managed_root(
            "/music:/mnt/srova-network/smb-aaaaaaaaaaaa:/mnt/manual",
            "/mnt/srova-network/smb-aaaaaaaaaaaa:/mnt/manual",
            "/mnt/srova-network/smb-aaaaaaaaaaaa")
        self.assertEqual(state["roots"], ["/music", "/mnt/manual"])
        self.assertEqual(state["network_roots"], ["/mnt/manual"])

    def test_connect_root_state_appends_once_and_preserves_existing_roots(self):
        managed = "/mnt/srova-network/smb-aaaaaaaaaaaa"
        state = add_exact_managed_root("/music:/mnt/manual", "/mnt/manual", managed)
        duplicate = add_exact_managed_root(state["local_value"], state["network_value"], managed)
        self.assertEqual(duplicate["roots"], ["/music", "/mnt/manual", managed])
        self.assertEqual(duplicate["network_roots"], ["/mnt/manual", managed])
        self.assertEqual(duplicate["local_roots"], ["/music"])

    def test_disconnect_only_root_permits_empty_values(self):
        path = "/mnt/srova-network/nfs-aaaaaaaaaaaa"
        state = remove_exact_managed_root(path, path, path)
        self.assertEqual(state["roots"], [])
        self.assertEqual(state["network_roots"], [])
        self.assertEqual(state["local_value"], "")
        self.assertEqual(state["network_value"], "")

    def test_disconnect_preserves_nonmatching_manual_network_root(self):
        managed = "/mnt/srova-network/nfs-aaaaaaaaaaaa"
        manual = "/mnt/nas/music"
        state = remove_exact_managed_root(f"{managed}:{manual}", f"{managed}:{manual}", managed)
        self.assertEqual(state["network_roots"], [manual])

    def test_backend_disconnect_persists_both_empty_values(self):
        import src.main_headless as backend
        managed = "/mnt/srova-network/nfs-aaaaaaaaaaaa"
        writes = {}
        with mock.patch.object(backend, "_load_srova_env_values", return_value={
                backend._LOCAL_TEST_ROOTS_ENV: managed, backend._NETWORK_MUSIC_ROOTS_ENV: managed}), \
                mock.patch.object(backend, "_write_srova_env_values", side_effect=lambda values, _label: writes.update(values)), \
                mock.patch.dict(os.environ, {}, clear=False):
            result = backend._remove_disconnected_managed_root(managed)
        self.assertEqual(result["roots"], [])
        self.assertEqual(writes[backend._LOCAL_TEST_ROOTS_ENV], "")
        self.assertEqual(writes[backend._NETWORK_MUSIC_ROOTS_ENV], "")

    def test_backend_connect_appends_managed_path_and_preserves_local_and_manual_roots(self):
        import src.main_headless as backend
        mid = "smb-aaaaaaaaaaaa"
        managed = f"/mnt/srova-network/{mid}"
        writes = []
        helper_result = {"ok": True, "id": mid, "mount_path": managed, "created_mount": True}
        with mock.patch.object(backend, "_load_srova_env_values", return_value={
                backend._LOCAL_TEST_ROOTS_ENV: "/music:/mnt/manual",
                backend._NETWORK_MUSIC_ROOTS_ENV: "/mnt/manual"}), \
                mock.patch.object(backend, "_write_srova_env_values",
                                  side_effect=lambda values, _label: writes.append(dict(values))), \
                mock.patch.object(backend.network_music, "call_mount_helper", return_value=helper_result), \
                mock.patch.dict(os.environ, {}, clear=False):
            result = backend._network_music_connect_payload({
                "protocol": "smb", "host": "nas.local", "share": "Music",
                "username": "u", "password": "p", "domain": "",
            })
        self.assertTrue(result["ok"])
        self.assertEqual(result["roots"], ["/music", "/mnt/manual", managed])
        self.assertEqual(result["network_roots"], ["/mnt/manual", managed])
        self.assertEqual(result["local_roots"], ["/music"])
        self.assertEqual(writes[-1][backend._NETWORK_MUSIC_ROOTS_ENV], f"/mnt/manual:{managed}")

    def test_backend_connect_does_not_duplicate_managed_path(self):
        import src.main_headless as backend
        mid = "nfs-aaaaaaaaaaaa"
        managed = f"/mnt/srova-network/{mid}"
        with mock.patch.object(backend, "_load_srova_env_values", return_value={
                backend._LOCAL_TEST_ROOTS_ENV: f"/music:{managed}",
                backend._NETWORK_MUSIC_ROOTS_ENV: managed}), \
                mock.patch.object(backend, "_write_srova_env_values"), \
                mock.patch.object(backend.network_music, "call_mount_helper", return_value={
                    "ok": True, "id": mid, "mount_path": managed, "created_mount": True}):
            result = backend._network_music_connect_payload({
                "protocol": "nfs", "host": "192.168.1.20", "export": "/Music"})
        self.assertEqual(result["roots"].count(managed), 1)
        self.assertEqual(result["network_roots"].count(managed), 1)

    def test_backend_connect_env_failure_disconnects_without_password(self):
        import src.main_headless as backend
        password = "  secret with spaces  "
        mid = "smb-aaaaaaaaaaaa"
        managed = f"/mnt/srova-network/{mid}"
        calls = []

        def helper_call(action, payload, timeout):
            calls.append((action, dict(payload), timeout))
            if action == "connect":
                return {"ok": True, "id": mid, "mount_path": managed, "created_mount": True}
            return {"ok": True, "id": mid, "mount_path": managed}

        with mock.patch.object(backend, "_load_srova_env_values", return_value={}), \
                mock.patch.object(backend, "_write_srova_env_values", side_effect=OSError("disk full")), \
                mock.patch.object(backend.network_music, "call_mount_helper", side_effect=helper_call), \
                mock.patch.object(backend.logger, "warning") as warning:
            result = backend._network_music_connect_payload({
                "protocol": "smb", "host": "nas.local", "share": "Music",
                "username": "u", "password": password, "domain": "",
            })
        self.assertFalse(result["ok"])
        self.assertEqual(calls[1][0], "disconnect")
        self.assertEqual(calls[1][1], {"id": mid})
        self.assertNotIn(password, json.dumps(result))
        self.assertNotIn(password, repr(calls[1]))
        self.assertNotIn(password, repr(warning.call_args_list))

    def test_backend_connect_rollback_failure_is_sanitized_partial_failure(self):
        import src.main_headless as backend
        password = "rollback-secret"
        mid = "smb-aaaaaaaaaaaa"
        managed = f"/mnt/srova-network/{mid}"
        responses = [
            {"ok": True, "id": mid, "mount_path": managed, "created_mount": True},
            {"ok": False, "error": f"could not disconnect {password}"},
        ]
        with mock.patch.object(backend, "_load_srova_env_values", return_value={}), \
                mock.patch.object(backend, "_write_srova_env_values", side_effect=OSError("full")), \
                mock.patch.object(backend.network_music, "call_mount_helper", side_effect=responses):
            result = backend._network_music_connect_payload({
                "protocol": "smb", "host": "nas.local", "share": "Music",
                "username": "u", "password": password, "domain": "",
            })
        self.assertFalse(result["ok"])
        self.assertTrue(result["partial_failure"])
        self.assertEqual(result["id"], mid)
        self.assertEqual(result["mount_path"], managed)
        self.assertNotIn(password, json.dumps(result))

    def test_backend_connect_env_failure_leaves_existing_mount_connected(self):
        import src.main_headless as backend
        password = "existing-mount-secret"
        mid = "smb-aaaaaaaaaaaa"
        managed = f"/mnt/srova-network/{mid}"
        for creation_field in ({"created_mount": False}, {}):
            helper_result = {"ok": True, "id": mid, "mount_path": managed, **creation_field}
            with self.subTest(creation_field=creation_field), \
                    mock.patch.object(backend, "_load_srova_env_values", return_value={}), \
                    mock.patch.object(backend, "_write_srova_env_values", side_effect=OSError(password)), \
                    mock.patch.object(backend.network_music, "call_mount_helper", return_value=helper_result) as helper_call, \
                    mock.patch.object(backend.logger, "warning") as warning:
                result = backend._network_music_connect_payload({
                    "protocol": "smb", "host": "nas.local", "share": "Music",
                    "username": "u", "password": password, "domain": "",
                })
            self.assertEqual(helper_call.call_count, 1)
            self.assertEqual(result, {
                "ok": False,
                "partial_failure": True,
                "id": mid,
                "mount_path": managed,
                "mounted": True,
                "error": "The existing mount was left connected, but SROVA could not save it as a music folder.",
            })
            self.assertNotIn(password, json.dumps(result))
            self.assertNotIn(password, repr(warning.call_args_list))

    def test_backend_disconnect_persists_before_helper_and_preserves_manual_root(self):
        import src.main_headless as backend
        mid = "nfs-aaaaaaaaaaaa"
        managed = f"/mnt/srova-network/{mid}"
        manual = "/mnt/manual"
        events = []

        def write(values, _label):
            events.append(("write", dict(values)))

        def helper_call(action, payload, timeout):
            events.append(("helper", action, dict(payload)))
            return {"ok": True, "id": mid, "mount_path": managed}

        with mock.patch.object(backend, "_load_srova_env_values", return_value={
                backend._LOCAL_TEST_ROOTS_ENV: f"/music:{managed}:{manual}",
                backend._NETWORK_MUSIC_ROOTS_ENV: f"{managed}:{manual}"}), \
                mock.patch.object(backend, "_write_srova_env_values", side_effect=write), \
                mock.patch.object(backend.network_music, "call_mount_helper", side_effect=helper_call):
            result = backend._network_music_disconnect_payload({"id": mid})
        self.assertTrue(result["ok"])
        self.assertEqual(result["roots"], ["/music", manual])
        self.assertEqual(result["network_roots"], [manual])
        self.assertEqual(events[0][0], "write")
        self.assertEqual(events[1][0], "helper")

    def test_backend_disconnect_only_root_writes_empty_values(self):
        import src.main_headless as backend
        mid = "smb-aaaaaaaaaaaa"
        managed = f"/mnt/srova-network/{mid}"
        writes = []
        with mock.patch.object(backend, "_load_srova_env_values", return_value={
                backend._LOCAL_TEST_ROOTS_ENV: managed,
                backend._NETWORK_MUSIC_ROOTS_ENV: managed}), \
                mock.patch.object(backend, "_write_srova_env_values",
                                  side_effect=lambda values, _label: writes.append(dict(values))), \
                mock.patch.object(backend.network_music, "call_mount_helper", return_value={
                    "ok": True, "id": mid, "mount_path": managed}):
            result = backend._network_music_disconnect_payload({"id": mid})
        self.assertEqual(result["roots"], [])
        self.assertEqual(writes[0][backend._LOCAL_TEST_ROOTS_ENV], "")
        self.assertEqual(writes[0][backend._NETWORK_MUSIC_ROOTS_ENV], "")

    def test_backend_disconnect_helper_failure_restores_old_values(self):
        import src.main_headless as backend
        mid = "nfs-aaaaaaaaaaaa"
        managed = f"/mnt/srova-network/{mid}"
        original = f"/music:{managed}"
        writes = []
        with mock.patch.object(backend, "_load_srova_env_values", return_value={
                backend._LOCAL_TEST_ROOTS_ENV: original,
                backend._NETWORK_MUSIC_ROOTS_ENV: managed}), \
                mock.patch.object(backend, "_write_srova_env_values",
                                  side_effect=lambda values, _label: writes.append(dict(values))), \
                mock.patch.object(backend.network_music, "call_mount_helper",
                                  return_value={"ok": False, "error": "unmount failed"}), \
                mock.patch.dict(os.environ, {}, clear=False):
            result = backend._network_music_disconnect_payload({"id": mid})
            self.assertEqual(os.environ[backend._LOCAL_TEST_ROOTS_ENV], original)
            self.assertEqual(os.environ[backend._NETWORK_MUSIC_ROOTS_ENV], managed)
        self.assertFalse(result["ok"])
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[1][backend._LOCAL_TEST_ROOTS_ENV], original)
        self.assertEqual(writes[1][backend._NETWORK_MUSIC_ROOTS_ENV], managed)

    def test_backend_disconnect_env_failure_prevents_helper_call(self):
        import src.main_headless as backend
        mid = "nfs-aaaaaaaaaaaa"
        managed = f"/mnt/srova-network/{mid}"
        with mock.patch.object(backend, "_load_srova_env_values", return_value={
                backend._LOCAL_TEST_ROOTS_ENV: managed,
                backend._NETWORK_MUSIC_ROOTS_ENV: managed}), \
                mock.patch.object(backend, "_write_srova_env_values", side_effect=OSError("full")), \
                mock.patch.object(backend.network_music, "call_mount_helper") as helper_call:
            result = backend._network_music_disconnect_payload({"id": mid})
        self.assertFalse(result["ok"])
        helper_call.assert_not_called()

    def test_ui_guards_duplicate_operations_and_does_not_resave_on_disconnect(self):
        source = (self.repo_root / "src/ui_web/ui.js").read_text(encoding="utf-8")
        connect = source[source.index("function connectSelected"):source.index("function renderMounts", source.index("function connectSelected"))]
        disconnect = source[source.index("function disconnectMount"):source.index("function discover", source.index("function disconnectMount"))]
        self.assertIn("connectInFlight", source)
        self.assertIn('currentCredentials.password = ""', source)
        self.assertIn("window.confirm", disconnect)
        self.assertIn("disconnectInFlight", disconnect)
        self.assertNotIn("saveRoots", connect)
        self.assertIn("options.reloadStatus", connect)
        self.assertNotIn("saveRoots", disconnect)
        self.assertIn("options.reloadStatus", disconnect)

    def test_ui_share_selection_is_visible_and_exclusive(self):
        source = (self.repo_root / "src/ui_web/ui.js").read_text(encoding="utf-8")
        render_start = source.index("function renderShares")
        render = source[render_start:source.index("function renderConnect", render_start)]
        selection_and_connect = source[render_start:source.index("function renderMounts", render_start)]

        self.assertIn('row.setAttribute("aria-pressed", "false")', render)
        self.assertIn('sharePanel.querySelectorAll(".networkShareShareRow")', render)
        self.assertIn('shareRow.classList.toggle("networkShareShareRowSelected", isSelected)', render)
        self.assertIn('shareRow.setAttribute("aria-pressed", isSelected ? "true" : "false")', render)
        self.assertIn('hint.className = "networkShareShareHint"', render)
        self.assertIn('shareHint.textContent = isSelected ? "Selected" : "Select"', render)
        self.assertIn('protocol === "nfs" ? item.path : item.name', render)
        self.assertIn("updateShareRowSelection(row)", render)
        self.assertIn("renderConnect()", render)
        self.assertNotIn("saveRoots", selection_and_connect)

        css = (self.repo_root / "src/ui_web/srova.css").read_text(encoding="utf-8")
        self.assertIn(".networkShareShareRowSelected {", css)
        self.assertIn(".networkShareShareRowSelected .networkShareShareHint {", css)
        self.assertIn(".networkShareShareRow:focus-visible {", css)

    def test_ui_managed_network_roots_use_friendly_safe_rows(self):
        source = (self.repo_root / "src/ui_web/ui.js").read_text(encoding="utf-8")
        name_start = source.index("function managedNetworkShareName")
        detail_start = source.index("function managedNetworkShareDetail", name_start)
        name_formatter = source[name_start:detail_start]
        detail_formatter = source[detail_start:source.index("function buildLocalMusicLibrarySection", detail_start)]

        self.assertIn('protocol === "smb" && source.indexOf("//") === 0', name_formatter)
        self.assertIn('source.slice(2).split("/")', name_formatter)
        self.assertIn('source.indexOf(":")', name_formatter)
        self.assertIn('pathPart.split("/")', name_formatter)
        for fallback in ("SMB Share", "NFS Share", "Network Share"):
            self.assertIn(fallback, name_formatter)
        self.assertIn('var source = String(mount.source || "")', detail_formatter)
        self.assertIn('parts.push(source)', detail_formatter)
        self.assertIn('"mounted read-only" : "not mounted"', detail_formatter)

        rows_start = source.index("function addManagedNetworkLibraryPathRow")
        rows_end = source.index("function getRootsFromInputs", rows_start)
        rows = source[rows_start:rows_end]
        self.assertIn('row.className = "settingsField localLibraryManagedPathRow"', rows)
        self.assertIn('name.textContent = managedNetworkShareName(mount)', rows)
        self.assertIn('detail.textContent = managedNetworkShareDetail(mount)', rows)
        self.assertIn('internalRoot.type = "hidden"', rows)
        self.assertIn("internalRoot.value = root", rows)
        self.assertIn("networkLibraryPathInputs.push(internalRoot)", rows)
        self.assertIn('disconnectBtn.textContent = "Disconnect"', rows)
        self.assertIn("root === mount.mount_path", rows)
        self.assertIn("addManagedNetworkLibraryPathRow(root, matchedMount)", rows)
        self.assertIn("addNetworkLibraryPathRow(root)", rows)

        disconnect_start = source.index("function disconnectManagedNetworkRoot")
        disconnect_end = source.index("function addManagedNetworkLibraryPathRow", disconnect_start)
        disconnect = source[disconnect_start:disconnect_end]
        self.assertIn("managedDisconnectInFlight[mountId]", disconnect)
        self.assertIn('window.confirm("Disconnect this managed network share?")', disconnect)
        self.assertIn('fetch("/api/local/library/network/disconnect"', disconnect)
        self.assertIn('method: "POST"', disconnect)
        self.assertIn("JSON.stringify({id: mount.id})", disconnect)
        self.assertIn("return loadStatus()", disconnect)
        self.assertNotIn("saveCurrentMusicRoots", disconnect)
        self.assertNotIn("saveRoots", disconnect)

        load_start = source.index("function loadStatus()", rows_end)
        load_end = source.index("saveBtn.onclick", load_start)
        loading = source[load_start:load_end]
        self.assertLess(
            loading.index('fetch("/api/local/library/status", {cache: "no-store"})'),
            loading.index('fetch("/api/local/library/network/mounts", {cache: "no-store"})'),
        )
        self.assertIn('.catch(function() { return []; })', loading)
        self.assertIn("renderStats(data || {}, managedMounts)", loading)

        mounts_start = source.index("function renderMounts")
        mounts_end = source.index("function loadMounts", mounts_start)
        mounts_render = source[mounts_start:mounts_end]
        self.assertIn("managedNetworkShareName(mount)", mounts_render)
        self.assertIn("managedNetworkShareDetail(mount)", mounts_render)
        self.assertNotIn("mount.mount_path", mounts_render)
        self.assertNotIn("networkShareMountPath", mounts_render)

        css = (self.repo_root / "src/ui_web/srova.css").read_text(encoding="utf-8")
        self.assertIn("#settingsView .localLibraryManagedPathRow {", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", css)
        self.assertIn("#settingsView .localLibraryManagedPathName {", css)
        self.assertIn("#settingsView .localLibraryManagedPathDetail,", css)
        self.assertIn("overflow-wrap: anywhere", css)
        mobile_start = css.index("@media (max-width: 640px)", css.index("#settingsView .localLibraryManagedPathRow"))
        mobile = css[mobile_start:css.index("/* Audirvana depth selector buttons */", mobile_start)]
        self.assertIn("#settingsView .localLibraryManagedPathRow", mobile)
        self.assertIn("grid-template-columns: 1fr", mobile)

        html = (self.repo_root / "src/ui_web/index.html").read_text(encoding="utf-8")
        # CSS and JavaScript may use independent cache-bust keys when only
        # one asset changes. Both references must remain explicitly versioned.
        self.assertRegex(
            html,
            r'/ui_web/srova\.css\?v=[A-Za-z0-9_.-]+',
        )
        self.assertRegex(
            html,
            r'/ui_web/ui\.js\?v=[A-Za-z0-9_.-]+',
        )

    def test_debian_lifecycle_and_payload_checks_are_safe(self):
        relative = "package.sh"
        source = (self.repo_root / relative).read_text(
            encoding="utf-8"
        )

        prerm = source.index(
            'if [ "$1" = "remove" ] || '
            '[ "$1" = "deconfigure" ]'
        )
        stop = source.index(
            "systemctl stop srova.service",
            prerm,
        )
        unmount = source.index("unmount-all", prerm)

        self.assertLess(stop, unmount, relative)
        self.assertIn(
            "srova-network-mount-helper "
            "unmount-all </dev/null",
            source,
            relative,
        )
        self.assertIn('rmdir "$managed_dir"', source)
        self.assertNotIn(
            "rm -rf /mnt/srova-network",
            source,
        )
        self.assertIn(
            "srova-network-mount-helper",
            source,
        )
        self.assertIn(
            "srova-network-mounts.service",
            source,
        )
        self.assertIn("srova-network-mount", source)
        self.assertIn("visudo -cf", source)

        for mode in ("755", "644", "440"):
            self.assertIn(mode, source)

        self.assertEqual(
            source.count(
                'dpkg-deb --root-owner-group '
                '--build "$BUILD_ROOT"'
            ),
            2,
        )
        self.assertNotIn(
            'dpkg-deb --build "$BUILD_ROOT"',
            source,
        )
        self.assertIn(
            "validate_deb_network_archive",
            source,
        )

        for expected in (
            "root/root",
            "-rwxr-xr-x",
            "-rw-r--r--",
            "-r--r-----",
        ):
            self.assertIn(expected, source)

    def test_debian_payload_rejects_oversized_application_svg_artwork(self):
        package_source = (self.repo_root / "package.sh").read_text(encoding="utf-8")
        bootstrap_source = (
            self.repo_root / "src/app/app_bootstrap.py"
        ).read_text(encoding="utf-8")

        forbidden_svg = (
            self.repo_root
            / "icons/hicolor/scalable/apps/hiresti.svg"
        )
        self.assertFalse(forbidden_svg.exists())

        self.assertIn("audit_svg_tree()", package_source)
        self.assertIn(
            'audit_svg_tree "$BUILD_ROOT" "staged package payload"',
            package_source,
        )
        self.assertIn(
            'audit_svg_tree "$svg_root" "packaging source"',
            package_source,
        )
        self.assertIn("hiresti.svg|srova.svg", package_source)
        self.assertIn('"$size" -gt 262144', package_source)
        self.assertIn("embedded Base64 image data", package_source)
        self.assertIn("-type f -name \"hiresti.png\"", package_source)
        self.assertNotIn(
            '-name "hiresti.png" -o -name "hiresti.svg"',
            package_source,
        )
        self.assertNotIn(
            'hicolor/scalable/apps/srova.svg',
            package_source,
        )

        self.assertIn(
            '"hicolor", "512x512", "apps", "hiresti.png"',
            bootstrap_source,
        )
        self.assertNotIn(
            '"scalable", "apps", "hiresti.svg"',
            bootstrap_source,
        )


    def test_arm64_debian_wrapper_delegates_to_package_builder(self):
        wrapper_path = (
            self.repo_root
            / "packaging/arm64/build_deb.sh"
        )
        old_path = (
            self.repo_root
            / "packaging/arm64/build_rc1_deb.sh"
        )
        readme_path = (
            self.repo_root
            / "packaging/arm64/README.md"
        )

        self.assertTrue(wrapper_path.is_file())
        self.assertFalse(old_path.exists())

        source = wrapper_path.read_text(encoding="utf-8")
        readme = readme_path.read_text(encoding="utf-8")

        for expected in (
            "set -euo pipefail",
            'ARCH="$(dpkg --print-architecture)"',
            'if [ "$ARCH" != "arm64" ]; then',
            "version.txt",
            'exec bash "$PACKAGE_SCRIPT" deb "$VERSION"',
        ):
            self.assertIn(expected, source)

        for obsolete in (
            "v1.0-rc1",
            "1.0~rc1-1",
            "NON-RC1 SOURCE OVERRIDE",
            "SROVA_PORT=8080",
            "/opt/srova/app",
        ):
            self.assertNotIn(obsolete, source)

        self.assertEqual(
            (
                self.repo_root / "version.txt"
            ).read_text(encoding="utf-8").strip(),
            "1.0-1",
        )

        for expected in (
            "package.sh",
            "build_deb.sh",
            "1.0-1",
            "/opt/srova",
            "8081",
        ):
            self.assertIn(expected, readme)



class NetworkMusicSettingsRefreshTests(unittest.TestCase):



    def test_configured_root_parsing_does_not_touch_filesystem(self):
        import src.main_headless as backend

        root = "/mnt/music"
        with mock.patch.object(
            backend,
            "_load_srova_env_values",
            return_value={backend._LOCAL_TEST_ROOTS_ENV: root},
        ), mock.patch.object(
            backend.os.path,
            "realpath",
            side_effect=AssertionError("realpath touched filesystem"),
        ), mock.patch.object(
            backend.os.path,
            "isdir",
            side_effect=AssertionError("isdir touched filesystem"),
        ):
            self.assertEqual(backend._local_test_roots(), [root])

    def test_active_roots_exclude_offline_network_without_touching_it(self):
        import src.main_headless as backend

        root = "/mnt/offline-music"
        with mock.patch.object(
            backend,
            "_network_music_roots",
            return_value=[root],
        ), mock.patch.object(
            backend,
            "_network_mount_entry_for_path",
            return_value=None,
        ), mock.patch.object(
            backend,
            "_autofs_mount_for_path",
            return_value="",
        ), mock.patch.object(
            backend,
            "_local_library_path_diagnostics",
            side_effect=AssertionError("offline network root was touched"),
        ):
            active = backend._active_local_test_roots([root])

        self.assertEqual(active, [])

    def test_scan_runs_preflight_before_active_root_resolution(self):
        import src.main_headless as backend

        root = "/mnt/music"
        events = []

        class FakeIndex:
            def __init__(self, roots):
                events.append(("index", list(roots)))

            def scan(self):
                events.append(("scan",))
                return {"ok": True}

        def preflight(roots, action):
            events.append(("preflight", list(roots), action))
            return None

        def active(roots):
            events.append(("active", list(roots)))
            return list(roots)

        with mock.patch.object(
            backend,
            "_local_test_roots",
            return_value=[root],
        ), mock.patch.object(
            backend,
            "_local_library_network_scan_preflight",
            side_effect=preflight,
        ), mock.patch.object(
            backend,
            "_active_local_test_roots",
            side_effect=active,
        ), mock.patch.object(
            backend,
            "LocalLibraryIndex",
            FakeIndex,
        ):
            result = backend._local_library_scan_payload()

        self.assertTrue(result["ok"])
        self.assertEqual(
            [event[0] for event in events],
            ["preflight", "active", "index", "scan"],
        )

    def test_scan_uses_active_subset_and_reports_unavailable_root(self):
        import src.main_headless as backend

        local = "/DATA/music"
        offline = "/mnt/offline-network"
        captured = {}

        class FakeIndex:
            def __init__(self, roots):
                captured["roots"] = list(roots)

            def scan(self):
                return {"ok": True, "stale": 0}

        with mock.patch.object(
            backend,
            "_local_test_roots",
            return_value=[local, offline],
        ), mock.patch.object(
            backend,
            "_local_library_network_scan_preflight",
            return_value=None,
        ), mock.patch.object(
            backend,
            "_active_local_test_roots",
            return_value=[local],
        ), mock.patch.object(
            backend,
            "LocalLibraryIndex",
            FakeIndex,
        ):
            result = backend._local_library_scan_payload()

        self.assertTrue(result["ok"])
        self.assertEqual(captured["roots"], [local])
        self.assertEqual(result["configured_roots"], [local, offline])
        self.assertEqual(result["unavailable_roots"], [offline])

    def test_rebuild_is_blocked_when_any_configured_root_is_unavailable(self):
        import src.main_headless as backend

        local = "/DATA/music"
        offline = "/mnt/offline-network"

        with mock.patch.object(
            backend,
            "_local_test_roots",
            return_value=[local, offline],
        ), mock.patch.object(
            backend,
            "_local_library_network_scan_preflight",
            return_value=None,
        ), mock.patch.object(
            backend,
            "_active_local_test_roots",
            return_value=[local],
        ), mock.patch.object(
            backend,
            "LocalLibraryIndex",
        ) as index, mock.patch.object(
            backend.threading,
            "Thread",
        ) as thread:
            result = backend._local_library_rebuild_payload()

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            "local_library_rebuild_roots_unavailable",
        )
        self.assertEqual(result["unavailable_roots"], [offline])
        index.assert_not_called()
        thread.assert_not_called()

    def test_cleanup_uses_active_subset_without_deleting_offline_root_rows(self):
        import src.main_headless as backend

        local = "/DATA/music"
        offline = "/mnt/offline-network"
        captured = {}

        class FakeIndex:
            def __init__(self, roots):
                captured["roots"] = list(roots)

            def cleanup_stale(self):
                return {"ok": True, "deleted": 0}

        with mock.patch.object(
            backend,
            "_local_test_roots",
            return_value=[local, offline],
        ), mock.patch.object(
            backend,
            "_local_library_network_scan_preflight",
            return_value=None,
        ), mock.patch.object(
            backend,
            "_active_local_test_roots",
            return_value=[local],
        ), mock.patch.object(
            backend,
            "LocalLibraryIndex",
            FakeIndex,
        ):
            result = backend._local_library_cleanup_stale_payload()

        self.assertTrue(result["ok"])
        self.assertEqual(captured["roots"], [local])
        self.assertEqual(result["unavailable_roots"], [offline])

    def test_status_reads_database_without_passing_configured_roots(self):
        import src.main_headless as backend

        captured = {}

        class FakeIndex:
            def __init__(self, roots):
                captured["roots"] = list(roots)

            def status(self):
                return {"ok": True, "track_count": 10, "roots": []}

        with mock.patch.object(
            backend,
            "_sync_local_library_artwork_policy",
        ), mock.patch.object(
            backend,
            "_music_root_availability",
            return_value={
                "configured_roots": ["/mnt/music"],
                "active_roots": [],
                "unavailable_roots": ["/mnt/music"],
            },
        ), mock.patch.object(
            backend,
            "LocalLibraryIndex",
            FakeIndex,
        ):
            result = backend._local_library_status_payload()

        self.assertEqual(captured["roots"], [])
        self.assertEqual(result["configured_roots"], ["/mnt/music"])
        self.assertEqual(result["unavailable_roots"], ["/mnt/music"])

    def test_autofs_wake_child_uses_bounded_nonrecursive_scandir(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "main_headless.py"
        ).read_text(encoding="utf-8")

        start = source.index("def _wake_exact_autofs_path")
        end = source.index(
            "def _local_library_env_value_from_files",
            start,
        )
        wake = source[start:end]

        self.assertIn("os.scandir(sys.argv[1])", wake)
        self.assertIn("next(it,None)", wake)
        self.assertIn("process.wait(timeout=", wake)
        self.assertNotIn("os.stat(sys.argv[1])", wake)

    def test_explicit_empty_saved_roots_override_stale_process_environment(self):
        import src.main_headless as backend

        stale_local = "/mnt/stale-local"
        stale_network = "/mnt/stale-network"

        with mock.patch.object(
            backend,
            "_load_srova_env_values",
            return_value={
                backend._LOCAL_TEST_ROOTS_ENV: "",
                backend._NETWORK_MUSIC_ROOTS_ENV: "",
            },
        ), mock.patch.dict(
            backend.os.environ,
            {
                backend._LOCAL_TEST_ROOTS_ENV: stale_local,
                backend._NETWORK_MUSIC_ROOTS_ENV: stale_network,
            },
            clear=False,
        ), mock.patch.object(
            backend.os.path,
            "isdir",
        ) as isdir:
            self.assertEqual(backend._local_test_roots(), [])
            self.assertEqual(
                backend._saved_music_root_values(
                    backend._LOCAL_TEST_ROOTS_ENV
                ),
                [],
            )
            self.assertEqual(
                backend._saved_music_root_values(
                    backend._NETWORK_MUSIC_ROOTS_ENV
                ),
                [],
            )
            self.assertEqual(backend._local_library_network_roots(), [])
            self.assertEqual(backend._network_music_roots(), [])

        isdir.assert_not_called()

    def test_unmounted_mnt_root_on_root_filesystem_remains_pending(self):
        import src.main_headless as backend

        with mock.patch.object(
            backend,
            "_autofs_mount_for_path",
            return_value="",
        ), mock.patch.object(
            backend,
            "_active_non_autofs_mount_for_path",
            return_value={
                "mount_point": "/",
                "fstype": "ext4",
                "source": "/dev/root",
            },
        ), mock.patch.object(
            backend,
            "_local_library_mount_expected",
            return_value=True,
        ), mock.patch.object(
            backend.os.path,
            "isdir",
            return_value=True,
        ):
            kind = backend._legacy_music_root_kind("/mnt/music")

        self.assertEqual(kind, "pending")

    def test_normal_local_directory_on_root_filesystem_is_local(self):
        import src.main_headless as backend

        with mock.patch.object(
            backend,
            "_autofs_mount_for_path",
            return_value="",
        ), mock.patch.object(
            backend,
            "_active_non_autofs_mount_for_path",
            return_value={
                "mount_point": "/",
                "fstype": "ext4",
                "source": "/dev/root",
            },
        ), mock.patch.object(
            backend,
            "_local_library_mount_expected",
            return_value=False,
        ), mock.patch.object(
            backend.os.path,
            "isdir",
            return_value=True,
        ):
            kind = backend._legacy_music_root_kind("/home/music-library")

        self.assertEqual(kind, "local")

    def test_active_non_network_mount_below_mnt_is_local(self):
        import src.main_headless as backend

        with mock.patch.object(
            backend,
            "_autofs_mount_for_path",
            return_value="",
        ), mock.patch.object(
            backend,
            "_active_non_autofs_mount_for_path",
            return_value={
                "mount_point": "/mnt/srova-usb",
                "fstype": "ntfs3",
                "source": "/dev/sda1",
            },
        ):
            kind = backend._legacy_music_root_kind(
                "/mnt/srova-usb/Music"
            )

        self.assertEqual(kind, "local")

    def test_network_rows_remain_configured_when_share_is_offline(self):
        import src.main_headless as backend

        root = "/mnt/offline-music"
        with mock.patch.object(
            backend,
            "_load_srova_env_values",
            return_value={
                backend._LOCAL_TEST_ROOTS_ENV: root,
                backend._NETWORK_MUSIC_ROOTS_ENV: root,
            },
        ), mock.patch.object(backend.os.path, "isdir", return_value=False):
            state = backend._configured_music_root_state()
            network = backend._network_music_roots()

        self.assertEqual(state["roots"], [root])
        self.assertEqual(state["network_roots"], [root])
        self.assertEqual(state["local_roots"], [])
        self.assertEqual(network, [root])

    def test_autofs_preflight_wakes_once_and_allows_new_backing_mount(self):
        import src.main_headless as backend

        root = "/mnt/music"
        blocked = {"root": root, "autofs_mount": root}

        with mock.patch.object(
            backend,
            "_network_music_roots",
            return_value=[root],
        ), mock.patch.object(
            backend,
            "_local_library_autofs_blocked_network_roots",
            side_effect=[[blocked], []],
        ) as blocker, mock.patch.object(
            backend,
            "_wake_exact_autofs_path",
            return_value=True,
        ) as wake, mock.patch.object(
            backend,
            "_sync_local_library_artwork_policy",
        ) as artwork:
            result = backend._local_library_network_scan_preflight(
                [root],
                action="scan",
            )

        self.assertIsNone(result)
        wake.assert_called_once_with(root)
        self.assertEqual(blocker.call_count, 2)
        artwork.assert_called_once_with([root])

    def test_autofs_preflight_blocks_after_one_failed_recheck(self):
        import src.main_headless as backend

        root = "/mnt/music"
        blocked = {"root": root, "autofs_mount": root}

        with mock.patch.object(
            backend,
            "_network_music_roots",
            return_value=[root],
        ), mock.patch.object(
            backend,
            "_local_library_autofs_blocked_network_roots",
            side_effect=[[blocked], [blocked]],
        ) as blocker, mock.patch.object(
            backend,
            "_wake_exact_autofs_path",
            return_value=False,
        ) as wake:
            result = backend._local_library_network_scan_preflight(
                [root],
                action="rebuild",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            backend._NETWORK_AUTOMOUNT_SCAN_ERROR,
        )
        self.assertEqual(result["wake_attempted_roots"], [root])
        wake.assert_called_once_with(root)
        self.assertEqual(blocker.call_count, 2)

    def test_rc1_network_root_migration_classifies_proven_nfs_without_changing_combined_roots(self):
        import src.main_headless as backend

        root = "/mnt/music"
        writes = []

        with mock.patch.object(
            backend,
            "_load_srova_env_values",
            return_value={backend._LOCAL_TEST_ROOTS_ENV: root},
        ), mock.patch.object(
            backend,
            "_legacy_music_root_kind",
            return_value="network",
        ), mock.patch.object(
            backend,
            "_write_srova_env_values",
            side_effect=lambda values, label: writes.append((dict(values), label)),
        ), mock.patch.dict(backend.os.environ, {}, clear=False):
            result = backend._migrate_legacy_network_root_state()

        self.assertEqual(result["status"], backend._NETWORK_ROOT_MIGRATION_COMPLETE)
        self.assertEqual(result["network_roots"], [root])
        self.assertEqual(result["classified_roots"], [root])
        self.assertEqual(
            writes[0][0][backend._NETWORK_MUSIC_ROOTS_ENV],
            root,
        )
        self.assertNotIn(
            backend._LOCAL_TEST_ROOTS_ENV,
            writes[0][0],
        )
        self.assertEqual(
            writes[0][0][backend._NETWORK_ROOT_MIGRATION_ENV],
            backend._NETWORK_ROOT_MIGRATION_COMPLETE,
        )

    def test_ambiguous_rc1_root_is_preserved_and_marked_pending(self):
        import src.main_headless as backend

        root = "/mnt/music"
        writes = []

        with mock.patch.object(
            backend,
            "_load_srova_env_values",
            return_value={backend._LOCAL_TEST_ROOTS_ENV: root},
        ), mock.patch.object(
            backend,
            "_legacy_music_root_kind",
            return_value="pending",
        ), mock.patch.object(
            backend,
            "_write_srova_env_values",
            side_effect=lambda values, label: writes.append((dict(values), label)),
        ), mock.patch.dict(backend.os.environ, {}, clear=False):
            result = backend._migrate_legacy_network_root_state()

        self.assertEqual(result["status"], backend._NETWORK_ROOT_MIGRATION_PENDING)
        self.assertEqual(result["pending_roots"], [root])
        self.assertEqual(result["network_roots"], [])
        self.assertEqual(
            writes[0][0][backend._NETWORK_MUSIC_ROOTS_ENV],
            "",
        )
        self.assertNotIn(
            backend._LOCAL_TEST_ROOTS_ENV,
            writes[0][0],
        )

    def test_existing_rc2_network_classification_is_preserved(self):
        import src.main_headless as backend

        root = "/mnt/srova-network/nfs-aaaaaaaaaaaa"
        writes = []

        with mock.patch.object(
            backend,
            "_load_srova_env_values",
            return_value={
                backend._LOCAL_TEST_ROOTS_ENV: root,
                backend._NETWORK_MUSIC_ROOTS_ENV: root,
            },
        ), mock.patch.object(
            backend,
            "_legacy_music_root_kind",
        ) as classify, mock.patch.object(
            backend,
            "_write_srova_env_values",
            side_effect=lambda values, label: writes.append((dict(values), label)),
        ):
            result = backend._migrate_legacy_network_root_state()

        classify.assert_not_called()
        self.assertEqual(result["status"], backend._NETWORK_ROOT_MIGRATION_COMPLETE)
        self.assertEqual(
            writes[0][0],
            {
                backend._NETWORK_ROOT_MIGRATION_ENV:
                    backend._NETWORK_ROOT_MIGRATION_COMPLETE,
            },
        )

    def test_explicit_root_saves_and_managed_mutations_complete_migration(self):
        source = (
            Path(__file__).resolve().parents[1] / "src" / "main_headless.py"
        ).read_text(encoding="utf-8")

        self.assertGreaterEqual(
            source.count(
                "_NETWORK_ROOT_MIGRATION_ENV: "
                "_NETWORK_ROOT_MIGRATION_COMPLETE"
            ),
            2,
        )
        self.assertIn(
            "migration = _migrate_legacy_network_root_state()",
            source,
        )
        self.assertIn(
            'self._send_json(data, no_store=True)',
            source[
                source.index('if static_path == "/api/local/library/status"'):
                source.index(
                    'if static_path == "/api/local/library/network/discover"'
                )
            ],
        )


    def test_ui_javascript_uses_single_valid_cache_token(self):
        index = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "ui_web"
            / "index.html"
        ).read_text(encoding="utf-8")

        prefix = "/ui_web/ui.js?v="
        self.assertEqual(index.count(prefix), 1)

        token = index.split(prefix, 1)[1].split('"', 1)[0]
        self.assertTrue(token)
        self.assertTrue(
            all(
                char.isalnum() or char in "_.-"
                for char in token
            )
        )
        self.assertNotIn(
            '<script src="/ui_web/ui.js"></script>',
            index,
        )

    def test_network_discovery_note_states_network_and_share_requirements(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "ui_web"
            / "ui.js"
        ).read_text(encoding="utf-8")

        section_start = source.index(
            "function buildLocalMusicLibrarySection()"
        )
        section_end = source.index(
            "function openNetworkShareDiscoveryModal",
            section_start,
        )
        section = source[section_start:section_end]

        self.assertIn(
            "localLibraryNetworkDiscoveryNote",
            section,
        )
        self.assertIn(
            "the same network",
            section,
        )
        self.assertIn(
            "an NFS or SMB share",
            section,
        )
        self.assertIn(
            'networkDiscoveryNote.className = '
            '"settingsDependencyNote localLibraryInfoNote '
            'localLibraryNetworkDiscoveryNote";',
            section,
        )

    def test_network_discovery_note_uses_existing_dependency_note_classes(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "ui_web"
            / "ui.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '"settingsDependencyNote localLibraryInfoNote '
            'localLibraryNetworkDiscoveryNote"',
            source,
        )

        # The note deliberately inherits the existing dependency-note
        # styling rather than introducing a separate fixed-width layout.
        css = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "ui_web"
            / "srova.css"
        ).read_text(encoding="utf-8")

        self.assertIn(".settingsDependencyNote", css)

    def test_settings_rows_use_canonical_mutation_results_and_ignore_stale_status(self):
        source = (
            Path(__file__).resolve().parents[1] / "src" / "ui_web" / "ui.js"
        ).read_text(encoding="utf-8")

        self.assertIn("var lastManagedNetworkMounts = [];", source)
        self.assertIn("var localLibraryStatusRequestSerial = 0;", source)
        self.assertIn("function applyCanonicalMusicRootRows(data, managedMounts)", source)
        self.assertIn(
            "var configuredRoots = Array.isArray(data.configured_roots)",
            source,
        )
        self.assertIn(
            ": (Array.isArray(data.roots) ? data.roots : []);",
            source,
        )
        self.assertIn(
            "configuredRoots.filter(function(root)",
            source,
        )

        save_start = source.index("function saveCurrentMusicRoots")
        save_end = source.index("function setBusy", save_start)
        save_flow = source[save_start:save_end]
        self.assertIn("applyCanonicalMusicRootRows(data);", save_flow)
        self.assertIn(
            "return loadStatus().then(function() { return data; });",
            save_flow,
        )

        render_start = source.index("function renderStats")
        render_end = source.index("function stopPolling", render_start)
        render_flow = source[render_start:render_end]
        self.assertIn(
            "applyCanonicalMusicRootRows(data, managedMounts);",
            render_flow,
        )

        load_start = source.index("function loadStatus()")
        load_end = source.index("saveBtn.onclick", load_start)
        load_flow = source[load_start:load_end]
        self.assertIn(
            "var requestSerial = ++localLibraryStatusRequestSerial;",
            load_flow,
        )
        self.assertIn(
            'fetch("/api/local/library/status", {cache: "no-store"})',
            load_flow,
        )
        self.assertIn(
            'fetch("/api/local/library/network/mounts", {cache: "no-store"})',
            load_flow,
        )
        self.assertIn(
            "if (requestSerial !== localLibraryStatusRequestSerial) { return data; }",
            load_flow,
        )
        self.assertIn(
            "if (requestSerial !== localLibraryStatusRequestSerial) { return null; }",
            load_flow,
        )

        disconnect_start = source.index("function disconnectManagedNetworkRoot")
        disconnect_end = source.index(
            "function addManagedNetworkLibraryPathRow",
            disconnect_start,
        )
        disconnect_flow = source[disconnect_start:disconnect_end]
        self.assertIn(
            "applyCanonicalMusicRootRows(data);",
            disconnect_flow,
        )

if __name__ == "__main__":
    unittest.main()
