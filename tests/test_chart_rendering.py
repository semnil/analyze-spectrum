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
                assert {"1/3 Octave Band Analysis", "Transfer Function", "Low-End Detail", "Mid-High Detail"} <= set(fonts)
                for title, used in fonts.items():
                    assert used, title
                    assert all("Segoe UI" in font for font in used), (title, used)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
