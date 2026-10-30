"""V8 coverage of the frontend scripts the Playwright tests run, written as LCOV.

``Collector.install()`` wraps Playwright's page creation so that every Chromium page starts precise coverage
(``Profiler.startPreciseCoverage``) before it loads anything, and takes it when the page, its context or its browser
is closed. Scripts are matched to ``frontend/*.js`` by URL path, as either server in the tests serves them: the
project root (``/frontend/main.js``) or the app's handler (``/main.js``). ``frontend/vendor/`` and the scripts of
py-analyze-common are left out. A line's hit count is the count of the innermost V8 range that contains all of its
code, summed over pages. Blank lines and lines that start a comment are not counted as code.
"""

import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page

_COMMENT = re.compile(r"(//|/\*|\*)")


def _read(local):
    """The file's text with its line ends as they are on disk, as the test servers serve it."""
    return local.read_bytes().decode("utf-8")


def _utf16_len(text):
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def _code_lines(text):
    """[(line number, start, end)] of the lines that hold code, in the UTF-16 offsets V8 reports."""
    lines = []
    offset = 0
    for number, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()
        if stripped and not _COMMENT.match(stripped):
            lead = _utf16_len(line[:len(line) - len(line.lstrip())])
            lines.append((number, offset + lead, offset + lead + _utf16_len(stripped)))
        offset += _utf16_len(line) + 1
    return lines


class Collector:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.frontend = self.root / "frontend"
        self.hits = {}  # repository path -> {line number: hits}
        self._sessions = {}

    def _source(self, url):
        """Repository path of the frontend script at url, or None."""
        path = urlparse(url).path.lstrip("/")
        if not path.endswith(".js"):
            return None
        local = (self.root / path) if path.startswith("frontend/") else (self.frontend / path)
        local = local.resolve()
        if not local.is_relative_to(self.frontend) or local.is_relative_to(self.frontend / "vendor"):
            return None
        return local if local.is_file() else None

    def _start(self, page):
        browser = page.context.browser
        if browser is None or browser.browser_type.name != "chromium":
            return
        session = page.context.new_cdp_session(page)
        session.send("Profiler.enable")
        session.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})
        self._sessions[page] = session

    def _take(self, page):
        session = self._sessions.pop(page, None)
        if session is None or page.is_closed():
            return
        for script in session.send("Profiler.takePreciseCoverage")["result"]:
            local = self._source(script["url"])
            if local is not None:
                self._add(local, script["functions"])

    def _add(self, local, functions):
        text = _read(local)
        ranges = [r for function in functions for r in function["ranges"]]
        script_end = max(r["endOffset"] for r in ranges)
        assert script_end == _utf16_len(text), (
            f"{local}: the page ran {script_end} UTF-16 units, the file has {_utf16_len(text)}")
        counts = self.hits.setdefault(local.relative_to(self.root).as_posix(), {})
        for number, start, end in _code_lines(text):
            inside = [r for r in ranges if r["startOffset"] <= start and end <= r["endOffset"]]
            innermost = min(inside, key=lambda r: r["endOffset"] - r["startOffset"])
            counts[number] = counts.get(number, 0) + innermost["count"]

    def install(self):
        collector = self

        def wrap_new_page(original):
            def new_page(self, *args, **kwargs):
                page = original(self, *args, **kwargs)
                collector._start(page)
                return page
            return new_page

        def wrap_close(original, pages):
            def close(self, *args, **kwargs):
                for page in pages(self):
                    collector._take(page)
                return original(self, *args, **kwargs)
            return close

        Browser.new_page = wrap_new_page(Browser.new_page)
        BrowserContext.new_page = wrap_new_page(BrowserContext.new_page)
        Page.close = wrap_close(Page.close, lambda page: [page])
        BrowserContext.close = wrap_close(BrowserContext.close, lambda context: list(context.pages))
        Browser.close = wrap_close(
            Browser.close, lambda browser: [page for context in browser.contexts for page in context.pages])

    def write(self, output):
        """Writes every frontend script outside frontend/vendor/, those no test loaded with zero hits."""
        records = []
        for local in sorted(self.frontend.rglob("*.js")):
            if local.is_relative_to(self.frontend / "vendor"):
                continue
            name = local.relative_to(self.root).as_posix()
            counts = self.hits.get(name, {})
            lines = [(number, counts.get(number, 0)) for number, _, _ in _code_lines(_read(local))]
            records.append("\n".join(
                ["TN:", f"SF:{name}"] + [f"DA:{number},{hits}" for number, hits in lines]
                + [f"LF:{len(lines)}", f"LH:{sum(1 for _, hits in lines if hits)}", "end_of_record"]))
        Path(output).write_text("\n".join(records) + "\n", encoding="utf-8")
