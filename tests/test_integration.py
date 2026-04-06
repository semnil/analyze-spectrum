"""Integration tests: real HTTPServer + analysis pipeline (no pywebview)."""

import json
import sys
import threading
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure webview mock is in place before gui module is first imported
if "webview" not in sys.modules:
    sys.modules["webview"] = MagicMock()

import analyze_spectrum.gui as _gui_mod  # noqa: E402


@pytest.fixture(scope="module")
def _server():
    """Start the HTTP server once per module on a random port."""
    server = HTTPServer(("127.0.0.1", 0), _gui_mod.AnalyzeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", _gui_mod
    server.shutdown()


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear result cache between tests."""
    _gui_mod._result_cache.clear()
    _gui_mod._result_cache_data.clear()
    yield
    _gui_mod._result_cache.clear()
    _gui_mod._result_cache_data.clear()


def _post(base_url, path, body=None):
    """Send a POST request and return (status, parsed_body)."""
    import urllib.request
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        base_url + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req)
        raw = resp.read().decode()
        return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, raw


def _parse_ndjson(raw: str) -> list[dict]:
    """Parse NDJSON response into list of events."""
    events = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


class TestAnalyzeEndpoint:
    def test_missing_url_returns_400(self, _server):
        base, _ = _server
        status, raw = _post(base, "/analyze", {})
        assert status == 400
        assert "url" in json.loads(raw).get("error", "").lower()

    def test_analyze_local_wav(self, _server, wav_file):
        base, _ = _server
        status, raw = _post(base, "/analyze", {"url": wav_file})
        assert status == 200
        events = _parse_ndjson(raw)
        result_events = [e for e in events if e["type"] == "result"]
        assert len(result_events) == 1
        data = result_events[0]["data"]
        assert "spectrum" in data
        assert "bands" in data
        assert "summary" in data
        assert data["sample_rate"] == 48000
        assert data["meta"]["source"] == wav_file
        assert data["meta"]["schema_version"] >= 1

    def test_analyze_returns_progress_events(self, _server, wav_file):
        base, _ = _server
        _, raw = _post(base, "/analyze", {"url": wav_file})
        events = _parse_ndjson(raw)
        stages = [e.get("stage") for e in events if e["type"] == "progress"]
        assert "pcm" in stages
        assert "analyze" in stages

    def test_analyze_with_duration(self, _server, tmp_path):
        """Duration limit extracts middle portion of a longer file."""
        from tests.conftest import _make_wav_bytes
        # 5-second file, request 0.05 minutes (3 seconds)
        long_wav = str(tmp_path / "long.wav")
        with open(long_wav, "wb") as f:
            f.write(_make_wav_bytes(440.0, 5.0))
        base, _ = _server
        status, raw = _post(base, "/analyze", {"url": long_wav, "duration": 0.05})
        assert status == 200
        events = _parse_ndjson(raw)
        result = [e for e in events if e["type"] == "result"][0]["data"]
        assert result["duration_sec"] <= 3.5

    def test_analyze_invalid_duration(self, _server, wav_file):
        base, _ = _server
        status, raw = _post(base, "/analyze", {"url": wav_file, "duration": -1})
        assert status == 400

    def test_analyze_nonexistent_file(self, _server):
        base, _ = _server
        status, raw = _post(base, "/analyze", {"url": "/nonexistent/file.wav"})
        assert status == 200  # NDJSON stream starts, error sent as event
        events = _parse_ndjson(raw)
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) >= 1

    def test_analyze_cache_hit(self, _server, wav_file):
        base, gui_mod = _server
        # First request — cache miss
        _, raw1 = _post(base, "/analyze", {"url": wav_file})
        events1 = _parse_ndjson(raw1)
        stages1 = [e.get("stage") for e in events1 if e["type"] == "progress"]
        assert "analyze" in stages1

        # Second request — cache hit
        _, raw2 = _post(base, "/analyze", {"url": wav_file})
        events2 = _parse_ndjson(raw2)
        stages2 = [e.get("stage") for e in events2 if e["type"] == "progress"]
        assert "cache" in stages2
        assert "analyze" not in stages2

        # Results should be identical
        r1 = [e for e in events1 if e["type"] == "result"][0]["data"]
        r2 = [e for e in events2 if e["type"] == "result"][0]["data"]
        assert r1["spectrum"] == r2["spectrum"]


class TestCompareEndpoint:
    def test_compare_needs_two_sources(self, _server, wav_file):
        base, _ = _server
        status, raw = _post(base, "/compare", {"sources": [wav_file]})
        assert status == 400

    def test_compare_max_six(self, _server, wav_file):
        base, _ = _server
        status, _ = _post(base, "/compare", {"sources": [wav_file] * 7})
        assert status == 400

    def test_compare_two_tracks(self, _server, wav_file, wav_file_b):
        base, _ = _server
        status, raw = _post(base, "/compare", {"sources": [wav_file, wav_file_b]})
        assert status == 200
        events = _parse_ndjson(raw)
        compare_events = [e for e in events if e["type"] == "compare_result"]
        assert len(compare_events) == 1
        data = compare_events[0]["data"]
        assert len(data["tracks"]) == 2
        assert len(data["transfer_functions"]) == 1
        tf = data["transfer_functions"][0]
        assert "freqs" in tf
        assert "delta_db" in tf

    def test_compare_uses_cache(self, _server, wav_file, wav_file_b):
        base, _ = _server
        # Pre-analyze wav_file to populate cache
        _post(base, "/analyze", {"url": wav_file})

        # Compare should use cache for wav_file
        _, raw = _post(base, "/compare", {"sources": [wav_file, wav_file_b]})
        events = _parse_ndjson(raw)
        stages = [e.get("stage") for e in events if e["type"] == "progress"]
        assert "cache" in stages  # wav_file served from cache

    def test_compare_meta_sources(self, _server, wav_file, wav_file_b):
        base, _ = _server
        _, raw = _post(base, "/compare", {"sources": [wav_file, wav_file_b]})
        events = _parse_ndjson(raw)
        data = [e for e in events if e["type"] == "compare_result"][0]["data"]
        assert data["meta"]["sources"] == [wav_file, wav_file_b]


class TestSaveEndpoint:
    def test_save_missing_data(self, _server):
        base, _ = _server
        status, _ = _post(base, "/save", {"filename": "test.json"})
        assert status == 400

    def test_save_cancel_dialog(self, _server):
        base, gui_mod = _server
        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = None
        status, raw = _post(base, "/save", {"data": {"x": 1}, "filename": "t.json"})
        assert status == 200
        assert json.loads(raw)["saved"] is False

    def test_save_writes_file(self, _server, tmp_path):
        base, gui_mod = _server
        out = str(tmp_path / "result.json")
        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = out
        data = {"spectrum": {"freqs": [100]}, "label": "test"}
        status, raw = _post(base, "/save", {"data": data, "filename": "r.json"})
        assert status == 200
        assert json.loads(raw)["saved"] is True
        saved = json.loads(Path(out).read_text(encoding="utf-8"))
        assert saved == data

    def test_save_from_cache(self, _server, wav_file, tmp_path):
        base, gui_mod = _server
        # Analyze to populate cache
        _post(base, "/analyze", {"url": wav_file})

        out = str(tmp_path / "cached.json")
        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = out
        status, raw = _post(base, "/save", {
            "data": {"placeholder": True},
            "filename": "c.json",
            "source": wav_file,
            "duration": None,
        })
        assert status == 200
        assert json.loads(raw)["saved"] is True
        saved = json.loads(Path(out).read_text(encoding="utf-8"))
        assert "spectrum" in saved  # real data from cache, not placeholder


class TestLoadEndpoint:
    def test_load_cancel(self, _server):
        base, gui_mod = _server
        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = None
        status, raw = _post(base, "/load", {})
        assert status == 200
        assert json.loads(raw)["loaded"] is False

    def test_load_single_json(self, _server, wav_file, tmp_path):
        base, gui_mod = _server
        # Create a valid analysis JSON
        _, raw = _post(base, "/analyze", {"url": wav_file})
        result_data = [e for e in _parse_ndjson(raw) if e["type"] == "result"][0]["data"]

        json_path = str(tmp_path / "single.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f)

        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = [json_path]
        status, raw = _post(base, "/load", {})
        assert status == 200
        resp = json.loads(raw)
        assert resp["loaded"] is True
        assert resp["type"] == "single"
        assert resp["data"]["spectrum"] == result_data["spectrum"]

    def test_load_multi_json(self, _server, wav_file, wav_file_b, tmp_path):
        base, gui_mod = _server
        paths = []
        for wf in [wav_file, wav_file_b]:
            _, raw = _post(base, "/analyze", {"url": wf})
            data = [e for e in _parse_ndjson(raw) if e["type"] == "result"][0]["data"]
            p = str(tmp_path / f"track_{len(paths)}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f)
            paths.append(p)

        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = paths
        status, raw = _post(base, "/load", {})
        assert status == 200
        resp = json.loads(raw)
        assert resp["loaded"] is True
        assert resp["type"] == "multi"
        assert len(resp["items"]) == 2

    def test_load_compare_json_rejected(self, _server, wav_file, wav_file_b, tmp_path):
        """Compare result JSON is no longer supported for loading."""
        base, gui_mod = _server
        _, raw = _post(base, "/compare", {"sources": [wav_file, wav_file_b]})
        data = [e for e in _parse_ndjson(raw) if e["type"] == "compare_result"][0]["data"]

        json_path = str(tmp_path / "compare.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = [json_path]
        status, raw = _post(base, "/load", {})
        assert status == 400
        assert "compare" in json.loads(raw)["error"].lower()

    def test_load_schema_outdated_url(self, _server, wav_file, tmp_path):
        """Loading a JSON with old schema_version and URL source."""
        base, gui_mod = _server
        _, raw = _post(base, "/analyze", {"url": wav_file})
        result_data = [e for e in _parse_ndjson(raw) if e["type"] == "result"][0]["data"]

        # Set schema_version to 0 to simulate old format
        result_data["meta"]["schema_version"] = 0
        result_data["meta"]["source"] = "https://example.com/test"

        json_path = str(tmp_path / "old_schema.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f)

        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = [json_path]
        status, raw = _post(base, "/load", {})
        assert status == 200
        resp = json.loads(raw)
        assert resp["loaded"] is True
        assert resp["schema_outdated"] is True
        assert resp["source_available"] is True

    def test_load_schema_outdated_missing_file(self, _server, wav_file, tmp_path):
        """Loading old schema JSON where the local file no longer exists."""
        base, gui_mod = _server
        _, raw = _post(base, "/analyze", {"url": wav_file})
        result_data = [e for e in _parse_ndjson(raw) if e["type"] == "result"][0]["data"]

        result_data["meta"]["schema_version"] = 0
        result_data["meta"]["source"] = "/nonexistent/old_recording.wav"

        json_path = str(tmp_path / "old_schema_missing.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f)

        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = [json_path]
        status, raw = _post(base, "/load", {})
        assert status == 200
        resp = json.loads(raw)
        assert resp["schema_outdated"] is True
        assert resp["source_available"] is False

    def test_load_schema_outdated_no_version(self, _server, wav_file, tmp_path):
        """JSON without schema_version is treated as outdated."""
        base, gui_mod = _server
        _, raw = _post(base, "/analyze", {"url": wav_file})
        result_data = [e for e in _parse_ndjson(raw) if e["type"] == "result"][0]["data"]

        del result_data["meta"]["schema_version"]

        json_path = str(tmp_path / "no_schema_ver.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f)

        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = [json_path]
        status, raw = _post(base, "/load", {})
        assert status == 200
        resp = json.loads(raw)
        assert resp["schema_outdated"] is True

    def test_load_invalid_json(self, _server, tmp_path):
        base, gui_mod = _server
        bad = str(tmp_path / "bad.json")
        with open(bad, "w") as f:
            json.dump({"foo": "bar"}, f)

        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = [bad]
        status, raw = _post(base, "/load", {})
        assert status == 400

    def test_load_caches_data(self, _server, wav_file, tmp_path):
        base, gui_mod = _server
        _, raw = _post(base, "/analyze", {"url": wav_file})
        result_data = [e for e in _parse_ndjson(raw) if e["type"] == "result"][0]["data"]

        gui_mod._result_cache.clear()  # clear cache

        json_path = str(tmp_path / "to_cache.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f)

        gui_mod._window = MagicMock()
        gui_mod._window.create_file_dialog.return_value = [json_path]
        _post(base, "/load", {})

        # Should now be cached
        cached = gui_mod._cache_get(wav_file, None)
        assert cached is not None
        assert cached["spectrum"] == result_data["spectrum"]


class TestUploadEndpoint:
    def test_upload_empty_rejected(self, _server):
        """Upload with no content is rejected."""
        import urllib.request
        base, _ = _server
        req = urllib.request.Request(
            base + "/upload",
            data=b"",
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": "0",
                "X-Filename": "test.wav",
            },
        )
        try:
            resp = urllib.request.urlopen(req)
            status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 400

    def test_upload_bad_extension_rejected(self, _server):
        """Upload with unsupported extension is rejected."""
        import urllib.request
        base, _ = _server
        payload = b"\x00" * 100
        req = urllib.request.Request(
            base + "/upload",
            data=payload,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(payload)),
                "X-Filename": "malware.exe",
            },
        )
        try:
            resp = urllib.request.urlopen(req)
            status = resp.status
            raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            status = e.code
            raw = e.read().decode()
        assert status == 400
        assert "unsupported" in raw.lower() or "file type" in raw.lower()

    def test_upload_wav_success(self, _server):
        """Upload a valid WAV file."""
        import urllib.request
        from tests.conftest import _make_wav_bytes
        base, _ = _server
        payload = _make_wav_bytes(440.0, 0.1)
        req = urllib.request.Request(
            base + "/upload",
            data=payload,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(payload)),
                "X-Filename": "uploaded.wav",
            },
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        result = json.loads(resp.read().decode())
        assert result["uploaded"] is True
        assert result["path"].endswith(".wav")
