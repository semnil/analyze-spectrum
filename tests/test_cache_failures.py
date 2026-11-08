"""Cache fallback and failed analyses through the real HTTP handler."""

import json
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
    (subprocess.CalledProcessError(1, ["ffmpeg", "secret-url"], stderr="y" * 250),
     "ffmpeg failed during PCM extraction: " + "y" * 200),
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


def _stream_request(monkeypatch, send_event):
    """POST /analyze for a.wav with the stream's events handed to ``send_event``; return the raw response body."""
    monkeypatch.setattr(gui.AnalyzeHandler, "_send_event", send_event)
    server = HTTPServer(("127.0.0.1", 0), gui.AnalyzeHandler)
    unhandled = []
    server.handle_error = lambda request, client_address: unhandled.append(client_address)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        status, raw = _post(f"http://127.0.0.1:{server.server_port}", "/analyze", {"url": "a.wav"})
    finally:
        thread.join(timeout=5)
        server.server_close()
    assert status == 200
    assert unhandled == []
    return raw


def test_client_gone_before_the_first_event_stops_the_analysis(isolated_cache, monkeypatch):
    resolve = Mock()
    monkeypatch.setattr(gui, "resolve_source", resolve)
    sent = []

    def gone(self, event_type, **fields):
        sent.append(event_type)
        raise gui._ClientDisconnected()

    assert _stream_request(monkeypatch, gone) == ""
    assert sent == ["progress"]
    resolve.assert_not_called()


@pytest.mark.parametrize("error, expected", [
    (FileNotFoundError("missing decoder"), "missing decoder"),
    (subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"bad input"), "ffmpeg failed during PCM extraction: bad input"),
    (RuntimeError("decode interrupted"), "Analysis failed: decode interrupted"),
], ids=["file_not_found", "ffmpeg_failed", "other"])
def test_client_gone_while_the_error_is_sent_ends_the_stream_quietly(isolated_cache, monkeypatch, error, expected):
    monkeypatch.setattr(gui, "resolve_source", Mock(return_value=("audio.wav", "Clip")))
    monkeypatch.setattr(gui, "probe_info", Mock(return_value=(2, 10.0)))
    monkeypatch.setattr(gui, "extract_audio", Mock(side_effect=error))
    sent = []

    def gone_at_the_error(self, event_type, **fields):
        sent.append((event_type, fields))
        if event_type == "error":
            raise gui._ClientDisconnected()
        self.wfile.write((json.dumps({"type": event_type, **fields}) + "\n").encode())

    raw = _stream_request(monkeypatch, gone_at_the_error)
    assert sent[-1] == ("error", {"error": expected})
    assert all(event_type != "error" for event_type, _ in sent[:-1])
    assert all(event["type"] != "error" for event in _parse_ndjson(raw))
