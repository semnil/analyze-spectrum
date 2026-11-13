# Testing decisions

> 日本語版は [testing.ja.md](testing.ja.md) を参照してください。

Closed decisions about this repository's tests. How the tests run today is in `AGENTS.md` ("Tests"); this file keeps what was chosen, why, and when to decide again.

## The test page's static server keeps the default accept queue

- **Decision** (2026-11-02): `_test_server` in `tests/test_frontend.py`, the single-threaded `HTTPServer` that serves the project root to `tests/frontend/test_ui.html`, keeps Python's default accept queue (`request_queue_size`, 5). analyze-loudness gave the same fixture a queue of 64 (semnil/analyze-loudness#143); that change is not carried over to this repository.
- **Reason**: `test_ui.html` loads five external scripts, so the page opens at most five connections to the server at a time, which is not more than the default queue. analyze-loudness's test page loads seven and reaches six. The count of six assumes that Chromium opens at most six connections to one host at a time.
- **Reopen when**: a sixth external script is added to `test_ui.html`. The page then reaches six connections at a time, one more than the default queue.
- **Not part of this decision**: the server the app itself runs. py-analyze-common's `GuiServer` (`analyze_common/server.py`) sets `request_queue_size = 64`.
