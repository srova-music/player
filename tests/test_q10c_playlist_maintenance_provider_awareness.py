import ast
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

BACKEND = (
    ROOT / "src/main_headless.py"
).read_text(encoding="utf-8")

UI = (
    ROOT / "src/ui_web/ui.js"
).read_text(encoding="utf-8")

INDEX = (
    ROOT / "src/ui_web/index.html"
).read_text(encoding="utf-8")

QOBUZ = (
    ROOT / "src/backend/qobuz.py"
).read_text(encoding="utf-8")


FUNCTIONS = {
    "_normalise_playlist_maintenance_provider",
    "_playlist_maintenance_saved_provider",
    "_qobuz_playlist_maintenance_available",
    "_effective_playlist_maintenance_provider",
    "_playlist_maintenance_settings_state",
    "_set_playlist_maintenance_settings",
}


class FakeLogger:
    def debug(self, *args, **kwargs):
        pass


class FakeQobuz:
    def __init__(self, usable):
        self.usable = usable

    def status(self):
        return {"usable": self.usable}


class FakeApp:
    def __init__(self, usable):
        self.qobuz_backend = FakeQobuz(usable)


def provider_model(saved, tidal, qobuz):
    tree = ast.parse(BACKEND)

    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in FUNCTIONS
        )
    ]

    assert {
        node.name
        for node in nodes
    } == FUNCTIONS

    namespace = {
        "_APP_SETTINGS": {
            "playlist_maintenance_provider": saved,
            "infinite_play_provider": "tidal",
            "automix_provider": "qobuz",
        },
        "_APP_SETTINGS_LOCK": threading.RLock(),
        "APP_INSTANCE": FakeApp(qobuz),
        "_tidal_login_snapshot": (
            lambda: object() if tidal else None
        ),
        "_save_app_settings": lambda: None,
        "logger": FakeLogger(),
    }

    exec(
        compile(
            ast.Module(
                body=nodes,
                type_ignores=[],
            ),
            "<q10c-provider-model>",
            "exec",
        ),
        namespace,
    )

    return namespace


@pytest.mark.parametrize(
    "saved,tidal,qobuz,expected",
    [
        ("tidal", True, True, "tidal"),
        ("qobuz", True, True, "qobuz"),
        ("qobuz", True, False, "tidal"),
        ("tidal", False, True, "qobuz"),
        ("qobuz", False, False, None),
    ],
)
def test_saved_effective_matrix(
    saved,
    tidal,
    qobuz,
    expected,
):
    ns = provider_model(
        saved,
        tidal,
        qobuz,
    )

    assert (
        ns[
            "_effective_playlist_maintenance_provider"
        ]()
        == expected
    )

    assert (
        ns["_APP_SETTINGS"][
            "playlist_maintenance_provider"
        ]
        == saved
    )


def test_saved_preference_restores_after_auth_returns():
    ns = provider_model(
        "qobuz",
        True,
        False,
    )

    effective = ns[
        "_effective_playlist_maintenance_provider"
    ]

    assert effective() == "tidal"

    ns["APP_INSTANCE"].qobuz_backend.usable = True

    assert effective() == "qobuz"

    assert (
        ns["_APP_SETTINGS"][
            "playlist_maintenance_provider"
        ]
        == "qobuz"
    )


def test_provider_setting_is_independent():
    ns = provider_model(
        "tidal",
        True,
        True,
    )

    before_inf = ns["_APP_SETTINGS"][
        "infinite_play_provider"
    ]

    before_mix = ns["_APP_SETTINGS"][
        "automix_provider"
    ]

    result = ns[
        "_set_playlist_maintenance_settings"
    ](
        provider="qobuz"
    )

    assert result["provider"] == "qobuz"
    assert result["effective_provider"] == "qobuz"

    assert ns["_APP_SETTINGS"][
        "infinite_play_provider"
    ] == before_inf

    assert ns["_APP_SETTINGS"][
        "automix_provider"
    ] == before_mix


def test_provider_selector_reuses_q9d_model():
    block = UI[
        UI.index(
            "function buildPlaylistMaintenanceSection("
        ):
        UI.index(
            "function _dupRow("
        )
    ]

    assert "buildQ9dProviderSelector(" in block
    assert '"playlist_maintenance"' in block
    assert (
        '"/api/settings/playlist-maintenance"'
        in UI
    )


def test_qobuz_refresh_does_not_touch_tidal_cache():
    block = UI[
        UI.index(
            'if (provider === "qobuz")'
        ):
        UI.index(
            'status.textContent = "Clearing cache...";'
        )
    ]

    assert (
        '"/qobuz/catalog?op=playlists&_="'
        in block
    )

    assert '"/cache/clear"' not in block
    assert '"/tidal/myplaylists"' not in block


def test_qobuz_scan_uses_owned_complete_playlists():
    block = BACKEND[
        BACKEND.index(
            "def _qobuz_playlist_duplicate_scan():"
        ):
        BACKEND.index(
            "def _provider_radio_visibility_settings():"
        )
    ]

    assert (
        "backend.get_user_playlists()"
        in block
    )

    assert (
        '"playlist_editable"'
        in block
    )

    assert (
        "_complete_streaming_playlist_payload("
        in block
    )

    assert ") <= 30" in block
    assert "reverse=True" in block


def test_tidal_mature_duplicate_path_is_preserved():
    assert (
        'if self.path == '
        '"/tidal/playlists/find_duplicates":'
        in BACKEND
    )

    assert (
        "backend.session.playlist(pl_id)"
        in BACKEND
    )

    assert (
        "tracks = pl_obj.items()"
        in BACKEND
    )

    assert (
        'if self.path == '
        '"/tidal/playlists/delete_duplicates":'
        in BACKEND
    )


def test_qobuz_delete_uses_existing_safe_backend():
    start = BACKEND.index(
        'if self.path == '
        '"/qobuz/playlists/delete_duplicates":'
    )

    end = BACKEND.index(
        "# -- Auto-Mix: create playlist",
        start,
    )

    block = BACKEND[start:end]

    assert "backend.delete_playlist(" in block
    assert "backend._catalog_request(" not in block
    assert "/playlist/delete" not in block

    assert "def delete_playlist(" in QOBUZ


def test_provider_specific_delete_dispatch():
    block = UI[
        UI.index(
            "function renderDupResults("
        ):
        UI.index(
            "function _dupRow("
        )
    ]

    assert (
        '"/qobuz/playlists/delete_duplicates"'
        in block
    )

    assert (
        '"/tidal/playlists/delete_duplicates"'
        in block
    )

    assert "qobuzPlaylistsLoaded =" in block
    assert "playlistsLoaded =" in block


def test_cache_token_preserves_q9d_ancestry():
    assert (
        "/ui_web/ui.js?"
        "v=20260912_v2_0_q10a_infinite_play_pause_logo_js4"
        in INDEX
    )

    assert (
        "_q10c_playlist_maintenance_provider_js8"
        in INDEX
    )

    assert INDEX.count(
        "/ui_web/ui.js?v="
    ) == 1
