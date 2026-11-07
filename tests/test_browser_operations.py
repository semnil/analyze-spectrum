"""Browser input, track ordering and file operations through the app's page."""

import base64
import json
import re
from urllib.parse import unquote

import numpy as np
import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect, sync_playwright

from analyze_common.json_util import json_safe
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


def test_reordering_keeps_sources_and_rows_in_sync(page):
    page.evaluate("() => {compareSources = ['first.wav', 'second.wav']; updateCompareUI();}")
    page.locator(".track-item").first.locator(".track-btn").nth(1).click()
    assert page.evaluate("compareSources") == ["second.wav", "first.wav"]
    expect(page.locator(".track-label")).to_have_text(["second.wav", "first.wav"])
    page.locator(".track-item").nth(1).locator(".track-btn").first.click()
    assert page.evaluate("compareSources") == ["first.wav", "second.wav"]
    expect(page.locator(".track-label")).to_have_text(["first.wav", "second.wav"])
    page.wait_for_function("Array.from(document.querySelectorAll('.track-item')).every(el => el.style.transition === '')")
    expect(page.locator(".track-item").first.locator(".track-btn").first).to_be_disabled()
    expect(page.locator(".track-item").last.locator(".track-btn").nth(1)).to_be_disabled()


@pytest.fixture(scope="module")
def tracks_by_source():
    samples = np.random.default_rng(7).normal(0, 0.05, 12000)
    gains = {"first.wav": 1, "second.wav": 2, "third.wav": 0.5}
    return {source: analyze_track(samples * gain, label=source) for source, gain in gains.items()}


def _comparison(tracks_by_source, sources):
    data = compare_tracks([tracks_by_source[source] for source in sources]).to_dict()
    for track, source in zip(data["tracks"], sources):
        track["meta"] = {"source": source}
    return data


def _answer_comparison(route, tracks_by_source):
    sources = json.loads(route.request.post_data)["sources"]
    event = {"type": "compare_result", "data": _comparison(tracks_by_source, sources)}
    route.fulfill(status=200, content_type="application/x-ndjson", body=json.dumps(json_safe(event)) + "\n")


def _show_comparison(page, tracks_by_source, sources):
    page.evaluate("sources => {compareSources = sources; updateCompareUI();}", sources)
    page.evaluate("data => renderCompare(data)", json_safe(_comparison(tracks_by_source, sources)))


def _set_height_with_nothing_on_screen(page, height):
    # Cancels the redraw the page's resize handler schedules, which would replace the results during the steps of a test.
    page.evaluate("() => {addEventListener('resize', () => {window.resized = true;}, {once: true});}")
    page.set_viewport_size({"width": 1100, "height": height})
    page.wait_for_function("window.resized")
    page.evaluate("clearTimeout(_afterResizeTimer); _afterResizeTimer = null; _scrollAtResize = null;")


def _track_button(page, row, action):
    return page.locator(".track-item").nth(row).locator(f'.track-btn[data-action="{action}"]')


def _shown_sources(page):
    return page.evaluate("lastData && lastData.tracks.map(track => track.meta.source)")


def _first_held(page, held):
    for _ in range(500):
        if held:
            return held[0]
        page.wait_for_timeout(10)
    raise AssertionError("the page sent no request")


def test_moving_a_track_compares_again_in_the_new_order(page, tracks_by_source):
    held = []
    page.route("**/compare", lambda route: held.append(route))
    _show_comparison(page, tracks_by_source, ["first.wav", "second.wav"])
    _track_button(page, 0, "down").click()
    route = _first_held(page, held)
    assert json.loads(route.request.post_data) == {"sources": ["second.wav", "first.wav"]}
    expect(page.locator(".track-label")).to_have_text(["second.wav", "first.wav"])
    # The results stay, and the rows wait, until the new results replace them.
    assert _shown_sources(page) == ["first.wav", "second.wav"]
    expect(_track_button(page, 1, "up")).to_be_disabled()
    _answer_comparison(route, tracks_by_source)
    page.wait_for_function("!isBusy")
    assert _shown_sources(page) == ["second.wav", "first.wav"]
    assert page.locator(".chart-title", has_text="Transfer Function").count() == 1
    assert page.evaluate("statusEl.textContent") == ""
    expect(_track_button(page, 1, "up")).to_be_enabled()
    assert len(held) == 1


def test_moving_a_track_keeps_the_focus_the_scroll_and_the_pending_source(page, tracks_by_source):
    page.route("**/compare", lambda route: _answer_comparison(route, tracks_by_source))
    # At this height the page is shorter than the scroll position while the results are redrawn.
    _set_height_with_nothing_on_screen(page, 1000)
    _show_comparison(page, tracks_by_source, ["first.wav", "second.wav", "third.wav"])
    field = page.locator("#url-input")
    field.fill("pending.wav")
    _track_button(page, 0, "down").focus()
    page.evaluate("window.scrollTo(0, 120)")
    scroll = page.evaluate("window.scrollY")
    assert scroll == 120
    page.evaluate("() => {window.resultsFocused = 0; resultsEl.addEventListener('focus', () => window.resultsFocused++);}")
    page.keyboard.press("Enter")
    page.wait_for_function("!isBusy && lastData.tracks[0].meta.source === 'second.wav'")
    expect(_track_button(page, 1, "down")).to_be_focused()
    assert page.evaluate("window.resultsFocused") == 0
    assert page.evaluate("window.scrollY") == scroll
    page.keyboard.press("Enter")
    page.wait_for_function("!isBusy && lastData.tracks[1].meta.source === 'third.wav'")
    assert _shown_sources(page) == ["second.wav", "third.wav", "first.wav"]
    expect(field).to_have_value("pending.wav")
    assert page.evaluate("compareSources") == ["second.wav", "third.wav", "first.wav"]


@pytest.mark.parametrize("answer", ["result", "failure"])
def test_a_run_after_a_move_leaves_what_the_user_changed_while_it_ran(page, tracks_by_source, answer):
    held = []
    page.route("**/compare", lambda route: held.append(route))
    _set_height_with_nothing_on_screen(page, 1000)
    _show_comparison(page, tracks_by_source, ["first.wav", "second.wav", "third.wav"])
    _track_button(page, 0, "down").focus()
    page.keyboard.press("Enter")
    route = _first_held(page, held)
    field = page.locator("#url-input")
    field.focus()
    page.evaluate("window.scrollTo(0, 200)")
    if answer == "result":
        _answer_comparison(route, tracks_by_source)
    else:
        route.fulfill(status=500, json={"error": "the source is gone"})
    page.wait_for_function("!isBusy")
    expect(field).to_be_focused()
    if answer == "result":
        assert page.evaluate("window.scrollY") == 200


def test_a_failed_comparison_after_a_move_clears_the_results(page, tracks_by_source):
    page.route("**/compare", lambda route: route.fulfill(status=500, json={"error": "the source is gone"}))
    _show_comparison(page, tracks_by_source, ["first.wav", "second.wav"])
    _track_button(page, 0, "down").click()
    expect(page.locator("#status")).to_contain_text("the source is gone")
    page.wait_for_function("!isBusy")
    assert page.evaluate("lastData") is None
    assert page.evaluate("resultsEl.childElementCount") == 0
    assert page.evaluate("compareSources") == ["second.wav", "first.wav"]


def test_a_cancelled_comparison_after_a_move_clears_the_results(page, tracks_by_source):
    held = []
    page.route("**/compare", lambda route: held.append(route))
    _show_comparison(page, tracks_by_source, ["first.wav", "second.wav"])
    _track_button(page, 0, "down").click()
    _first_held(page, held)
    page.locator("#submit-btn").click()
    page.wait_for_function("!isBusy")
    assert page.evaluate("lastData") is None
    assert page.evaluate("resultsEl.childElementCount") == 0
    assert page.evaluate("statusEl.textContent") == page.evaluate("window.i18n.t('status.cancelled')")


def test_moving_a_track_with_no_comparison_on_screen_runs_nothing(page, tracks_by_source):
    requests = []
    page.route("**/compare", lambda route: requests.append(route))
    page.evaluate("() => {compareSources = ['first.wav', 'second.wav']; updateCompareUI();}")
    _track_button(page, 0, "down").click()
    single = {**tracks_by_source["third.wav"].to_dict(), "meta": {"source": "third.wav"}}
    page.evaluate("data => renderSingle(data)", json_safe(single))
    _track_button(page, 0, "down").click()
    page.wait_for_function("lastData === null")
    assert page.evaluate("resultsEl.childElementCount") == 0
    assert page.evaluate("isBusy") is False
    assert requests == []


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


_VALUE_CELLS_REACHED_JS = """() => Array.from(document.querySelectorAll('#results .summary-table tr')).flatMap((row) =>
  Array.from(row.children).filter((cell) => !cell.classList.contains('label-cell') && cell.cellIndex > 0).map((cell) => {
    cell.scrollIntoView({inline: 'center', block: 'center'});
    const box = cell.getBoundingClientRect();
    return document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2) === cell;
  }))"""


@pytest.mark.parametrize("width", [480, 1100])
def test_long_track_labels_leave_the_values_readable(page, width):
    """With very long unbroken track labels and an estimated EQ the page stays as
    wide as the window, and the label column hides no value."""
    samples = np.random.default_rng(7).normal(0, 0.05, 48000)
    long_label = "https://example.com/" + "a" * 200
    data = compare_tracks([analyze_track(samples, label=long_label + "1"),
                           analyze_track(samples * 2, label=long_label + "2")]).to_dict()
    page.set_viewport_size({"width": width, "height": 800})
    page.evaluate("data => renderCompare(data)", data)
    assert page.locator(".eq-caption").count() > 0
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    reached = page.evaluate(_VALUE_CELLS_REACHED_JS)
    assert reached and all(reached)


_LABEL_CELLS_STATE_JS = """() => {
  const results = document.getElementById('results');
  const box = results.getBoundingClientRect();
  const firstCell = document.querySelector('.summary-table td.label-cell');
  const chain = [];
  for (let el = firstCell; el; el = el.parentElement) {
    const style = getComputedStyle(el);
    chain.push([el.tagName, el.className, style.display, style.visibility, Math.round(el.getBoundingClientRect().width)]);
  }
  return {
    widths: Array.from(document.querySelectorAll('.summary-table td.label-cell')).map(c => c.getBoundingClientRect().width),
    resultsClass: results.className,
    resultsDisplay: getComputedStyle(results).display,
    resultsBox: [box.width, box.height],
    window: [window.innerWidth, window.innerHeight, window.devicePixelRatio],
    visibility: document.visibilityState,
    readyState: document.readyState,
    sheets: Array.from(document.styleSheets).map(s => s.href && s.href.split('/').pop()),
    chain,
  };
}"""


def test_track_labels_keep_a_readable_width_in_a_narrow_window(page):
    """In a 480 px window the label column of the summary tables does not get
    narrower than 96 px, however little room the values leave."""
    samples = np.random.default_rng(7).normal(0, 0.05, 48000)
    names = ["recording_final_mix_v2.wav", "master_for_streaming.flac", "vocal.wav"]
    data = compare_tracks([analyze_track(samples * (i + 1), label=name) for i, name in enumerate(names)]).to_dict()
    page.set_viewport_size({"width": 480, "height": 800})
    page.evaluate("data => renderCompare(data)", data)
    state = page.evaluate(_LABEL_CELLS_STATE_JS)
    assert state["widths"] and min(state["widths"]) >= 96, json.dumps(state)


_COMPARISON_ON_SCREEN_JS = """(data) => { compareSources.push('A', 'B'); updateCompareUI(); renderCompare(data);
  _setDisplayedSources(['A', 'B']); }"""


def test_dropped_files_hold_the_page_and_drop_a_comparison(page, tracks):
    """The page is busy until the files are in, and files joining the track list
    drop the comparison on screen, whose tracks are no longer the list's."""
    page.evaluate(_COMPARISON_ON_SCREEN_JS, compare_tracks(tracks).to_dict())
    held = []
    page.route("**/upload", lambda route: held.append(route))
    with page.expect_request("**/upload"):
        _drop(page, ["c.wav", "d.wav"])
    assert page.evaluate("isBusy")
    expect(page.locator("#add-btn")).to_be_disabled()
    expect(page.locator("#submit-btn")).to_be_disabled()
    expect(page.locator("#submit-btn")).to_have_text(page.evaluate("window.i18n.t('btn.loading')"))
    expect(page.locator("#submit-btn")).not_to_have_class(re.compile("cancelling"))
    assert page.evaluate("lastData !== null")
    with page.expect_request("**/upload"):
        held.pop().fulfill(json={"uploaded": True, "path": "/tmp/up/c.wav"})
    page.wait_for_function("compareSources.length === 3")
    assert page.evaluate("lastData") is None
    held.pop().fulfill(json={"uploaded": True, "path": "/tmp/up/d.wav"})
    page.wait_for_function("!isBusy && compareSources.length === 4")
    expect(page.locator("#add-btn")).to_be_enabled()
    expect(page.locator("#submit-btn")).to_be_enabled()
    expect(page.locator("#submit-btn")).to_have_text(page.evaluate("window.i18n.t('btn.compare')"))


def test_the_submit_button_reserves_the_width_of_its_loading_label(page):
    width = "document.getElementById('submit-btn').getBoundingClientRect().width"
    before = page.evaluate(width)
    page.evaluate("""() => {
      const tr = window.i18n.tr;
      window.i18n.tr = (key, lang) => key === "btn.loading" ? "W".repeat(40) : tr(key, lang);
      _reserveButtonWidths();
      window.i18n.tr = tr;
    }""")
    assert page.evaluate(width) > before


def test_a_failed_upload_frees_the_page_and_keeps_the_comparison(page, tracks):
    page.evaluate(_COMPARISON_ON_SCREEN_JS, compare_tracks(tracks).to_dict())
    page.route("**/upload", lambda route: route.fulfill(status=400, json={"error": "Unsupported file type: .txt"}))
    _drop(page, ["notes.txt", "more.txt"])
    expect(page.locator("#status")).to_contain_text(".txt")
    page.wait_for_function("!isBusy")
    expect(page.locator("#add-btn")).to_be_enabled()
    assert page.evaluate("lastData !== null")


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


@pytest.mark.parametrize("outdated", [False, True], ids=["current", "outdated"])
def test_saving_a_loaded_json_sends_no_source_of_an_earlier_analysis(page, tracks, outdated):
    """The save of a JSON Load JSON shows carries the JSON and no source, so the
    server writes that JSON and not the session's analysis of the same source."""
    page.evaluate("lastSource = 'analyzed.wav'")
    data = tracks[0].to_dict()
    data["meta"] = {"source": "analyzed.wav"}
    reply = {"loaded": True, "type": "single", "data": data}
    if outdated:
        reply.update(schema_outdated=True, source="analyzed.wav", source_available=True)
    page.route("**/load", lambda route: route.fulfill(json=reply))
    bodies = []

    def save(route):
        bodies.append(json.loads(route.request.post_data))
        route.fulfill(json={"saved": True, "path": "/saved/result"})

    page.route("**/save", save)
    page.locator("#load-btn").click()
    if outdated:
        page.locator(".modal-cancel").click()
    page.locator(".save-btn").first.click()
    expect(page.locator("#status")).to_contain_text("/saved/result")
    assert bodies[0]["data"]["label"] == "First"
    assert "source" not in bodies[0]


@pytest.mark.parametrize("button", [0, 1], ids=["save_json", "save_image"])
@pytest.mark.parametrize("before", ["saved", "error"])
def test_cancelling_a_save_empties_the_status_line(page, tracks, button, before):
    """A cancelled file dialog leaves an empty status line that is not an error
    and stays empty across a language switch, whatever the line said before; an
    error reply still shows the error."""
    page.evaluate("data => renderSingle(data)", tracks[0].to_dict())
    reply = {"saved": True, "path": "/saved/result"}
    for path in ("/save", "/save-image"):
        page.route("**" + path, lambda route: route.fulfill(json=reply))
    save = page.locator(".save-btn").nth(button)
    status = page.locator("#status")
    if before == "saved":
        save.click()
        expect(status).to_contain_text("/saved/result")
    else:
        page.evaluate("showError('HTTP Error 403: Forbidden')")
        expect(status.locator(".copy-btn")).to_have_count(1)
    reply.clear()
    reply["saved"] = False
    save.click()
    expect(status).to_have_text("")
    expect(status).to_have_attribute("role", "status")
    assert not page.evaluate("document.getElementById('status').classList.contains('error')")
    page.evaluate("window.i18n.setLang('ja')")
    expect(status).to_have_text("")
    reply["error"] = "disk full"
    save.click()
    expect(status).to_contain_text("disk full")
    expect(status).to_have_attribute("role", "alert")


@pytest.mark.parametrize("save", ["saveResult", "saveImage"])
@pytest.mark.parametrize("before,write,line,error", [
    ("", "_setUpdateLock(true); statusEl.textContent = 'Downloading';", "Downloading", False),
    ("", "showError('Settings could not be saved');", "Settings could not be saved", True),
    ("showError('Settings could not be saved');", "showError('Settings could not be saved');",
     "Settings could not be saved", True),
], ids=["update", "error", "same_error"])
def test_cancelling_a_save_keeps_a_line_written_after_it_began(page, tracks, save, before, write, line, error):
    """When another line reaches the status while a save's file dialog is open,
    cancelling the dialog leaves that line; an error stays an error, also across
    a language switch."""
    data = tracks[0].to_dict()
    page.evaluate("data => renderSingle(data)", data)
    if before:
        page.evaluate(before)
    held = []
    for path in ("/save", "/save-image"):
        page.route("**" + path, lambda route: held.append(route))
    with page.expect_request(lambda request: "/save" in request.url):
        page.evaluate("([name, data]) => { window.running = window[name](data); }", [save, data])
    page.evaluate(write)
    held[0].fulfill(json={"saved": False})
    page.evaluate("window.running")
    status = page.locator("#status")
    expect(status).to_contain_text(line)
    if error:
        expect(status).to_have_attribute("role", "alert")
        expect(status.locator(".copy-btn")).to_have_count(1)
        page.evaluate("window.i18n.setLang('ja')")
        expect(status).to_contain_text(line)


def test_cancelling_a_save_empties_an_error_whose_copy_label_came_back(page, tracks):
    """The Copy label changing back while a save's file dialog is open is not a
    new line: cancelling the dialog empties the error."""
    _clipboard(page)
    page.evaluate("data => renderSingle(data)", tracks[0].to_dict())
    page.evaluate("showError('HTTP Error 403: Forbidden')")
    copy = page.locator("#status .copy-btn")
    label = copy.text_content()
    copy.click()
    expect(copy).not_to_have_text(label)
    held = []
    page.route("**/save", lambda route: held.append(route))
    with page.expect_request("**/save"):
        page.locator(".save-btn").nth(0).click()
    expect(copy).to_have_text(label)
    held[0].fulfill(json={"saved": False})
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


def test_queue_focus_keeps_its_place_while_results_are_shown(page, tracks):
    page.evaluate("() => {compareSources = ['first.wav', 'second.wav']; updateCompareUI();}")
    page.evaluate("data => renderCompare(data)", compare_tracks(tracks).to_dict())
    up = page.locator(".track-item").nth(1).locator('[data-action="up"]')
    up.focus()
    page.emulate_media(color_scheme="dark")
    page.wait_for_function("document.documentElement.getAttribute('data-theme') === 'dark'")
    expect(up).to_be_focused()
    page.evaluate("window.i18n.setLang('ja')")
    expect(page.locator(".track-item").nth(1).locator('[data-action="up"]')).to_be_focused()
    assert page.locator(".chart-title", has_text="Transfer Function").count() == 1


def test_results_take_the_focus_after_an_analysis_and_a_load(page, tracks):
    single = tracks[0].to_dict()
    page.route("**/analyze", lambda route: route.fulfill(
        body=json.dumps({"type": "result", "data": single}) + "\n", content_type="application/x-ndjson"))
    page.fill("#url-input", "/music/a.wav")
    page.locator("#submit-btn").click()
    expect(page.locator("#results")).to_be_focused()

    page.evaluate("() => {compareSources.length = 0; updateCompareUI(); clearResults();}")
    page.fill("#url-input", "")
    page.route("**/load", lambda route: route.fulfill(json={"loaded": True, "type": "single", "data": single}))
    page.locator("#load-btn").click()
    expect(page.locator("#results")).to_be_focused()
    expect(page.locator(".chart-title", has_text="PSD Spectrum")).to_have_count(1)


def test_redraws_keep_the_focus_in_the_results_and_leave_it_elsewhere(page, tracks):
    page.evaluate("() => {compareSources = ['first.wav', 'second.wav']; updateCompareUI();}")
    page.evaluate("data => renderCompare(data)", compare_tracks(tracks).to_dict())
    page.locator("#results .save-btn").first.focus()
    page.evaluate("window.i18n.setLang('ja')")
    expect(page.locator("#results")).to_be_focused()
    page.locator("#url-input").focus()
    page.evaluate("document.querySelector('#results .chart-title').dataset.before = '1'")
    page.set_viewport_size({"width": 900, "height": 700})
    page.wait_for_function("!document.querySelector('#results .chart-title[data-before]')")
    expect(page.locator("#url-input")).to_be_focused()


@pytest.mark.parametrize("cause", ["resize", "theme", "language"])
def test_redraws_keep_the_scroll_position(page, tracks, cause):
    page.evaluate("data => renderSingle(data)", tracks[0].to_dict())
    page.evaluate("window.scrollTo(0, 150)")
    assert page.evaluate("window.scrollY") == 150
    page.evaluate("document.querySelector('#results .chart-title').dataset.before = '1'")
    if cause == "resize":
        page.set_viewport_size({"width": 1000, "height": 720})
    elif cause == "theme":
        page.evaluate("setThemeMode('dark')")
    else:
        page.evaluate("window.i18n.setLang('ja')")
    page.wait_for_function("!document.querySelector('#results .chart-title[data-before]')")
    assert page.evaluate("window.scrollY") == 150


@pytest.mark.parametrize("focus, settled", [("the field", 150), ("nothing", 0)])
def test_a_resize_goes_back_to_the_position_at_its_start_with_the_field_focused(page, tracks, focus, settled):
    page.evaluate("data => renderSingle(data)", tracks[0].to_dict())
    page.evaluate("window.scrollTo(0, 150)")
    page.evaluate("document.getElementById('url-input').focus({preventScroll: true})" if focus == "the field" else "document.activeElement.blur()")
    # This listener moves the page to the top after the page's own resize listener, before the redraw.
    page.evaluate("addEventListener('resize', () => window.scrollTo(0, 0))")
    page.evaluate("document.querySelector('#results .chart-title').dataset.before = '1'")
    page.evaluate("() => { addEventListener('scroll', () => { window.atScroll = window.scrollY; }, {once: true}); dispatchEvent(new Event('resize')); dispatchEvent(new Event('resize')); }")
    page.wait_for_function("window.atScroll !== undefined")
    assert page.evaluate("window.atScroll") == settled
    page.wait_for_function("!document.querySelector('#results .chart-title[data-before]')")
    assert page.evaluate("window.scrollY") == settled
    page.evaluate("window.scrollTo(0, 300)")
    page.evaluate("document.querySelector('#results .chart-title').dataset.before = '1'")
    page.evaluate("setThemeMode('dark')")
    page.wait_for_function("!document.querySelector('#results .chart-title[data-before]')")
    assert page.evaluate("window.scrollY") == 300


def test_a_redraw_after_a_resize_goes_back_to_the_kept_position_without_a_scroll_event(page, tracks):
    page.evaluate("data => renderSingle(data)", tracks[0].to_dict())
    page.evaluate("window.scrollTo(0, 150)")
    page.evaluate("document.getElementById('url-input').focus({preventScroll: true})")
    # The page moves to the top in the same task as the redraw, before any scroll event.
    page.evaluate("() => { const original = _redrawKeepingFocus; _redrawKeepingFocus = function (container, redraw) { window.scrollTo(0, 0); return original(container, redraw); }; }")
    page.evaluate("document.querySelector('#results .chart-title').dataset.before = '1'")
    page.evaluate("dispatchEvent(new Event('resize'))")
    page.wait_for_function("!document.querySelector('#results .chart-title[data-before]')")
    assert page.evaluate("window.scrollY") == 150
