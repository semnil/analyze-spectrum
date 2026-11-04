"""Browser input, track ordering and file operations through the app's page."""

import base64
from urllib.parse import unquote

import numpy as np
import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect, sync_playwright

from analyze_spectrum.analysis import analyze_track, compare_tracks
from tests.test_frontend import _app_server, _gui_module


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture()
def page(browser, monkeypatch):
    gui = _gui_module()
    monkeypatch.setattr(gui._updater, "status", lambda: {"supported": False, "launch_check": False})
    server = _app_server("analyze_spectrum.gui")
    page = browser.new_page(locale="en-US")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
        page.evaluate("window.analyzeUpdate.ready")
        page.evaluate("window.i18n.setLang('en')")
        yield page
        assert errors == []
    finally:
        try:
            page.close()
        finally:
            server.shutdown()
            server.server_close()


@pytest.fixture(scope="module")
def tracks():
    samples = np.random.default_rng(7).normal(0, 0.05, 12000)
    return [analyze_track(samples, label="First"), analyze_track(samples * 2, label="Second")]


def _clipboard(page, text="paste-value"):
    page.evaluate("""text => Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
        text, writeText(value) {this.text = value; return Promise.resolve();},
        readText() {return Promise.resolve(this.text);}
    }})""", text)


def _menu(page, start=1, end=3):
    field = page.locator("#url-input")
    field.fill("abcdef")
    field.evaluate("(el, range) => el.setSelectionRange(...range)", [start, end])
    field.dispatch_event("contextmenu", {"clientX": 100, "clientY": 100})
    expect(page.get_by_role("menu")).to_be_visible()
    return field


@pytest.mark.parametrize("item,value,clipboard,selection", [
    (0, "adef", "bc", [1, 1]),
    (1, "abcdef", "bc", [1, 3]),
    (2, "apaste-valuedef", "paste-value", [12, 12]),
    (3, "abcdef", "paste-value", [0, 6]),
])
def test_context_menu_edits_the_selection(page, item, value, clipboard, selection):
    _clipboard(page)
    field = _menu(page)
    page.get_by_role("menuitem").nth(item).click()
    expect(field).to_have_value(value)
    assert page.evaluate("navigator.clipboard.text") == clipboard
    assert field.evaluate("el => [el.selectionStart, el.selectionEnd]") == selection
    expect(page.get_by_role("menu")).to_have_count(0)


def test_context_menu_keyboard_navigation_and_activation(page):
    _clipboard(page)
    field = _menu(page)
    items = page.get_by_role("menuitem")
    expect(items.nth(0)).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(items.nth(1)).to_be_focused()
    page.keyboard.press("ArrowUp")
    expect(items.nth(0)).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.get_by_role("menu")).to_have_count(0)
    expect(field).to_be_focused()
    _menu(page)
    page.keyboard.press("Enter")
    expect(field).to_have_value("adef")
    assert page.evaluate("navigator.clipboard.text") == "bc"
    expect(page.get_by_role("menu")).to_have_count(0)


@pytest.mark.parametrize("clipboard", [True, False])
def test_context_menu_disables_unavailable_actions(page, clipboard):
    if clipboard:
        _clipboard(page)
    else:
        page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: undefined})")
    _menu(page, start=2, end=2)
    items = page.get_by_role("menuitem")
    expect(items.nth(0)).to_be_disabled()
    expect(items.nth(1)).to_be_disabled()
    assert items.nth(2).is_enabled() == clipboard
    expect(items.nth(3)).to_be_enabled()


@pytest.mark.parametrize("rendered", [True, False])
def test_reordering_keeps_sources_rows_and_rendered_tracks_in_sync(page, tracks, rendered):
    page.evaluate("() => {compareSources = ['first.wav', 'second.wav']; updateCompareUI();}")
    if rendered:
        page.evaluate("data => renderCompare(data)", compare_tracks(tracks).to_dict())
    page.locator(".track-item").first.locator(".track-btn").nth(1).click()
    assert page.evaluate("compareSources") == ["second.wav", "first.wav"]
    expect(page.locator(".track-label")).to_have_text(["second.wav", "first.wav"])
    if rendered:
        assert page.evaluate("lastData.tracks.map(track => track.label)") == ["Second", "First"]
        assert page.locator(".chart-title", has_text="Transfer Function").count() == 1
    page.locator(".track-item").nth(1).locator(".track-btn").first.click()
    assert page.evaluate("compareSources") == ["first.wav", "second.wav"]
    expect(page.locator(".track-label")).to_have_text(["first.wav", "second.wav"])
    if rendered:
        assert page.evaluate("lastData.tracks.map(track => track.label)") == ["First", "Second"]
    page.wait_for_function("Array.from(document.querySelectorAll('.track-item')).every(el => el.style.transition === '')")
    expect(page.locator(".track-item").first.locator(".track-btn").first).to_be_disabled()
    expect(page.locator(".track-item").last.locator(".track-btn").nth(1)).to_be_disabled()


def _drop(page, names):
    page.evaluate("""names => {
        const data = new DataTransfer();
        for (const name of names) data.items.add(new File(['audio'], name, {type: 'audio/wav'}));
        for (const type of ['dragover', 'dragenter', 'dragleave', 'drop'])
            window.dispatchEvent(new DragEvent(type, {dataTransfer: data}));
    }""", names)


def test_file_drop_uploads_files_and_preserves_the_pending_source(page):
    requests = []

    def upload(route):
        name = route.request.headers["x-filename"]
        requests.append((name, route.request.headers["content-type"], route.request.post_data_buffer))
        route.fulfill(json={"uploaded": True, "path": "/uploaded/" + name})

    page.route("**/upload", upload)
    field = page.locator("#url-input")
    _drop(page, ["one.wav"])
    expect(field).to_have_value("/uploaded/one.wav")
    _drop(page, ["two.wav"])
    expect(field).to_have_value("/uploaded/two.wav")
    assert page.evaluate("compareSources") == ["/uploaded/one.wav"]
    _drop(page, ["three.wav", "four.wav"])
    expect(page.locator(".track-label")).to_have_text([
        "/uploaded/one.wav", "/uploaded/three.wav", "/uploaded/four.wav"])
    expect(field).to_have_value("/uploaded/two.wav")
    assert page.evaluate("document.body.classList.contains('drag-over')") is False
    assert requests == [(name, "application/octet-stream", b"audio")
                        for name in ("one.wav", "two.wav", "three.wav", "four.wav")]


def test_file_drop_sends_a_non_ascii_name_percent_encoded(page):
    requests = []

    def upload(route):
        name = route.request.headers["x-filename"]
        requests.append(name)
        route.fulfill(json={"uploaded": True, "path": "/uploaded/" + unquote(name)})

    page.route("**/upload", upload)
    _drop(page, ["日本語 track.wav"])
    expect(page.locator("#url-input")).to_have_value("/uploaded/日本語 track.wav")
    assert requests == ["%E6%97%A5%E6%9C%AC%E8%AA%9E%20track.wav"]


def _response(page, endpoint, status, body):
    page.route("**/" + endpoint, lambda route: route.fulfill(status=status, json=body))


@pytest.mark.parametrize("status,body,error", [
    (400, {"error": "upload-http-error"}, "upload-http-error"),
    (200, {"error": "upload-result-error"}, "upload-result-error"),
    (500, {}, "HTTP 500"),
    (None, None, "Failed to fetch"),
])
def test_file_drop_reports_upload_failures_without_adding_a_track(page, status, body, error):
    if status is None:
        page.route("**/upload", lambda route: route.abort())
    else:
        _response(page, "upload", status, body)
    page.locator("#url-input").fill("pending.wav")
    _drop(page, ["failed.wav"])
    expect(page.locator("#status")).to_contain_text(error)
    expect(page.locator("#status")).to_have_attribute("role", "alert")
    expect(page.locator("#url-input")).to_have_value("pending.wav")
    assert page.evaluate("compareSources") == []


@pytest.mark.parametrize("status,body,expected", [
    (200, {"saved": True, "path": "/saved/image.png"}, "/saved/image.png"),
    (200, {"saved": False}, ""),
    (200, {"error": "save-result-error"}, "save-result-error"),
    (500, {"error": "save-http-error"}, "save-http-error"),
    (500, {}, "HTTP 500"),
    (None, None, "Failed to fetch"),
])
def test_image_save_sends_a_png_and_reports_the_outcome(page, tracks, status, body, expected):
    data = tracks[0].to_dict()
    page.evaluate("data => renderSingle(data)", data)
    requests = []

    def save(route):
        requests.append(route.request.post_data_json)
        if status is None:
            route.abort()
        else:
            route.fulfill(status=status, json=body)

    page.route("**/save-image", save)
    page.evaluate("data => saveImage(data)", data)
    assert len(requests) == 1
    assert requests[0]["filename"] == "spectrum_First.png"
    prefix, encoded = requests[0]["dataUrl"].split(",", 1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n")
    if expected:
        expect(page.locator("#status")).to_contain_text(expected)
        role = "status" if body and body.get("saved") else "alert"
        expect(page.locator("#status")).to_have_attribute("role", role)
    else:
        expect(page.locator("#status")).to_have_text("")


@pytest.mark.parametrize("status,body,expected", [
    (200, {"selected": True, "path": "/selected/audio.wav"}, "/selected/audio.wav"),
    (200, {"selected": False}, None),
    (500, {"error": "browse-error"}, "browse-error"),
    (500, {}, "HTTP 500"),
    (None, None, "Failed to fetch"),
])
def test_browse_preserves_the_input_unless_a_file_is_selected(page, status, body, expected):
    requests = []

    def browse(route):
        requests.append((route.request.method, route.request.post_data_json))
        if status is None:
            route.abort()
        else:
            route.fulfill(status=status, json=body)

    page.route("**/browse", browse)
    field = page.locator("#url-input")
    field.fill("pending.wav")
    event = "requestfinished" if status else "requestfailed"
    with page.expect_event(event, predicate=lambda request: request.url.endswith("/browse")):
        page.locator("#browse-btn").click()
    if status == 200 and expected:
        expect(field).to_have_value(expected)
        expect(field).to_be_focused()
    else:
        expect(field).to_have_value("pending.wav")
        if expected:
            expect(page.locator("#status")).to_contain_text(expected)
        else:
            expect(page.locator("#status")).to_have_text("")
    assert requests == [("POST", {})]
