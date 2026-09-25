from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

UI = (
    ROOT
    / "src"
    / "ui_web"
    / "ui.js"
).read_text(
    encoding="utf-8"
)

INDEX = (
    ROOT
    / "src"
    / "ui_web"
    / "index.html"
).read_text(
    encoding="utf-8"
)

CSS = (
    ROOT
    / "src"
    / "ui_web"
    / "srova.css"
).read_text(
    encoding="utf-8"
)

MAIN = (
    ROOT
    / "src"
    / "main_headless.py"
).read_text(
    encoding="utf-8"
)

QOBUZ = (
    ROOT
    / "src"
    / "backend"
    / "qobuz.py"
).read_text(
    encoding="utf-8"
)


def test_q10d_ux_has_two_explicit_sign_in_choices():
    assert (
        '"Sign In with SROVA Remote"'
        in UI
    )

    assert (
        '"Sign In with Browser"'
        in UI
    )

    assert (
        '"Sign in to Qobuz. Choose how you are using SROVA."'
        in UI
    )

    assert (
        '"Choose a sign-in method"'
        in UI
    )


def test_q10d_ux_keeps_both_choices_as_real_links():
    assert (
        'id="loginUrl"'
        in INDEX
    )

    assert (
        'var link ='
        in UI
    )

    assert (
        'document.createElement('
        in UI
    )

    assert (
        '"a"'
        in UI
    )

    assert (
        'link.href ='
        in UI
    )

    assert (
        'loginUrlEl.href ='
        in UI
    )


def test_q10d_ux_hides_callback_completion_until_browser_choice():
    assert (
        "function showQobuzBrowserCompletionPanel()"
        in UI
    )

    assert (
        "qobuzCompletePanel.classList.add("
        in UI
    )

    assert (
        "showQobuzBrowserCompletionPanel();"
        in UI
    )


def test_q10d_ux_masks_raw_primary_qobuz_url():
    start = UI.index(
        "function startQobuzLogin("
    )

    end = UI.index(
        "function cancelQobuzLogin(",
        start,
    )

    block = UI[start:end]

    assert (
        "loginUrlEl.href ="
        in block
    )

    assert (
        "prepareQobuzRemoteSignInLink();"
        in block
    )

    assert (
        "loginUrlEl.textContent =\n"
        "            String(data.url);"
        not in block
    )


def test_q10d_ux_keeps_explicit_mode_selection_without_guessing():
    start = UI.index(
        "function startQobuzLogin("
    )

    end = UI.index(
        "function cancelQobuzLogin(",
        start,
    )

    block = UI[start:end]

    assert (
        "navigator.userAgent"
        not in block
    )

    assert (
        "Android"
        not in block
    )


def test_q10d_handoff_page_uses_srova_theme():
    assert (
        "qobuzHandoffBody"
        in MAIN
    )

    assert (
        "qobuzHandoffCard"
        in MAIN
    )

    assert (
        "qobuzHandoffWordmark"
        in MAIN
    )

    assert (
        "QOBUZ"
        in MAIN
    )

    assert (
        "/* Q10D AUTH UX REFINEMENT */"
        in CSS
    )

    assert (
        ".qobuzHandoffBody"
        in CSS
    )

    assert (
        ".qobuzHandoffCard"
        in CSS
    )


def test_q10d_handoff_keeps_required_copy():
    assert (
        "Sign-in complete"
        in MAIN
    )

    assert (
        "Copy the full URL shown in your "
        in MAIN
    )

    assert (
        "browser's address bar."
        in MAIN
    )

    assert (
        "Paste it into the open SROVA popup "
        in MAIN
    )

    assert (
        "to finish signing in."
        in MAIN
    )

    assert (
        "Sign-in couldn't be completed"
        in MAIN
    )

    assert (
        "Return to SROVA and start the Qobuz "
        in MAIN
    )


def test_q10d_handoff_security_allows_only_same_origin_assets():
    assert (
        "style-src 'self'"
        in MAIN
    )

    assert (
        "img-src 'self'"
        in MAIN
    )

    assert (
        '"Referrer-Policy",'
        in MAIN
    )

    assert (
        '"no-referrer",'
        in MAIN
    )

    assert (
        '"Cache-Control",'
        in MAIN
    )

    assert (
        '"no-store",'
        in MAIN
    )


def test_q10d_ux_cache_keys_advanced():
    assert (
        "q10d_auth_ux_css2"
        in INDEX
    )

    assert (
        "q10d_auth_ux_js10"
        in INDEX
    )


def test_q10d_core_remote_callback_contract_remains_present():
    assert (
        'redirect = f"http://localhost:{port}/{nonce}"'
        in QOBUZ
    )

    assert (
        'listener.bind(("127.0.0.1", 0))'
        in QOBUZ
    )

    assert (
        '"manual_url": manual_login_url'
        in QOBUZ
    )
