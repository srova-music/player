from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = (ROOT / "src" / "ui_web" / "ui.js").read_text(encoding="utf-8")


def _slice(start_marker: str, end_marker: str) -> str:
    start = UI_SOURCE.index(start_marker)
    end = UI_SOURCE.index(end_marker, start)
    return UI_SOURCE[start:end]


def test_radio_source_has_in_memory_page_cache_and_stable_station_signature():
    assert "var _radioSourcePageCache = null;" in UI_SOURCE
    assert "var _radioSourceStationSignature = \"\";" in UI_SOURCE
    assert "function radioStationSignature(stations)" in UI_SOURCE

    signature = _slice(
        "function radioStationSignature(stations)",
        "function invalidateRadioSourceCache()",
    )

    # Station order and artwork identity must participate in the signature.
    assert "station.id" in signature
    assert "station.name" in signature
    assert "station.url" in signature
    assert "station.icon" in signature
    assert "station.image_url" in signature
    assert "station.icon || station.image_url" in signature
    assert ".map(" in signature
    assert ".join(" in signature


def test_radio_source_reuses_cached_dom_and_validates_station_data():
    source = _slice(
        "function showRadioSource(preserveReorderMode, setupVerified)",
        "function tidalSourceSearchHasResults",
    )

    assert "if (_radioSourcePageCache)" in source
    assert "homeSections.appendChild(_radioSourcePageCache);" in source
    assert "refreshRadioSourceCache();" in source

    # A cached return must not synchronously rebuild the Radio shelf.
    reuse_pos = source.index("if (_radioSourcePageCache)")
    append_pos = source.index("homeSections.appendChild(_radioSourcePageCache);")
    refresh_pos = source.index("refreshRadioSourceCache();")
    build_pos = source.index("buildRadioShelf(")

    assert reuse_pos < append_pos < refresh_pos < build_pos


def test_radio_cache_refresh_rebuilds_only_when_station_signature_changes():
    refresh = _slice(
        "function refreshRadioSourceCache()",
        "function buildRadioShelf(onReady)",
    )

    assert 'fetch("/api/radio/stations")' in refresh
    assert "radioStationSignature(stations)" in refresh
    assert "_radioSourceStationSignature" in refresh
    assert "if (signature === _radioSourceStationSignature)" in refresh
    assert "invalidateRadioSourceCache();" in refresh
    assert "showRadioSource(false, true);" in refresh


def test_radio_crud_and_reorder_keep_cache_invalidation_correct():
    submit = _slice(
        "function submitAddRadio()",
        "function deleteRadioStation(id)",
    )
    delete = _slice(
        "function deleteRadioStation(id)",
        "function buildRadioSection()",
    )
    reorder = _slice(
        "function persistRadioStationOrder(items)",
        "function buildRadioShelf(onReady)",
    )

    # Add/edit/delete must discard cached station DOM so changed artwork can appear.
    assert "invalidateRadioSourceCache();" in submit
    assert "invalidateRadioSourceCache();" in delete

    # Successful drag reorder keeps the same image nodes but updates the
    # deterministic signature to the newly persisted order.
    assert "_radioSourceStationSignature = radioStationSignature(reordered);" in reorder
