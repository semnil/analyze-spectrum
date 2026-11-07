"""Render comparison charts and their PNG export with the real browser scripts."""

import base64
import struct

import numpy as np
import pytest

from analyze_spectrum.analysis import analyze_track, compare_tracks
from tests.test_frontend import _HAS_PLAYWRIGHT, _app_server


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_transfer_curve_and_eq_are_in_the_rendered_comparison_and_export(theme, monkeypatch):
    from playwright.sync_api import sync_playwright
    from analyze_spectrum import gui

    monkeypatch.setattr(gui._updater, "status", lambda: {"supported": False, "launch_check": False})
    samples = np.random.default_rng(7).normal(0, 0.05, 12000)
    tracks = [analyze_track(samples, label="Reference"), analyze_track(samples * 2, label="Louder")]
    data = compare_tracks(tracks).to_dict()
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1100, "height": 800}, device_scale_factor=2, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("window.analyzeUpdate.ready")
                page.evaluate("mode => { window.i18n.setLang('en'); setThemeMode(mode); }", theme)
                page.evaluate("data => { clearResults(); renderCompare(data); }", data)
                page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                assert page.locator(".chart-title", has_text="Transfer Function").count() == 1
                assert "Preamp" in page.locator("#results").inner_text()
                # Sample the gain curve between grid lines and below the legend.
                pixel = page.evaluate("""() => {
                    const canvas = chartCanvasRefs.find(ref => ref.title === 'Transfer Function').canvas;
                    const ratio = window.devicePixelRatio;
                    const x = (55 + (canvas.clientWidth - 75) / 2) * ratio;
                    const gain = 20 * Math.log10(2);
                    const y = (36 + (canvas.clientHeight - 86) * (1 - (gain + 20) / 40)) * ratio;
                    const pixels = canvas.getContext('2d').getImageData(Math.floor(x)-2, Math.floor(y)-2, 5, 5).data;
                    let ink = 0;
                    for (let i = 3; i < pixels.length; i += 4) if (pixels[i]) ink++;
                    return ink;
                }""")
                assert pixel > 0
                exported = page.evaluate("""async data => {
                    const url = captureImage(data);
                    const image = new Image();
                    image.src = url;
                    await image.decode();
                    const canvas = document.createElement('canvas');
                    canvas.width = image.width; canvas.height = image.height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(image, 0, 0);
                    const color = getThemeColors().trackColors[0].slice(1).match(/../g).map(value => parseInt(value, 16));
                    const pixels = ctx.getImageData(0, 2400, canvas.width, canvas.height - 2400).data;
                    let chartPixels = 0;
                    for (let i = 0; i < pixels.length; i += 4)
                        if (color.every((value, channel) => pixels[i+channel] === value)) chartPixels++;
                    return {url, chartPixels};
                }""", data)
                assert exported["chartPixels"] > 0
                png = base64.b64decode(exported["url"].split(",", 1)[1])
                assert png[:8] == b"\x89PNG\r\n\x1a\n"
                width, height = struct.unpack(">II", png[16:24])
                assert width == 2200
                assert height > 2500
                assert errors == []
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_chart_text_is_drawn_in_the_font_of_the_page(monkeypatch):
    from playwright.sync_api import sync_playwright
    from analyze_spectrum import gui

    monkeypatch.setattr(gui._updater, "status", lambda: {"supported": False, "launch_check": False})
    samples = np.random.default_rng(7).normal(0, 0.05, 12000)
    tracks = [analyze_track(samples, label="Reference"), analyze_track(samples * 2, label="Louder")]
    data = compare_tracks(tracks).to_dict()
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1100, "height": 800}, locale="en-US")
                page.add_init_script("""
                    window.__chartFonts = new Map();
                    const fillText = CanvasRenderingContext2D.prototype.fillText;
                    CanvasRenderingContext2D.prototype.fillText = function (...args) {
                        const fonts = window.__chartFonts.get(this.canvas) || new Set();
                        window.__chartFonts.set(this.canvas, fonts.add(this.font));
                        return fillText.apply(this, args);
                    };
                """)
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("window.analyzeUpdate.ready")
                page.evaluate("window.i18n.setLang('en')")
                page.evaluate("data => { clearResults(); renderCompare(data); }", data)
                page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                fonts = page.evaluate("""() => Object.fromEntries(chartCanvasRefs.map(
                    ref => [ref.title, Array.from(window.__chartFonts.get(ref.canvas) || [])]))""")
                assert {"PSD Spectrum", "1/3 Octave Band Analysis", "Transfer Function", "Low-End Detail", "Mid-High Detail"} <= set(fonts)
                page_families = page.evaluate("getComputedStyle(document.body).fontFamily").split(", ")
                for title, used in fonts.items():
                    assert used, title
                    assert all(font.split("px ", 1)[1].split(", ") == page_families for font in used), (title, used)
                legend = page.evaluate("getComputedStyle(document.querySelector('.u-legend .u-label')).fontFamily")
                assert legend.split(", ") == page_families
                exported = page.evaluate("""data => {
                    window.__chartFonts.clear();
                    captureImage(data);
                    return Array.from(window.__chartFonts.values()).flatMap(fonts => Array.from(fonts));
                }""", data)
                assert exported
                assert all(font.split("px ", 1)[1].split(", ") == page_families for font in exported), exported
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


_TEXT_RECORDER = """
    window.__texts = [];
    window.__lines = [];
    const fillText = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (text, x, y, ...rest) {
        const size = this.measureText(String(text));
        const left = this.textAlign === 'center' ? x - size.width / 2 : this.textAlign === 'right' ? x - size.width : x;
        const m = this.getTransform();
        const corners = [
            [left, y - size.actualBoundingBoxAscent], [left + size.width, y - size.actualBoundingBoxAscent],
            [left, y + size.actualBoundingBoxDescent], [left + size.width, y + size.actualBoundingBoxDescent],
        ].map(([cx, cy]) => [m.a * cx + m.c * cy + m.e, m.b * cx + m.d * cy + m.f]);
        window.__texts.push({
            text: String(text), canvas: this.canvas, align: this.textAlign, y,
            x0: Math.min(...corners.map(c => c[0])), x1: Math.max(...corners.map(c => c[0])),
            y0: Math.min(...corners.map(c => c[1])), y1: Math.max(...corners.map(c => c[1])),
        });
        return fillText.call(this, text, x, y, ...rest);
    };
    const moveTo = CanvasRenderingContext2D.prototype.moveTo;
    const lineTo = CanvasRenderingContext2D.prototype.lineTo;
    CanvasRenderingContext2D.prototype.moveTo = function (x, y) { this.__from = [x, y]; return moveTo.call(this, x, y); };
    CanvasRenderingContext2D.prototype.lineTo = function (x, y) {
        if (this.__from && this.__from[1] === y) window.__lines.push({y, length: Math.abs(x - this.__from[0])});
        return lineTo.call(this, x, y);
    };
"""


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("low, high, step", [(-10, 10, 5), (-25, 25, 5), (-60, 30, 10), (-110, 95, 20), (-210, 210, 50)])
def test_transfer_tick_labels_stay_apart_on_any_range(low, high, step, monkeypatch):
    from playwright.sync_api import sync_playwright
    from analyze_spectrum import gui

    monkeypatch.setattr(gui._updater, "status", lambda: {"supported": False, "launch_check": False})
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1100, "height": 800}, locale="en-US")
                page.add_init_script(_TEXT_RECORDER)
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("window.analyzeUpdate.ready")
                ticks = page.evaluate("""([low, high]) => {
                    const canvas = document.createElement('canvas');
                    canvas.style.cssText = 'display:block;width:1000px;height:280px';
                    document.body.appendChild(canvas);
                    window.__texts.length = 0;
                    window.__lines.length = 0;
                    renderTransfer(canvas, [{label: 'A', freqs: [20, 1000, 20000], delta_db: [low, 0, high]}]);
                    return {
                        labels: window.__texts.filter(t => t.align === 'right').map(t => ({db: Number(t.text), y: t.y})),
                        lines: window.__lines.slice(),
                    };
                }""", [low, high])
                values = [tick["db"] for tick in ticks["labels"]]
                assert 0 in values
                assert all(value % step == 0 for value in values)
                assert all(b - a == step for a, b in zip(values, values[1:]))
                gaps = [a["y"] - b["y"] for a, b in zip(ticks["labels"], ticks["labels"][1:])]
                assert min(gaps) >= 14
                # Each label sits 3 px below its grid line, which spans the plot; the legend's swatches are short.
                grid = {round(line["y"], 3) for line in ticks["lines"] if line["length"] > 100}
                assert {round(tick["y"] - 3, 3) for tick in ticks["labels"]} == grid
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("names", [
    ["A", "B", "C", "D", "E", "F"],
    ["ノイズ一", "ノイズ二", "ノイズ三", "ノイズ四", "ノイズ五", "ノイズ六"],
    [f"Track {i} Official Audio Remaster Live At Some Very Long Venue Name" for i in range(6)],
    [f"とても長い日本語の題名がついた動画の音声トラック番号{i}を比較するための試料です" * 2 for i in range(6)],
], ids=["short", "short_ja", "long", "long_ja"])
def test_legend_stays_clear_of_other_chart_text_and_on_the_canvas(names, monkeypatch):
    from playwright.sync_api import sync_playwright
    from analyze_spectrum import gui

    monkeypatch.setattr(gui._updater, "status", lambda: {"supported": False, "launch_check": False})
    samples = np.random.default_rng(7).normal(0, 0.05, 12000)
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (1100, 900, 500):
                    page = browser.new_page(viewport={"width": width, "height": 800}, locale="en-US")
                    page.add_init_script(_TEXT_RECORDER)
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.evaluate("window.analyzeUpdate.ready")
                    page.evaluate("window.i18n.setLang('en')")
                    for count in (2, 6):
                        tracks = [analyze_track(samples * (i + 1), label=names[i]) for i in range(count)]
                        data = compare_tracks(tracks).to_dict()
                        problems = page.evaluate("""data => {
                            window.__texts.length = 0;
                            clearResults();
                            renderCompare(data);
                            const labels = data.tracks.map(t => t.label).concat(data.transfer_functions.map(t => t.label));
                            const isLegend = text => labels.includes(text) ||
                                (text.endsWith('...') && labels.some(label => label.startsWith(text.slice(0, -3))));
                            const problems = [];
                            let legends = 0;
                            for (const ref of chartCanvasRefs) {
                                const texts = window.__texts.filter(t => t.canvas === ref.canvas);
                                for (const a of texts.filter(t => isLegend(t.text))) {
                                    legends++;
                                    if (a.x0 < 0 || a.x1 > ref.canvas.clientWidth) problems.push([ref.title, 'off the canvas', a.text]);
                                    for (const b of texts) {
                                        if (a === b) continue;
                                        if (Math.min(a.x1, b.x1) > Math.max(a.x0, b.x0) && Math.min(a.y1, b.y1) > Math.max(a.y0, b.y0))
                                            problems.push([ref.title, a.text, b.text]);
                                    }
                                }
                            }
                            return {legends, problems};
                        }""", data)
                        assert problems["legends"] >= 3 * count, (width, count)
                        assert problems["problems"] == [], (width, count)
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_truncated_text_keeps_whole_characters(monkeypatch):
    from playwright.sync_api import sync_playwright
    from analyze_spectrum import gui

    monkeypatch.setattr(gui._updater, "status", lambda: {"supported": False, "launch_check": False})
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                results = page.evaluate(r"""() => {
                    const ctx = document.createElement('canvas').getContext('2d');
                    const text = '\u{1F3B5}'.repeat(40);
                    const full = ctx.measureText(text).width;
                    const rows = [];
                    for (let maxW = 20; maxW < full; maxW += 3) rows.push(_truncText(ctx, text, maxW));
                    return {rows, lone: rows.filter(row => /[\uD800-\uDBFF]\.\.\.$/.test(row)).length};
                }""")
                assert results["rows"]
                assert results["lone"] == 0
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_marker_labels_take_a_second_row_and_are_left_out_when_they_do_not_fit(monkeypatch):
    from playwright.sync_api import sync_playwright
    from analyze_spectrum import gui

    monkeypatch.setattr(gui._updater, "status", lambda: {"supported": False, "launch_check": False})
    samples = np.random.default_rng(7).normal(0, 0.05, 12000)
    base = compare_tracks([analyze_track(samples, label=name) for name in "ABCD"]).to_dict()
    server = _app_server("analyze_spectrum.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1200, "height": 900}, locale="en-US")
                page.add_init_script(_TEXT_RECORDER)
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("window.analyzeUpdate.ready")
                page.evaluate("window.i18n.setLang('en')")

                def draw(hf, hpf):
                    return page.evaluate("""({data, hf, hpf}) => {
                        data.tracks.forEach((track, i) => {
                            track.summary.hf_rolloff_hz = hf[i] ?? null;
                            track.summary.hpf_3db_hz = hpf[i] ?? null;
                        });
                        window.__texts.length = 0;
                        window.__lines.length = 0;
                        clearResults();
                        renderCompare(data);
                        const rows = {};
                        for (const ref of chartCanvasRefs) {
                            const texts = window.__texts.filter(t => t.canvas === ref.canvas);
                            const labels = texts.filter(t => /^(HF|HPF) /.test(t.text));
                            if (labels.length) rows[ref.title] = {
                                labels: labels.map(t => ({text: t.text, y: t.y, x0: t.x0, x1: t.x1, y0: t.y0, y1: t.y1})),
                                others: texts.filter(t => !/^(HF|HPF) /.test(t.text)).map(t => ({x0: t.x0, x1: t.x1, y0: t.y0, y1: t.y1})),
                                bottom: ref.canvas.clientHeight,
                            };
                        }
                        return rows;
                    }""", {"data": base, "hf": hf, "hpf": hpf})

                def assert_clear(row):
                    every = row["labels"] + row["others"]
                    for label in row["labels"]:
                        assert label["y1"] <= row["bottom"]
                        for other in every:
                            if other is not label:
                                assert not (min(label["x1"], other["x1"]) > max(label["x0"], other["x0"])
                                            and min(label["y1"], other["y1"]) > max(label["y0"], other["y0"])), (label, other)

                apart = draw([13000, 16800], [59, 117])
                assert [label["text"] for label in apart["Mid-High Detail"]["labels"]] == ["HF 13.0kHz", "HF 16.8kHz"]
                assert len({label["y"] for label in apart["Mid-High Detail"]["labels"]}) == 1
                assert [label["text"] for label in apart["Low-End Detail"]["labels"]] == ["HPF 59Hz", "HPF 117Hz"]
                assert len({label["y"] for label in apart["Low-End Detail"]["labels"]}) == 1

                near = draw([16800, 18700, 17000, 17500], [82, 94, 88, 90])
                for title, count in (("Mid-High Detail", 2), ("Low-End Detail", 2)):
                    row = near[title]
                    assert len(row["labels"]) == count, row["labels"]
                    assert len({label["y"] for label in row["labels"]}) == 2
                    assert_clear(row)

                # At the middle of Mid-High Detail's log axis the second row would reach the axis title.
                at_title = draw([3100, 3200], [])["Mid-High Detail"]
                assert [label["text"] for label in at_title["labels"]] == ["HF 3.1kHz"]
                assert_clear(at_title)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
