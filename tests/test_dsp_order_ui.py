import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app_builders as mod


def test_apply_dsp_order_persists_and_rebuilds():
    calls = []

    class _Player:
        def set_dsp_order(self, order):
            calls.append(("player", list(order)))
            return True

    app = SimpleNamespace(
        player=_Player(),
        settings={},
        schedule_save_settings=lambda: calls.append(("save",)),
        _rebuild_dsp_overview_chain=lambda: calls.append(("rebuild",)),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
    )

    assert mod._apply_dsp_order(app, ["tube", "peq", "widener", "convolver", "tape"]) is True
    assert app.settings["dsp_order"] == ["tube", "peq", "widener", "convolver", "tape"]
    assert calls == [
        ("player", ["tube", "peq", "widener", "convolver", "tape"]),
        ("save",),
        ("rebuild",),
        ("ui",),
    ]


def test_on_dsp_order_drop_updates_pending_only_while_editing():
    calls = []
    app = SimpleNamespace(
        settings={"dsp_order": ["peq", "convolver", "tape", "tube", "widener"]},
        _dsp_order_editing=True,
        _dsp_order_pending=["peq", "convolver", "tape", "tube", "widener"],
        _rebuild_dsp_overview_chain=lambda: calls.append(("rebuild",)),
        _refresh_dsp_order_edit_ui=lambda: calls.append(("refresh",)),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
    )

    assert mod._on_dsp_order_drop(app, "tube", "convolver") is True
    assert app._dsp_order_pending == ["peq", "tube", "convolver", "tape", "widener"]
    assert calls == [("rebuild",), ("refresh",), ("ui",)]


def test_on_dsp_order_drop_moves_forward_after_target():
    calls = []
    app = SimpleNamespace(
        settings={"dsp_order": ["peq", "convolver", "tape", "tube", "widener"]},
        _dsp_order_editing=True,
        _dsp_order_pending=["peq", "convolver", "tape", "tube", "widener"],
        _rebuild_dsp_overview_chain=lambda: calls.append(("rebuild",)),
        _refresh_dsp_order_edit_ui=lambda: calls.append(("refresh",)),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
    )

    assert mod._on_dsp_order_drop(app, "peq", "tube") is True
    assert app._dsp_order_pending == ["convolver", "tape", "tube", "peq", "widener"]
    assert calls == [("rebuild",), ("refresh",), ("ui",)]


def test_on_dsp_order_drop_ignored_when_not_editing():
    app = SimpleNamespace(
        settings={"dsp_order": ["peq", "convolver", "tape", "tube", "widener"]},
        _dsp_order_editing=False,
        _dsp_order_pending=["peq", "convolver", "tape", "tube", "widener"],
    )

    assert mod._on_dsp_order_drop(app, "peq", "tube") is False
    assert app._dsp_order_pending == ["peq", "convolver", "tape", "tube", "widener"]


def test_on_dsp_order_drop_supports_lv2_slots():
    calls = []
    app = SimpleNamespace(
        settings={"dsp_order": ["peq", "lv2_0", "convolver", "tape", "tube", "widener"]},
        _dsp_order_editing=True,
        _dsp_order_pending=["peq", "lv2_0", "convolver", "tape", "tube", "widener"],
        _rebuild_dsp_overview_chain=lambda: calls.append(("rebuild",)),
        _refresh_dsp_order_edit_ui=lambda: calls.append(("refresh",)),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
    )

    assert mod._on_dsp_order_drop(app, "lv2_0", "tube") is True
    assert app._dsp_order_pending == ["peq", "convolver", "tape", "tube", "lv2_0", "widener"]
    assert calls == [("rebuild",), ("refresh",), ("ui",)]


def test_save_dsp_order_edit_applies_pending_once():
    calls = []

    app = SimpleNamespace(
        _dsp_order_editing=True,
        _dsp_order_pending=["tube", "peq", "widener", "convolver", "tape"],
        _apply_dsp_order=lambda order, save=True: calls.append(("apply", list(order), bool(save))) or True,
        _rebuild_dsp_overview_chain=lambda: calls.append(("rebuild",)),
        _refresh_dsp_order_edit_ui=lambda: calls.append(("refresh",)),
        _update_dsp_ui_state=lambda: calls.append(("ui",)),
        show_output_notice=lambda text, state, timeout: calls.append(("notice", text, state, timeout)),
    )

    original_restart = mod._lv2_restart_playback_for_graph_rebind
    mod._lv2_restart_playback_for_graph_rebind = lambda self: calls.append(("restart",))
    try:
        mod._save_dsp_order_edit(app)
    finally:
        mod._lv2_restart_playback_for_graph_rebind = original_restart

    assert app._dsp_order_editing is False
    assert app._dsp_order_pending is None
    assert calls == [
        ("apply", ["tube", "peq", "widener", "convolver", "tape"], True),
        ("rebuild",),
        ("refresh",),
        ("ui",),
        ("restart",),
        ("notice", "DSP chain order saved", "ok", 2200),
    ]


def test_rebuild_dsp_overview_chain_includes_lv2_slots_from_order():
    attached = []

    class _Flow:
        def get_first_child(self):
            return None

        def remove(self, child):
            raise AssertionError(
                "remove should not be called when grid is empty"
            )

        def attach(self, child, column, row, width, height):
            attached.append(
                (child, column, row, width, height)
            )

    app = SimpleNamespace(
        dsp_chain_flow=_Flow(),
        settings={
            "dsp_order": [
                "peq",
                "lv2_0",
                "convolver",
                "tape",
                "tube",
                "widener",
            ]
        },
        _dsp_order_editing=False,
        _dsp_order_pending=None,
        _dsp_overview_modules_per_row_cached=4,
        dsp_overview_module_buttons={},
        _lv2_get_plugin_meta=lambda slot_id: (
            {"name": "Auto phaser"}
            if slot_id == "lv2_0"
            else None
        ),
        player=SimpleNamespace(
            lv2_slots={
                "lv2_0": {
                    "uri": "http://example.com/auto_phaser",
                    "enabled": True,
                }
            }
        ),
    )

    original_cell = mod._build_dsp_overview_module_cell
    original_horizontal = (
        mod._build_dsp_chain_horizontal_connector
    )
    original_vertical = (
        mod._build_dsp_chain_vertical_connector
    )

    def _fake_module_cell(
        _app,
        module_id,
        title,
        target_module=None,
        row_index=0,
    ):
        return {
            "module_id": module_id,
            "title": title,
            "target_module": target_module,
            "row_index": row_index,
        }

    try:
        mod._build_dsp_overview_module_cell = (
            _fake_module_cell
        )
        mod._build_dsp_chain_horizontal_connector = (
            lambda reverse=False: object()
        )
        mod._build_dsp_chain_vertical_connector = (
            lambda: object()
        )

        mod._rebuild_dsp_overview_chain(app)
    finally:
        mod._build_dsp_overview_module_cell = (
            original_cell
        )
        mod._build_dsp_chain_horizontal_connector = (
            original_horizontal
        )
        mod._build_dsp_chain_vertical_connector = (
            original_vertical
        )

    module_cells = [
        item[0]
        for item in attached
        if isinstance(item[0], dict)
        and "module_id" in item[0]
    ]

    modules = [
        cell["module_id"]
        for cell in module_cells
    ]
    titles = {
        cell["module_id"]: cell["title"]
        for cell in module_cells
    }

    assert "lv2_0" in modules
    assert titles["lv2_0"] == "Auto phaser"


def test_build_dsp_overview_module_row_marks_lv2_as_reorderable():
    class _Button:
        def __init__(self, **kwargs):
            self.controllers = []
            self.child = None

        def set_size_request(self, *_args):
            pass

        def set_child(self, child):
            self.child = child

        def connect(self, *_args, **_kwargs):
            return 1

        def set_can_focus(self, *_args):
            pass

        def add_controller(self, controller):
            self.controllers.append(controller)

    class _Box:
        def __init__(self, *args, **kwargs):
            self.children = []

        def append(self, child):
            self.children.append(child)

    class _Overlay:
        def __init__(self, *args, **kwargs):
            self.child = None
            self.overlays = []

        def set_child(self, child):
            self.child = child

        def add_overlay(self, child):
            self.overlays.append(child)

    class _Image:
        def __init__(self):
            self.controllers = []

        def add_css_class(self, *_args):
            pass

        def set_halign(self, *_args):
            pass

        def set_valign(self, *_args):
            pass

        def set_margin_top(self, *_args):
            pass

        def set_margin_start(self, *_args):
            pass

        def set_cursor_from_name(self, *_args):
            pass

        def add_controller(self, controller):
            self.controllers.append(controller)

    class _Drag:
        def set_actions(self, *_args):
            pass

        def connect(self, *_args, **_kwargs):
            return 1

    class _Drop:
        def connect(self, *_args, **_kwargs):
            return 1

    original_button = mod.Gtk.Button
    original_box = mod.Gtk.Box
    original_label = mod.Gtk.Label
    original_overlay = mod.Gtk.Overlay
    original_image = mod.Gtk.Image
    original_drag = mod.Gtk.DragSource
    original_drop = mod.Gtk.DropTarget

    try:
        mod.Gtk.Button = _Button
        mod.Gtk.Box = _Box
        mod.Gtk.Label = (
            lambda *args, **kwargs: object()
        )
        mod.Gtk.Overlay = _Overlay
        mod.Gtk.Image = SimpleNamespace(
            new_from_icon_name=(
                lambda *_args, **_kwargs: _Image()
            )
        )
        mod.Gtk.DragSource = SimpleNamespace(
            new=lambda: _Drag()
        )
        mod.Gtk.DropTarget = SimpleNamespace(
            new=lambda *_args, **_kwargs: _Drop()
        )

        app = SimpleNamespace(
            _dsp_order_editing=True,
            _on_dsp_order_drop=(
                lambda *_args, **_kwargs: True
            ),
            dsp_overview_module_buttons={},
        )

        button = mod._build_dsp_overview_module_row(
            app,
            "lv2_0",
            "Auto phaser",
            target_module="lv2_0",
            row_index=1,
        )
    finally:
        mod.Gtk.Button = original_button
        mod.Gtk.Box = original_box
        mod.Gtk.Label = original_label
        mod.Gtk.Overlay = original_overlay
        mod.Gtk.Image = original_image
        mod.Gtk.DragSource = original_drag
        mod.Gtk.DropTarget = original_drop

    handles = [
        child
        for child in button.child.overlays
        if isinstance(child, _Image)
    ]

    assert len(button.controllers) == 1
    assert len(handles) == 1
    assert len(handles[0].controllers) == 1
    assert app.dsp_overview_module_buttons["lv2_0"] is button
