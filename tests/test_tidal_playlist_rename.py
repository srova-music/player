import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from backend.tidal import TidalBackend


class FakePlaylist:
    def __init__(
        self,
        playlist_id="playlist-1",
        name="Original Name",
        creator_id="user-1",
        edit_result=True,
        edit_error=None,
    ):
        self.id = playlist_id
        self.name = name
        self.description = "Original description"
        self.creator = SimpleNamespace(id=creator_id)
        self.edit_result = edit_result
        self.edit_error = edit_error
        self.edit_calls = []

    def edit(self, title=None, description=None):
        self.edit_calls.append((title, description))
        if self.edit_error is not None:
            raise self.edit_error
        return self.edit_result


def make_backend(playlist, user_id="user-1"):
    backend = TidalBackend()
    user = SimpleNamespace(id=user_id)
    backend.user = user
    backend.session = SimpleNamespace(
        user=user,
        playlist=lambda _playlist_id: playlist,
    )
    return backend


class TidalPlaylistRenameTests(unittest.TestCase):
    def test_owned_playlist_rename_succeeds_and_trims_name(self):
        playlist = FakePlaylist()
        backend = make_backend(playlist)

        result = backend.rename_cloud_playlist(
            playlist.id,
            "  Renamed Playlist  ",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["playlist_id"], playlist.id)
        self.assertEqual(result["name"], "Renamed Playlist")
        self.assertEqual(playlist.name, "Renamed Playlist")
        self.assertEqual(
            playlist.edit_calls,
            [("Renamed Playlist", "Original description")],
        )

    def test_non_owned_playlist_is_not_editable(self):
        playlist = FakePlaylist(creator_id="different-user")
        backend = make_backend(playlist)

        result = backend.rename_cloud_playlist(
            playlist.id,
            "Not Allowed",
        )

        self.assertFalse(result["ok"])
        self.assertIn("not editable", result["error"])
        self.assertEqual(playlist.name, "Original Name")
        self.assertEqual(playlist.edit_calls, [])

    def test_blank_playlist_name_is_rejected(self):
        playlist = FakePlaylist()
        backend = make_backend(playlist)

        result = backend.rename_cloud_playlist(
            playlist.id,
            "   ",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "playlist name required")
        self.assertEqual(playlist.name, "Original Name")
        self.assertEqual(playlist.edit_calls, [])

    def test_tidal_rejection_preserves_old_name(self):
        playlist = FakePlaylist(edit_result=False)
        backend = make_backend(playlist)

        result = backend.rename_cloud_playlist(
            playlist.id,
            "Rejected Name",
        )

        self.assertFalse(result["ok"])
        self.assertIn("did not accept", result["error"])
        self.assertEqual(playlist.name, "Original Name")
        self.assertEqual(
            playlist.edit_calls,
            [("Rejected Name", "Original description")],
        )

    def test_tidal_exception_is_reported_and_old_name_survives(self):
        playlist = FakePlaylist(
            edit_error=RuntimeError("TIDAL test rejection"),
        )
        backend = make_backend(playlist)

        result = backend.rename_cloud_playlist(
            playlist.id,
            "Rejected Name",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "TIDAL test rejection")
        self.assertEqual(playlist.name, "Original Name")

    def test_http_contract_contains_ownership_metadata_and_rename_route(self):
        source = (
            REPO_ROOT / "src" / "main_headless.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '"playlist_editable": playlist_editable',
            source,
        )
        self.assertIn(
            'if self.path == "/tidal/playlist/rename":',
            source,
        )
        self.assertIn(
            'result = backend.rename_cloud_playlist(playlist_id, name)',
            source,
        )
        self.assertIn(
            'cache_invalidate("playlist:" + playlist_id)',
            source,
        )
        self.assertIn(
            '{"ok": False, "error": "playlist name required"}',
            source,
        )


    def test_ui_contract_is_ownership_gated_and_updates_in_place(self):
        ui_source = (
            REPO_ROOT / "src" / "ui_web" / "ui.js"
        ).read_text(encoding="utf-8")
        html = (
            REPO_ROOT / "src" / "ui_web" / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'return postJson("/tidal/playlist/rename"',
            ui_source,
        )
        self.assertIn(
            'currentContext.playlist_editable === true',
            ui_source,
        )
        self.assertIn(
            'renameBtn.id = "playlistRenameBtn"',
            ui_source,
        )
        self.assertIn(
            'updateTidalPlaylistNameInUi(',
            ui_source,
        )
        self.assertIn(
            '"data-playlist-id"',
            ui_source,
        )
        self.assertIn(
            'busyLabel: "Renaming..."',
            ui_source,
        )
        self.assertIn(
            'renderAlbumQueueBtn(\n                    [],',
            ui_source,
        )
        css_marker = '/ui_web/srova.css?v='
        js_marker = '/ui_web/ui.js?v='

        self.assertIn(css_marker, html)
        self.assertIn(js_marker, html)

        css_cache_key = html.split(css_marker, 1)[1].split('"', 1)[0]
        js_cache_key = html.split(js_marker, 1)[1].split('"', 1)[0]

        self.assertTrue(css_cache_key)
        self.assertTrue(js_cache_key)


if __name__ == "__main__":
    unittest.main()
