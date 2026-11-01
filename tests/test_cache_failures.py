"""Cache fallback and failed analyses through the real HTTP handler."""

import subprocess
import threading
from collections import OrderedDict
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

from analyze_spectrum import gui
from tests.test_integration import _parse_ndjson, _post


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(gui, "_cache_dir", str(tmp_path))
    monkeypatch.setattr(gui, "_result_cache", OrderedDict())
    monkeypatch.setattr(gui, "_result_cache_data", OrderedDict())
    monkeypatch.setattr(gui, "_loaded_cache_data", OrderedDict())
    monkeypatch.setattr(gui, "_cache_seq", 0)


def test_disk_fallback_repopulates_memory_and_refreshes_eviction_order(isolated_cache, monkeypatch):
    monkeypatch.setattr(gui, "_CACHE_MAX_ENTRIES", 2)
    a = Path(gui._cache_put("https://a", None, {"value": 1}))
    b = Path(gui._cache_put("https://b", None, {"value": 2}))
    gui._result_cache_data.clear()
    assert gui._cache_get("https://a", None) == {"value": 1}
    assert gui._result_cache_data[("https://a", None)] == {"value": 1}
    gui._cache_put("https://c", None, {"value": 3})
    assert a.exists() and not b.exists()
    assert gui._cache_get("https://a", None) == {"value": 1}
    assert gui._cache_get("https://b", None) is None


@pytest.mark.parametrize("contents", [None, "{broken"])
def test_unreadable_disk_cache_becomes_a_miss(isolated_cache, contents):
    path = Path(gui._cache_put("https://a", None, {"value": 1}))
    gui._result_cache_data.clear()
    if contents is None:
        path.unlink()
    else:
        path.write_text(contents, encoding="utf-8")
    assert gui._cache_get("https://a", None) is None
    assert not gui._result_cache_data


@pytest.mark.parametrize("error, expected", [
    (FileNotFoundError("missing decoder"), "missing decoder"),
    (RuntimeError("decode interrupted"), "Analysis failed: decode interrupted"),
    (subprocess.CalledProcessError(1, ["ffmpeg", "secret-url"], stderr=b"x" * 250),
     "ffmpeg failed during PCM extraction: " + "x" * 200),
    (subprocess.CalledProcessError(1, ["ffmpeg", "secret-url"]), "ffmpeg failed during PCM extraction"),
])
def test_failed_extraction_sends_error_without_result_and_cleans_workdir(isolated_cache, monkeypatch, error, expected):
    resolve = Mock(return_value=("audio.wav", "Clip"))
    monkeypatch.setattr(gui, "resolve_source", resolve)
    monkeypatch.setattr(gui, "probe_info", Mock(return_value=(2, 10.0)))
    monkeypatch.setattr(gui, "extract_audio", Mock(side_effect=error))
    analyze = Mock()
    monkeypatch.setattr(gui, "analyze_track", analyze)
    server = HTTPServer(("127.0.0.1", 0), gui.AnalyzeHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        status, raw = _post(f"http://127.0.0.1:{server.server_port}", "/analyze", {"url": "a.wav"})
        assert status == 200
        events = _parse_ndjson(raw)
        assert events[-1] == {"type": "error", "error": expected}
        assert all(event["type"] != "result" for event in events)
        analyze.assert_not_called()
        assert not gui._result_cache
        assert not Path(resolve.call_args.args[1]).exists()
    finally:
        thread.join(timeout=5)
        server.server_close()
        assert not thread.is_alive()
