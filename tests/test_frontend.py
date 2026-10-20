"""Run frontend UI tests in a headless Chromium browser via Playwright.

Starts a local HTTP server to serve the test HTML, then uses Playwright
to open the page and read test results from window._testResult.
"""

import threading
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


def _app_server(gui_module_name):
    """Serve the real index.html, style.css and common.css through the app's handler."""
    import importlib
    import sys
    from http.server import ThreadingHTTPServer
    from unittest.mock import MagicMock
    saved = sys.modules.get("webview")
    sys.modules["webview"] = MagicMock()
    try:
        gui_mod = importlib.import_module(gui_module_name)
    finally:
        if saved is None:
            del sys.modules["webview"]
        else:
            sys.modules["webview"] = saved

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
