"""Run frontend UI tests in a headless Chromium browser via Playwright.

Starts a local HTTP server to serve the test HTML, then uses Playwright
to open the page and read test results from window._testResult.
"""

import contextlib
import json
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


@pytest.fixture(scope="module")
def _test_server():
    """Serve the project root so test_ui.html can load frontend/ files."""
    handler_cls = type(
        "_H", (SimpleHTTPRequestHandler,),
        {
            "__init__": lambda self, *a, **kw: SimpleHTTPRequestHandler.__init__(
                self, *a, directory=str(_PROJECT_ROOT), **kw),
            "log_message": lambda self, *a: None,
        },
    )
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_frontend_ui(_test_server):
    """Execute frontend tests in a headless Chromium browser."""
    port = _test_server
    url = f"http://127.0.0.1:{port}/tests/frontend/test_ui.html"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(msg.text))

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("window._testResult !== undefined", timeout=10000)

        result = page.evaluate("window._testResult")
        dom_text = page.evaluate("document.getElementById('test-output').innerText")
        browser.close()

    assert result, "window._testResult was not set by the test runner"
    total = result["passed"] + result["failed"]

    assert total > 0, "No tests were executed"
    if result["failed"] > 0:
        # Show only FAIL lines for concise output
        fail_lines = [ln for ln in dom_text.split("\n") if "FAIL" in ln]
        pytest.fail(
            f"{result['failed']}/{total} frontend tests failed:\n"
            + "\n".join(fail_lines)
        )
    print(f"\nFrontend tests: {result['passed']}/{total} passed")


def _gui_module(gui_module_name="analyze_spectrum.gui"):
    """The app's gui module, imported with pywebview mocked out."""
    import importlib
    from unittest.mock import MagicMock
    saved = sys.modules.get("webview")
    sys.modules["webview"] = MagicMock()
    try:
        return importlib.import_module(gui_module_name)
    finally:
        if saved is None:
            del sys.modules["webview"]
        else:
            sys.modules["webview"] = saved


def _app_server(gui_module_name):
    """Serve the real index.html, style.css and common.css through the app's handler."""
    from http.server import ThreadingHTTPServer
    gui_mod = _gui_module(gui_module_name)

    class _Server(ThreadingHTTPServer):
        request_queue_size = 64

    server = _Server(("127.0.0.1", 0), gui_mod.AnalyzeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_confirm_modal_buttons_are_44px_targets():
    """The confirm modal's OK / Cancel meet the 44 px touch-target height."""
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            page.evaluate("void _confirmModal('Proceed?', 'source.wav')")
            page.wait_for_selector(".modal-ok")
            for selector in (".modal-ok", ".modal-cancel"):
                height = page.evaluate(
                    f"document.querySelector('{selector}').getBoundingClientRect().height")
                assert height >= 44, f"{selector} is {height} px tall"
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_clear_all_button_is_at_least_36px_tall():
    """Clear All meets the 36 px desktop target height."""
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            for source in ("a.wav", "b.wav"):
                page.fill("#url-input", source)
                page.click("#add-btn")
            height = page.evaluate("document.getElementById('clear-btn').getBoundingClientRect().height")
            assert height >= 36, f"#clear-btn is {height} px tall"
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_theme_and_submit_labels_follow_the_state_after_load_and_language_switch():
    """main.js alone writes the theme button's accessible name and the submit
    button's text, so the translation pass of i18n.js at DOMContentLoaded and on
    a language switch does not replace them."""
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="ja-JP")
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            theme_state = "window.i18n.t('theme.aria_state.' + _themeMode)"
            assert page.evaluate("window.i18n.lang()") == "ja"
            assert page.get_attribute("#theme-toggle", "aria-label") == page.evaluate(theme_state)
            assert page.inner_text("#submit-btn") == page.evaluate("window.i18n.t('btn.analyze')")
            page.click("#lang-toggle")
            assert page.evaluate("window.i18n.lang()") == "en"
            assert page.get_attribute("#theme-toggle", "aria-label") == page.evaluate(theme_state)
            assert page.inner_text("#submit-btn") == page.evaluate("window.i18n.t('btn.analyze')")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_running_analysis_keeps_its_cancel_button_across_a_language_switch():
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="en-US")
            held = []
            page.route("**/analyze", lambda route: held.append(route))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            try:
                page.fill("#url-input", "x.wav")
                page.click("#submit-btn")
                page.wait_for_function("isBusy")
                page.click("#lang-toggle")
                assert page.evaluate("window.i18n.lang()") == "ja"
                assert page.evaluate("isBusy") is True
                assert page.inner_text("#submit-btn") == page.evaluate("window.i18n.t('btn.cancel')")
                assert page.get_attribute("#submit-btn", "aria-label") == page.evaluate("window.i18n.t('btn.cancel.aria')")
            finally:
                for route in held:
                    route.abort()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


_RESOLVE_VAR_JS = """(name) => {
  const probe = document.createElement("div");
  probe.style.background = "var(" + name + ")";
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).backgroundColor;
  probe.remove();
  return value;
}"""


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_interactive_states_follow_stylesheet_order(scheme):
    """Rules in common.css load before style.css; the states they style still win."""
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(color_scheme=scheme, reduced_motion="reduce")
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            btn_bg = "getComputedStyle(document.getElementById('submit-btn')).backgroundColor"

            page.evaluate("document.getElementById('submit-btn').classList.add('cancelling')")
            page.hover("#submit-btn")
            assert page.evaluate(btn_bg) == page.evaluate(_RESOLVE_VAR_JS, "--danger-hover")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


class _PageUpdater:
    """Fake analyze_common.update.Updater: offers ``offer`` and fails the install
    once ``release`` is set."""

    def __init__(self, offer, launch_check=True, install_result=None):
        self.offer = offer
        self.launch_check_on = launch_check
        self.install_result = install_result
        self.checks = 0
        self.installed = []
        self.saved = []
        self.release = threading.Event()
        # Set to hold that answer until the test sets the event.
        self.status_gate = None
        self.check_gate = None
        self.save_gate = None

    def gates(self):
        return [g for g in (self.release, self.status_gate, self.check_gate, self.save_gate) if g is not None]

    def status(self):
        if self.status_gate is not None:
            self.status_gate.wait(10)
        return {"current": "1.0.0", "supported": True, "launch_check": self.launch_check_on}

    def launch_check(self):
        return self.launch_check_on

    def set_launch_check(self, on):
        if self.save_gate is not None:
            self.save_gate.wait(10)
        self.saved.append(on)
        self.launch_check_on = on

    def check(self):
        if self.check_gate is not None:
            self.check_gate.wait(10)
        self.checks += 1
        return self.offer

    def install(self, version):
        from analyze_common.update import UpdateError
        self.installed.append(version)
        if self.install_result is not None:
            return self.install_result
        self.release.wait(10)
        raise UpdateError("bad signature")


_UPDATE_LOCKED = ("#url-input", "#browse-btn", "#submit-btn", "#add-btn", "#load-btn", "#settings-toggle")


@contextlib.contextmanager
def _update_page(updater, on_dialog, lang="en", prepare=None):
    """The real index.html, served with ``updater`` behind the update endpoints.
    ``lang`` is stored in the settings file first; ``prepare(page)`` runs
    before the page loads."""
    server = _app_server("analyze_spectrum.gui")
    gui = sys.modules["analyze_spectrum.gui"]
    saved = gui._updater
    gui._updater = updater
    if lang is not None:
        gui._ui_settings.update({"lang": lang})
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_context().new_page()
            page.on("dialog", on_dialog)
            if prepare is not None:
                prepare(page)
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            yield page
            browser.close()
    finally:
        for gate in updater.gates():
            gate.set()
        gui._updater = saved
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_accepted_update_locks_the_page_until_the_install_fails():
    updater = _PageUpdater("9.9.9")
    asked = []

    def accept(dialog):
        asked.append(dialog.message)
        dialog.accept()

    with _update_page(updater, accept) as page:
        page.wait_for_function("document.getElementById('submit-btn').disabled", timeout=10000)
        assert len(asked) == 1 and "9.9.9" in asked[0]
        assert all(page.is_disabled(selector) for selector in _UPDATE_LOCKED)
        assert "Downloading update" in page.inner_text("#status")
        updater.release.set()
        page.wait_for_selector("#status.error", timeout=10000)
        assert "bad signature" in page.inner_text("#status")
        assert all(page.is_enabled(selector) for selector in _UPDATE_LOCKED)
    assert updater.installed == ["9.9.9"]


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_declined_update_installs_nothing():
    updater = _PageUpdater("9.9.9")
    asked = []

    def dismiss(dialog):
        asked.append(dialog.message)
        dialog.dismiss()

    with _update_page(updater, dismiss) as page:
        page.wait_for_function("document.getElementById('settings-toggle') !== null", timeout=10000)
        page.wait_for_load_state("networkidle")
        assert len(asked) == 1
        assert all(page.is_enabled(selector) for selector in _UPDATE_LOCKED)
    assert updater.checks == 1
    assert updater.installed == []


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_launch_check_off_does_not_ask_the_release_feed():
    updater = _PageUpdater("9.9.9", launch_check=False)
    with _update_page(updater, lambda d: d.dismiss()) as page:
        page.wait_for_function("document.getElementById('settings-toggle') !== null", timeout=10000)
        page.wait_for_load_state("networkidle")
    assert updater.checks == 0


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_unchecking_launch_check_saves_it_in_the_app():
    updater = _PageUpdater(None)
    with _update_page(updater, lambda d: d.dismiss()) as page:
        page.wait_for_load_state("networkidle")
        page.click("#settings-toggle")
        page.wait_for_selector("#settings-update-launch")
        assert page.is_checked("#settings-update-launch")
        page.uncheck("#settings-update-launch")
        page.wait_for_function("!document.getElementById('settings-update-launch').checked")
        page.wait_for_load_state("networkidle")
    assert updater.saved == [False]
    assert updater.launch_check_on is False


_TRACK_JS = """{label: 'x', sample_rate: 48000, duration_sec: 1, rms_dbfs: -14, peak_dbfs: -3,
  true_peak_dbtp: -2.8, spectrum: {freqs: [100, 200, 400, 800], psd_db: [-30, -35, -40, -45]},
  bands: {centers: [100, 200, 400], energy_db: [-30, -35, -40]},
  summary: {crest_factor_db: 11, low_intel_ratio_db: 3, spectral_centroid_hz: 600, spectral_tilt_db_oct: -3.5,
    presence_mid_ratio_db: -2, brightness_db: -10, hpf_3db_hz: null, hf_rolloff_hz: 12000,
    band_energy: {sub_20_80: -45, low_80_200: -20, low_mid_200_500: -22, mid_500_2k: -25,
      presence_2k_5k: -27, air_5k_10k: -38}},
  meta: {version: '1', analyzed_at: '2026-01-01T00:00:00Z', source: 'x'}}"""

_RENDER_JS = {
    "single": "renderSingle(" + _TRACK_JS + ")",
    "compare": "renderCompare({tracks: [" + _TRACK_JS + ", " + _TRACK_JS + "], transfer_functions: [], "
               "meta: {version: '1', analyzed_at: '2026-01-01T00:00:00Z', sources: ['x', 'y']}})",
}


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("result", ["single", "compare"])
def test_saving_is_locked_while_an_update_installs(result):
    updater = _PageUpdater("9.9.9", launch_check=False)
    saves = []
    with _update_page(updater, lambda d: d.accept()) as page:
        page.on("request", lambda r: saves.append(r.url) if "/save" in r.url else None)
        page.wait_for_load_state("networkidle")
        page.evaluate(_RENDER_JS[result])
        page.click("#settings-toggle")
        page.click("#settings-update-now")
        page.wait_for_function("document.getElementById('submit-btn').disabled", timeout=10000)
        assert page.eval_on_selector_all(".save-btn", "bs => bs.length > 0 && bs.every(b => b.disabled)")
        page.evaluate("saveResult(lastData); saveImage(lastData);")
        page.evaluate("window.i18n.setLang('ja')")
        assert page.eval_on_selector_all(".save-btn", "bs => bs.length > 0 && bs.every(b => b.disabled)")
        updater.release.set()
        page.wait_for_selector("#status.error", timeout=10000)
        assert page.eval_on_selector_all(".save-btn", "bs => bs.length > 0 && bs.every(b => !b.disabled)")
    assert saves == []


# An analysis in flight, as far as the page's Escape handler can tell, and a
# record of whether that handler cancelled it.
_RUNNING_ANALYSIS_JS = """activeAbort = new AbortController(); window.__aborted = false;
activeAbort.signal.addEventListener('abort', () => { window.__aborted = true; });"""
_DIALOG_OPEN_JS = "!document.querySelector('.settings-scrim').hidden"
_FOCUS_IN_DIALOG_JS = "document.querySelector('.settings-box').contains(document.activeElement)"
_FOCUS_ON_DIALOG_JS = "document.activeElement === document.querySelector('.settings-box')"


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_escape_during_check_now_keeps_the_analysis_and_the_dialog():
    updater = _PageUpdater(None, launch_check=False)
    updater.check_gate = threading.Event()
    with _update_page(updater, lambda d: d.dismiss()) as page:
        page.wait_for_load_state("networkidle")
        page.evaluate(_RUNNING_ANALYSIS_JS)
        page.click("#settings-toggle")
        page.click("#settings-update-now")
        page.wait_for_function("document.getElementById('settings-update-now').disabled")
        page.keyboard.press("Escape")
        assert page.evaluate("window.__aborted") is False
        assert page.evaluate(_FOCUS_IN_DIALOG_JS)
        assert page.evaluate(_DIALOG_OPEN_JS)
        updater.check_gate.set()
        page.wait_for_function("!document.getElementById('settings-update-now').disabled")
        assert page.evaluate("document.activeElement.id") == "settings-update-now"


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_escape_during_a_save_closes_the_dialog_and_keeps_the_analysis():
    updater = _PageUpdater(None, launch_check=True)
    updater.save_gate = threading.Event()
    with _update_page(updater, lambda d: d.dismiss()) as page:
        page.wait_for_load_state("networkidle")
        page.evaluate(_RUNNING_ANALYSIS_JS)
        page.click("#settings-toggle")
        page.click("#settings-update-launch")
        page.wait_for_function("document.getElementById('settings-update-launch').disabled")
        assert page.evaluate(_FOCUS_ON_DIALOG_JS)
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.id") == "settings-update-now"
        page.evaluate("document.querySelector('.settings-box').focus()")
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.activeElement.id") == "settings-close"
        page.evaluate("document.querySelector('.settings-box').focus()")
        page.keyboard.press("Escape")
        assert page.evaluate("window.__aborted") is False
        assert not page.evaluate(_DIALOG_OPEN_JS)
        updater.save_gate.set()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_escape_after_the_status_redraw_keeps_the_analysis_and_closes_the_dialog():
    updater = _PageUpdater(None, launch_check=False)
    updater.status_gate = threading.Event()
    with _update_page(updater, lambda d: d.dismiss()) as page:
        page.wait_for_function("document.getElementById('settings-toggle') !== null", timeout=10000)
        page.evaluate(_RUNNING_ANALYSIS_JS)
        page.click("#settings-toggle")
        assert page.evaluate("document.activeElement.id") == "settings-close"
        assert page.is_disabled("#settings-update-now")
        updater.status_gate.set()
        page.wait_for_function("!document.getElementById('settings-update-now').disabled")
        assert page.evaluate("document.activeElement.id") == "settings-close"
        page.keyboard.press("Escape")
        assert page.evaluate("window.__aborted") is False
        assert not page.evaluate(_DIALOG_OPEN_JS)


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_settings_button_keeps_focus_and_refuses_while_an_update_downloads():
    updater = _PageUpdater("9.9.9", launch_check=False)
    with _update_page(updater, lambda d: d.accept()) as page:
        page.wait_for_load_state("networkidle")
        page.click("#settings-toggle")
        page.click("#settings-update-now")
        page.wait_for_function("document.getElementById('submit-btn').disabled", timeout=10000)
        assert page.evaluate("document.activeElement.id") == "settings-toggle"
        assert page.get_attribute("#settings-toggle", "aria-disabled") == "true"
        page.evaluate("document.getElementById('settings-toggle').click()")
        assert not page.evaluate(_DIALOG_OPEN_JS)
        updater.release.set()
        page.wait_for_selector("#status.error", timeout=10000)
        assert page.get_attribute("#settings-toggle", "aria-disabled") is None
        page.click("#settings-toggle")
        assert page.evaluate(_DIALOG_OPEN_JS)


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_tab_from_the_dialog_itself_goes_to_the_first_and_last_control():
    updater = _PageUpdater(None, launch_check=False)
    with _update_page(updater, lambda d: d.dismiss()) as page:
        page.wait_for_load_state("networkidle")
        page.click("#settings-toggle")
        page.evaluate("document.querySelector('.settings-box').focus()")
        assert page.evaluate(_FOCUS_ON_DIALOG_JS)
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.activeElement.id") == "settings-close"
        page.evaluate("document.querySelector('.settings-box').focus()")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.id") == "settings-update-launch"


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_settings_stay_closed_after_an_installed_update_could_not_restart():
    from analyze_common.update import Handoff
    updater = _PageUpdater("9.9.9", launch_check=False, install_result=Handoff(None, restart_error="Resource busy"))
    with _update_page(updater, lambda d: d.accept()) as page:
        page.wait_for_load_state("networkidle")
        page.click("#settings-toggle")
        page.click("#settings-update-now")
        page.wait_for_selector("#status.error", timeout=10000)
        assert "could not restart (Resource busy)" in page.inner_text("#status")
        assert page.is_enabled("#submit-btn")
        assert page.get_attribute("#settings-toggle", "aria-disabled") == "true"
        page.evaluate("document.getElementById('settings-toggle').click()")
        assert not page.evaluate(_DIALOG_OPEN_JS)


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_outside_press_keeps_escape_in_the_settings_dialog():
    """A real press outside the settings dialog does not move focus: Escape
    after it still reaches the dialog while a check holds the dialog open, and
    focus returns to the settings button when the press closes the dialog."""
    updater = _PageUpdater(None, launch_check=False)
    updater.check_gate = threading.Event()
    with _update_page(updater, lambda d: d.dismiss()) as page:
        page.evaluate("window.analyzeUpdate.ready")
        page.evaluate(_RUNNING_ANALYSIS_JS)
        page.focus("#settings-toggle")
        page.keyboard.press("Enter")
        page.focus("#settings-update-now")
        page.keyboard.press("Enter")
        page.wait_for_function("document.getElementById('settings-update-now').disabled")
        page.mouse.click(5, 5)
        page.keyboard.press("Escape")
        assert page.evaluate("window.__aborted") is False
        assert page.is_visible(".settings-box")
        updater.check_gate.set()
        page.wait_for_function("!document.getElementById('settings-update-now').disabled")
        page.mouse.click(5, 5)
        assert not page.is_visible(".settings-box")
        assert page.evaluate("document.activeElement.id") == "settings-toggle"


def _settings_file():
    gui = sys.modules["analyze_spectrum.gui"]
    try:
        return json.loads(gui._settings.path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _wait_for(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail("condition not met in time")
        time.sleep(0.02)


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_stored_theme_and_language_apply_before_main_js_runs():
    gui = _gui_module()
    gui._ui_settings.update({"theme": "dark"})
    blocked = []

    def block_main_js(page):
        page.route("**/main.js", lambda route: (blocked.append(route.request.url), route.abort()))

    with _update_page(_PageUpdater(None, launch_check=False), lambda d: d.dismiss(),
                      lang="ja", prepare=block_main_js) as page:
        page.wait_for_load_state("domcontentloaded")
        assert blocked
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
        assert page.evaluate("document.documentElement.getAttribute('lang')") == "ja"


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_theme_and_language_picked_are_there_at_the_next_launch():
    with _update_page(_PageUpdater(None, launch_check=False), lambda d: d.dismiss()) as page:
        page.wait_for_load_state("networkidle")
        page.click("#theme-toggle")
        page.click("#lang-toggle")
        _wait_for(lambda: _settings_file().get("theme") == "light" and _settings_file().get("lang") == "ja")
        relaunched = page.context.browser.new_context().new_page()
        relaunched.goto(page.url)
        relaunched.wait_for_load_state("networkidle")
        assert relaunched.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
        assert relaunched.evaluate("document.documentElement.getAttribute('lang')") == "ja"
        assert relaunched.get_attribute("#theme-toggle", "title") == \
            relaunched.evaluate("window.i18n.t('theme.title.light')")
        assert relaunched.inner_text("#lang-toggle") == "JA"


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_quick_theme_picks_are_saved_one_after_another(monkeypatch):
    gui = _gui_module()
    real_update = gui._ui_settings.update
    arrived, calls = [], []

    def slow_first(changes):
        start = time.monotonic()
        arrived.append(changes)
        if len(arrived) == 1:
            time.sleep(0.3)
        result = real_update(changes)
        calls.append((changes, start, time.monotonic()))
        return result

    monkeypatch.setattr(gui._ui_settings, "update", slow_first)
    with _update_page(_PageUpdater(None, launch_check=False), lambda d: d.dismiss()) as page:
        page.wait_for_load_state("networkidle")
        arrived.clear()
        calls.clear()
        page.evaluate("""() => {
          const button = document.getElementById("theme-toggle");
          button.click(); button.click(); button.click();
        }""")
        _wait_for(lambda: len(calls) == 3)
        shown = page.evaluate("_themeMode")
    assert [c[0] for c in calls] == [{"theme": "light"}, {"theme": "dark"}, {"theme": "auto"}]
    assert all(later[1] >= earlier[2] for earlier, later in zip(calls, calls[1:]))
    assert shown == "auto"
    assert _settings_file()["theme"] == "auto"


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_failed_theme_save_shows_the_cause_and_keeps_the_theme(monkeypatch):
    gui = _gui_module()
    with _update_page(_PageUpdater(None, launch_check=False), lambda d: d.dismiss()) as page:
        page.wait_for_load_state("networkidle")

        def fail(key, value):
            raise OSError("read-only")

        monkeypatch.setattr(gui._settings, "set", fail)
        page.click("#theme-toggle")
        page.wait_for_selector("#status.error")
        text = page.inner_text("#status .error-text")
        theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert text == "Error: The setting could not be saved: read-only"
    assert theme == "light"


def test_settings_file_is_in_this_tests_temp_folder(_isolated_settings):
    assert _isolated_settings in _gui_module()._settings.path.parents
