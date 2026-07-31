import fcntl
import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HELPER_PATH = Path(__file__).resolve().parents[1] / "packaging/network/srova-network-mount-helper"
loader = importlib.machinery.SourceFileLoader("srova_network_mount_helper", str(HELPER_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


class HelperTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        patches = {
            "MANAGED_BASE": root / "mnt",
            "CONFIG_DIR": root / "etc",
            "CONFIG_FILE": root / "etc/network-mounts.json",
            "CREDENTIAL_DIR": root / "etc/credentials",
            "LOCK_FILE": root / "run/srova.lock",
        }
        self.patchers = [mock.patch.object(helper, name, value) for name, value in patches.items()]
        for patcher in self.patchers:
            patcher.start()
        self.ids = mock.patch.object(helper, "service_ids", return_value=(1001, 1002))
        self.ids.start()

    def tearDown(self):
        self.ids.stop()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def nfs(self, host="192.168.1.20", export="/Music"):
        return {"protocol": "nfs", "host": host, "export": export}

    def smb(self, **extra):
        data = {"protocol": "smb", "host": "nas.local", "share": "Music"}
        data.update(extra)
        return data

    def config_with(self, *definitions):
        return {"version": 1, "mounts": [helper.validate_definition(item) for item in definitions]}

    def test_validation_rejects_unsafe_values_and_bad_id(self):
        cases = [
            (helper.validate_host, "bad\nhost"), (helper.validate_host, "bad,host"),
            (helper.validate_host, "-bad"), (helper.validate_host, "2001:db8::1"),
            (helper.validate_smb_share, "Music/FLAC"), (helper.validate_smb_share, "Music,ro"),
            (helper.validate_nfs_export, "Music"), (helper.validate_nfs_export, "/Music/../Other"),
            (helper.validate_managed_id, "../../outside"),
        ]
        for function, value in cases:
            with self.subTest(value=value), self.assertRaises(helper.HelperError):
                function(value)
        self.assertRegex(helper.mount_id(self.nfs()), r"^nfs-[0-9a-f]{12}$")

    def test_malformed_numeric_hosts_are_rejected(self):
        for host in ("999.1.1.1", "1.2.3", "192.168.1.999"):
            with self.subTest(host=host), self.assertRaisesRegex(helper.HelperError, "malformed"):
                helper.validate_host(host)
        self.assertEqual(helper.validate_host("192.168.1.20"), "192.168.1.20")
        self.assertEqual(helper.validate_host("nas.local"), "nas.local")

    def test_password_control_character_and_lengths_rejected(self):
        for value in ("bad\nsecret", "bad\rsecret", "bad\tsecret", "bad\x00secret", "bad\x7fsecret"):
            with self.subTest(value=repr(value)), self.assertRaises(helper.HelperError):
                helper.validate_password(value)
        with self.assertRaises(helper.HelperError):
            helper.validate_password("x" * 1025)
        with self.assertRaises(helper.HelperError):
            helper.validate_host("a" * 254)
        self.assertEqual(helper.validate_password("  secret with spaces  "), "  secret with spaces  ")
        self.assertEqual(helper.validate_password(""), "")

    def test_password_spaces_are_exact_in_credential_file_and_absent_from_mount_argv(self):
        password = "  secret with spaces  "
        self._active = self.smb(username="me", password=password)
        state, calls, finder, runner = self._mount_state_runner()
        captured = {}
        real_create = helper.create_temporary_credentials

        def create_and_capture(*args, **kwargs):
            path = real_create(*args, **kwargs)
            captured["text"] = path.read_text(encoding="utf-8")
            return path

        with mock.patch.object(helper, "findmnt", side_effect=finder), \
                mock.patch.object(helper, "run", side_effect=runner), \
                mock.patch.object(helper, "mounted_ok", side_effect=lambda _d: state["mounted"]), \
                mock.patch.object(helper, "create_temporary_credentials", side_effect=create_and_capture):
            result = helper.mount_defn(self._active, persist=False)
        self.assertIn("password=  secret with spaces  \n", captured["text"])
        self.assertNotIn(password, " ".join(next(argv for argv in calls if argv[0] == "mount")))
        self.assertNotIn(password, json.dumps(result))

    def test_caller_supplied_target_rejected(self):
        stream = mock.Mock()
        stream.read.return_value = '{"target":"/tmp/x"}'
        with mock.patch.object(helper.sys, "stdin", stream), self.assertRaises(helper.HelperError):
            helper.read_stdin_json()

    def test_corrupt_and_unsupported_config_are_errors(self):
        helper.CONFIG_DIR.mkdir(parents=True)
        helper.CONFIG_FILE.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(helper.HelperError, "malformed"):
            helper.load_config()
        helper.CONFIG_FILE.write_text('{"version":99,"mounts":[]}', encoding="utf-8")
        with self.assertRaisesRegex(helper.HelperError, "unsupported schema"):
            helper.load_config()

    def test_atomic_config_mode_and_mount_limit(self):
        helper.atomic_write_config({"version": 1, "mounts": []})
        self.assertEqual(stat.S_IMODE(helper.CONFIG_FILE.stat().st_mode), 0o600)
        with self.assertRaises(helper.HelperError):
            helper.atomic_write_config({"version": 1, "mounts": [self.nfs(str(i)) for i in range(33)]})

    def test_findmnt_parent_filesystem_is_not_exact_and_never_unmounted(self):
        target = helper.MANAGED_BASE / helper.mount_id(self.nfs())
        parent = {"filesystems": [{"target": "/", "source": "/dev/root", "fstype": "ext4", "options": "rw"}]}
        completed = subprocess.CompletedProcess([], 0, json.dumps(parent), "")
        with mock.patch.object(helper, "run", return_value=completed) as runner:
            self.assertIsNone(helper.findmnt(target))
            self.assertFalse(helper.unmount_target(target))
        self.assertFalse(any(call.args[0][0] == "umount" for call in runner.call_args_list))

    def test_mounted_ok_requires_exact_target(self):
        parent = {"target": "/", "source": "192.168.1.20:/Music", "fstype": "nfs", "options": "ro"}
        with mock.patch.object(helper, "findmnt", return_value=parent):
            self.assertFalse(helper.mounted_ok(self.nfs()))

    def _mount_state_runner(self, returncode=0):
        state = {"mounted": False}
        calls = []

        def findmnt(target):
            if not state["mounted"]:
                return None
            return {"target": str(target), "source": helper.source_for(self._active),
                    "fstype": "cifs" if self._active["protocol"] == "smb" else "nfs", "options": "ro"}

        def run(argv, timeout=helper.COMMAND_TIMEOUT):
            calls.append(argv)
            if argv[0] == "mount":
                state["mounted"] = True
                return subprocess.CompletedProcess(argv, returncode, "", "mount failed" if returncode else "")
            if argv[0] == "umount":
                state["mounted"] = False
            return subprocess.CompletedProcess(argv, 0, "", "")

        return state, calls, findmnt, run

    def test_failed_mount_command_rolls_back_mount_temp_credential_and_directory(self):
        self._active = self.smb(username="me", password="secret")
        state, calls, finder, runner = self._mount_state_runner(returncode=1)
        with mock.patch.object(helper, "findmnt", side_effect=finder), mock.patch.object(helper, "run", side_effect=runner):
            with self.assertRaises(helper.HelperError):
                helper.mount_defn(self._active)
        self.assertFalse(state["mounted"])
        self.assertTrue(any(argv[0] == "umount" for argv in calls))
        self.assertFalse(helper.mount_path(self._active).exists())
        self.assertEqual(list(helper.CREDENTIAL_DIR.glob("*")), [])

    def test_new_mount_response_reports_created_mount_true(self):
        self._active = self.nfs()
        state, _calls, finder, runner = self._mount_state_runner()
        with mock.patch.object(helper, "findmnt", side_effect=finder), \
                mock.patch.object(helper, "run", side_effect=runner), \
                mock.patch.object(helper, "mounted_ok", side_effect=lambda _d: state["mounted"]):
            result = helper.mount_defn(self._active, persist=False)
        self.assertIs(result["created_mount"], True)

    def test_existing_exact_mount_response_reports_created_mount_false(self):
        definition = self.nfs()
        exact = {"target": str(helper.mount_path(definition))}
        with mock.patch.object(helper, "findmnt", return_value=exact), \
                mock.patch.object(helper, "mounted_ok", return_value=True), \
                mock.patch.object(helper, "run") as runner:
            result = helper.mount_defn(definition, persist=False)
        self.assertIs(result["created_mount"], False)
        self.assertFalse(any(call.args[0][0] in ("mount", "umount") for call in runner.call_args_list))

    def test_failed_verification_unmounts_exact_new_mount(self):
        self._active = self.nfs()
        state, calls, finder, runner = self._mount_state_runner()
        with mock.patch.object(helper, "findmnt", side_effect=finder), \
                mock.patch.object(helper, "run", side_effect=runner), \
                mock.patch.object(helper, "mounted_ok", return_value=False):
            with self.assertRaisesRegex(helper.HelperError, "verification"):
                helper.mount_defn(self._active)
        self.assertFalse(state["mounted"])
        self.assertTrue(any(argv[0] == "umount" for argv in calls))

    def test_config_failure_rolls_back_mount_and_restores_old_credentials(self):
        self._active = self.smb(username="new", password="new-secret")
        mid = helper.mount_id(self._active)
        helper.ensure_dirs()
        old_path = helper.credential_path(mid)
        old_path.write_text("username=old\npassword=old-secret\n", encoding="utf-8")
        os.chmod(old_path, 0o600)
        state, calls, finder, runner = self._mount_state_runner()
        with mock.patch.object(helper, "findmnt", side_effect=finder), \
                mock.patch.object(helper, "run", side_effect=runner), \
                mock.patch.object(helper, "mounted_ok", side_effect=lambda _d: state["mounted"]), \
                mock.patch.object(helper, "atomic_write_config", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                helper.mount_defn(self._active)
        self.assertFalse(state["mounted"])
        self.assertIn("old-secret", old_path.read_text(encoding="utf-8"))
        self.assertNotIn("new-secret", old_path.read_text(encoding="utf-8"))
        self.assertEqual(list(helper.CREDENTIAL_DIR.glob("*.tmp")), [])
        self.assertEqual(list(helper.CREDENTIAL_DIR.glob("*.backup")), [])

    def test_config_failure_removes_new_credential_when_none_existed(self):
        self._active = self.smb(username="new", password="new-secret")
        persistent = helper.credential_path(helper.mount_id(self._active))
        state, _calls, finder, runner = self._mount_state_runner()
        with mock.patch.object(helper, "findmnt", side_effect=finder), \
                mock.patch.object(helper, "run", side_effect=runner), \
                mock.patch.object(helper, "mounted_ok", side_effect=lambda _d: state["mounted"]), \
                mock.patch.object(helper, "atomic_write_config", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                helper.mount_defn(self._active)
        self.assertFalse(state["mounted"])
        self.assertFalse(persistent.exists())

    def test_failure_immediately_after_credential_replace_restores_backup(self):
        self._active = self.smb(username="new", password="new-secret")
        mid = helper.mount_id(self._active)
        helper.ensure_dirs()
        persistent = helper.credential_path(mid)
        persistent.write_text("username=old\npassword=old-secret\n", encoding="utf-8")
        os.chmod(persistent, 0o600)
        state, calls, finder, runner = self._mount_state_runner()
        real_chmod = os.chmod
        failed = {"value": False}

        def fail_promoted_chmod(path, mode, **kwargs):
            if Path(path) == persistent and not failed["value"] and "new-secret" in persistent.read_text(encoding="utf-8"):
                failed["value"] = True
                raise OSError("chmod failed")
            return real_chmod(path, mode, **kwargs)

        with mock.patch.object(helper, "findmnt", side_effect=finder), \
                mock.patch.object(helper, "run", side_effect=runner), \
                mock.patch.object(helper, "mounted_ok", side_effect=lambda _d: state["mounted"]), \
                mock.patch.object(helper.os, "chmod", side_effect=fail_promoted_chmod):
            with self.assertRaisesRegex(OSError, "chmod failed"):
                helper.mount_defn(self._active)
        self.assertFalse(state["mounted"])
        self.assertIn("old-secret", persistent.read_text(encoding="utf-8"))
        self.assertNotIn("new-secret", persistent.read_text(encoding="utf-8"))
        self.assertEqual(list(helper.CREDENTIAL_DIR.glob("*.tmp")), [])
        self.assertEqual(list(helper.CREDENTIAL_DIR.glob("*.backup")), [])
        self.assertTrue(any(argv[0] == "umount" for argv in calls))

    def test_existing_mount_is_never_unmounted_on_persistence_failure(self):
        definition = self.nfs()
        exact = {"target": str(helper.mount_path(definition))}
        with mock.patch.object(helper, "findmnt", return_value=exact), \
                mock.patch.object(helper, "mounted_ok", return_value=True), \
                mock.patch.object(helper, "atomic_write_config", side_effect=OSError("full")), \
                mock.patch.object(helper, "run") as runner:
            with self.assertRaises(OSError):
                helper.mount_defn(definition)
        self.assertFalse(any(call.args[0][0] == "umount" for call in runner.call_args_list))

    def test_disconnect_offline_writes_config_before_removing_credentials_and_directory(self):
        definition = helper.validate_definition(self.smb())
        mid = definition["id"]
        helper.ensure_dirs()
        target = helper.mount_path(definition)
        target.mkdir()
        cred = helper.credential_path(mid)
        cred.write_text("old", encoding="utf-8")
        events = []
        with mock.patch.object(helper, "load_config", return_value=self.config_with(definition)), \
                mock.patch.object(helper, "findmnt", return_value=None), \
                mock.patch.object(helper, "atomic_write_config", side_effect=lambda _data: events.append("config")), \
                mock.patch.object(helper, "remove_credentials", side_effect=lambda _mid: (events.append("credential"), cred.unlink())):
            result = helper.action_disconnect({"id": mid})
        self.assertEqual(events, ["config", "credential"])
        self.assertFalse(target.exists())
        self.assertEqual(result["mount_path"], str(target))

    def test_disconnect_config_failure_preserves_definition_and_credential(self):
        definition = helper.validate_definition(self.smb())
        helper.ensure_dirs()
        cred = helper.credential_path(definition["id"])
        cred.write_text("saved", encoding="utf-8")
        with mock.patch.object(helper, "load_config", return_value=self.config_with(definition)), \
                mock.patch.object(helper, "unmount_target", return_value=True), \
                mock.patch.object(helper, "atomic_write_config", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                helper.action_disconnect({"id": definition["id"]})
        self.assertTrue(cred.exists())

    def test_unmount_all_continues_across_mounted_offline_and_failure(self):
        one, offline, failing = self.nfs("192.168.1.1"), self.nfs("192.168.1.2"), self.smb()
        config = self.config_with(one, offline, failing)
        targets = {str(helper.mount_path(item)): item for item in config["mounts"]}

        def unmount(target):
            item = targets[str(target)]
            if item["host"] == "nas.local":
                raise helper.HelperError("busy")
            return item["host"] == "192.168.1.1"

        with mock.patch.object(helper, "load_config", return_value=config), mock.patch.object(helper, "unmount_target", side_effect=unmount):
            result = helper.action_unmount_all({})
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["unmounted"]), 1)
        self.assertEqual(len(result["failed"]), 1)

    def test_busy_lock_returns_bounded_clear_error(self):
        helper.LOCK_FILE.parent.mkdir(parents=True)
        fd = os.open(helper.LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with self.assertRaisesRegex(helper.HelperError, "busy"):
                with helper.operation_lock(timeout=0.03):
                    self.fail("contended lock was acquired")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_normal_lock_acquisition_is_bounded_and_mode_is_private(self):
        helper.LOCK_FILE.parent.mkdir(parents=True)
        with helper.operation_lock(timeout=0.1):
            self.assertTrue(helper.LOCK_FILE.is_file())
            self.assertEqual(stat.S_IMODE(helper.LOCK_FILE.stat().st_mode), 0o600)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW is unavailable")
    def test_symlink_lock_is_rejected(self):
        helper.LOCK_FILE.parent.mkdir(parents=True)
        target = helper.LOCK_FILE.parent / "target"
        target.write_text("unchanged", encoding="utf-8")
        helper.LOCK_FILE.symlink_to(target)
        with self.assertRaisesRegex(helper.HelperError, "safely"):
            with helper.operation_lock(timeout=0.01):
                self.fail("symlink lock was accepted")
        self.assertEqual(target.read_text(encoding="utf-8"), "unchanged")

    def test_non_regular_lock_file_is_rejected(self):
        helper.LOCK_FILE.parent.mkdir(parents=True)
        helper.LOCK_FILE.mkdir()
        with self.assertRaises(helper.HelperError):
            with helper.operation_lock(timeout=0.01):
                self.fail("non-regular lock was accepted")

    def test_mount_argv_is_read_only_and_never_contains_password(self):
        self._active = self.smb(username="me", password="secret")
        state, calls, finder, runner = self._mount_state_runner()
        with mock.patch.object(helper, "findmnt", side_effect=finder), mock.patch.object(helper, "run", side_effect=runner), \
                mock.patch.object(helper, "mounted_ok", side_effect=lambda _d: state["mounted"]):
            helper.mount_defn(self._active, persist=False)
        mount_argv = next(argv for argv in calls if argv[0] == "mount")
        self.assertNotIn("secret", " ".join(mount_argv))
        for option in ("ro", "nosuid", "nodev", "noexec"):
            self.assertIn(option, mount_argv[4].split(","))


if __name__ == "__main__":
    unittest.main()
