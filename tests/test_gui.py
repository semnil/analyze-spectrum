"""Tests for analyze_spectrum.gui module."""

import importlib
import json
import os
import threading
from unittest.mock import patch, MagicMock

import pytest

# Imported before _mock_webview patches sys.modules: numpy / scipy modules first
# imported inside the patch are dropped from sys.modules when it ends, and numpy
# refuses to load its C extensions a second time in one process.
import analyze_spectrum.analysis  # noqa: F401


@pytest.fixture(autouse=True)
def _mock_webview():
    """Mock webview for all tests in this module."""
    with patch.dict("sys.modules", {"webview": MagicMock()}):
        import analyze_spectrum.gui as gui_mod
        importlib.reload(gui_mod)
        yield gui_mod


@pytest.fixture()
def _clear_cache(_mock_webview):
    """Clear the module-level result cache before and after each test."""
    gui_mod = _mock_webview
    gui_mod._result_cache.clear()
    yield gui_mod
    gui_mod._result_cache.clear()


class TestAnalyzeHandler:
    def test_gui_module_imports(self, _mock_webview):
        gui_mod = _mock_webview
        assert hasattr(gui_mod, "AnalyzeHandler")
        assert hasattr(gui_mod, "main")

    def test_is_url(self, _mock_webview):
        from analyze_spectrum.download import is_url
        assert is_url("https://www.youtube.com/watch?v=abc")
        assert is_url("http://example.com")
        assert not is_url("/path/to/file.m4a")
        assert not is_url("file.wav")

    def test_dialog_path_none(self, _mock_webview):
        gui_mod = _mock_webview
        assert gui_mod.AnalyzeHandler._dialog_path(None) is None
        assert gui_mod.AnalyzeHandler._dialog_path("") is None
        assert gui_mod.AnalyzeHandler._dialog_path([]) is None

    def test_dialog_path_string(self, _mock_webview):
        gui_mod = _mock_webview
        assert gui_mod.AnalyzeHandler._dialog_path("/tmp/file.json") == "/tmp/file.json"

    def test_dialog_path_list(self, _mock_webview):
        gui_mod = _mock_webview
        assert gui_mod.AnalyzeHandler._dialog_path(["/tmp/file.json"]) == "/tmp/file.json"

    def test_frontend_dir_exists(self, _mock_webview):
        gui_mod = _mock_webview
        assert gui_mod.FRONTEND_DIR.name == "frontend"

    def test_parse_duration_none(self, _mock_webview):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        assert handler._parse_duration({}) is None

    def test_parse_duration_valid(self, _mock_webview):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        assert handler._parse_duration({"duration": 2.5}) == 2.5
        assert handler._parse_duration({"duration": "3"}) == 3.0

    def test_parse_duration_invalid(self, _mock_webview):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        assert isinstance(handler._parse_duration({"duration": -1}), str)
        assert isinstance(handler._parse_duration({"duration": 0}), str)
        assert isinstance(handler._parse_duration({"duration": "abc"}), str)

    def test_parse_duration_non_scalar(self, _mock_webview):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        assert isinstance(handler._parse_duration({"duration": [1]}), str)
        assert isinstance(handler._parse_duration({"duration": {"v": 1}}), str)

    @pytest.mark.parametrize("duration, message", [
        (True, "'duration' must be a number, not bool"),
        (float("nan"), "'duration' must be a finite number"),
        (float("inf"), "'duration' must be a finite number"),
        (-1, "'duration' must be a positive number"),
        (0.005, "'duration' must be >= 0.01 minutes"),
        (240.001, "'duration' must be <= 240 minutes"),
        ("abc", "'duration' must be a number"),
    ])
    def test_parse_duration_messages(self, _mock_webview, duration, message):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        assert handler._parse_duration({"duration": duration}) == message

    def test_parse_duration_accepts_the_minimum(self, _mock_webview):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        assert handler._parse_duration({"duration": 0.01}) == 0.01

    def test_parse_duration_accepts_the_maximum(self, _mock_webview):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        assert handler._parse_duration({"duration": 240}) == 240.0

    def test_frozen_app_reads_bundled_resources_from_the_bundle(self, _mock_webview, monkeypatch, tmp_path):
        gui_mod = _mock_webview
        monkeypatch.setattr(gui_mod.sys, "frozen", True, raising=False)
        monkeypatch.setattr(gui_mod.sys, "_MEIPASS", str(tmp_path), raising=False)
        assert gui_mod._get_base_dir() == tmp_path

    def test_audio_types_defined(self, _mock_webview):
        gui_mod = _mock_webview
        types = gui_mod.AnalyzeHandler._AUDIO_TYPES
        assert isinstance(types, tuple)
        assert "*.wav" in types[0]
        assert "*.mp3" in types[0]

    def test_upload_dir_exists(self, _mock_webview):
        import os
        gui_mod = _mock_webview
        assert os.path.isdir(gui_mod._upload_dir)

    def test_max_upload_limit(self, _mock_webview):
        gui_mod = _mock_webview
        assert gui_mod.AnalyzeHandler._MAX_UPLOAD == 500 * 1024 * 1024

    def test_handler_routes_include_browse_upload(self, _mock_webview):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        assert hasattr(handler, "_handle_browse")
        assert hasattr(handler, "_handle_upload")

    def test_client_disconnected_exception(self, _mock_webview):
        gui_mod = _mock_webview
        assert hasattr(gui_mod, "_ClientDisconnected")
        exc = gui_mod._ClientDisconnected()
        assert isinstance(exc, Exception)

    def test_send_event_raises_on_broken_pipe(self, _mock_webview):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        handler.request = MagicMock()
        handler.request.sendall.side_effect = BrokenPipeError()
        with pytest.raises(gui_mod._ClientDisconnected):
            handler._send_event("progress", message="test")

    def test_send_event_raises_on_connection_reset(self, _mock_webview):
        gui_mod = _mock_webview
        handler = gui_mod.AnalyzeHandler.__new__(gui_mod.AnalyzeHandler)
        handler.request = MagicMock()
        handler.request.sendall.side_effect = ConnectionResetError()
        with pytest.raises(gui_mod._ClientDisconnected):
            handler._send_event("progress", message="test")


class TestCacheKey:
    def test_url_key_no_mtime(self, _clear_cache):
        gui_mod = _clear_cache
        key = gui_mod._cache_key("https://example.com/video", None)
        assert key == ("https://example.com/video", None)

    def test_url_key_with_duration(self, _clear_cache):
        gui_mod = _clear_cache
        key = gui_mod._cache_key("https://example.com/video", 2.5)
        assert key == ("https://example.com/video", 2.5)

    def test_local_file_key_includes_mtime(self, _clear_cache, tmp_path):
        gui_mod = _clear_cache
        f = tmp_path / "test.wav"
        f.write_bytes(b"\x00" * 100)
        key = gui_mod._cache_key(str(f), None)
        assert len(key) == 3
        assert key[0] == str(f)
        assert key[1] is None
        assert isinstance(key[2], float)
        assert key[2] == os.path.getmtime(str(f))

    def test_nonexistent_local_file_no_mtime(self, _clear_cache):
        gui_mod = _clear_cache
        key = gui_mod._cache_key("/nonexistent/path.wav", 1.0)
        assert key == ("/nonexistent/path.wav", 1.0)

    def test_different_duration_different_key(self, _clear_cache):
        gui_mod = _clear_cache
        k1 = gui_mod._cache_key("https://example.com/a", None)
        k2 = gui_mod._cache_key("https://example.com/a", 3.0)
        assert k1 != k2


class TestCachePutGet:
    def test_put_then_get_returns_same_data(self, _clear_cache):
        gui_mod = _clear_cache
        data = {"label": "test", "spectrum": {"freqs": [100, 200], "psd_db": [-10, -20]}}
        gui_mod._cache_put("https://example.com/a", None, data)
        result = gui_mod._cache_get("https://example.com/a", None)
        assert result == data

    def test_get_before_put_returns_none(self, _clear_cache):
        gui_mod = _clear_cache
        result = gui_mod._cache_get("https://example.com/missing", None)
        assert result is None

    def test_different_duration_is_separate_entry(self, _clear_cache):
        gui_mod = _clear_cache
        data1 = {"label": "full"}
        data2 = {"label": "partial"}
        gui_mod._cache_put("https://example.com/a", None, data1)
        gui_mod._cache_put("https://example.com/a", 2.0, data2)
        assert gui_mod._cache_get("https://example.com/a", None) == data1
        assert gui_mod._cache_get("https://example.com/a", 2.0) == data2

    def test_put_returns_path(self, _clear_cache):
        gui_mod = _clear_cache
        path = gui_mod._cache_put("https://example.com/a", None, {"x": 1})
        assert os.path.isfile(path)
        content = json.loads(open(path, encoding="utf-8").read())
        assert content == {"x": 1}

    def test_put_overwrites_same_key(self, _clear_cache):
        gui_mod = _clear_cache
        gui_mod._cache_put("https://example.com/a", None, {"v": 1})
        gui_mod._cache_put("https://example.com/a", None, {"v": 2})
        assert gui_mod._cache_get("https://example.com/a", None) == {"v": 2}

    def test_local_file_cache_with_mtime(self, _clear_cache, tmp_path):
        gui_mod = _clear_cache
        f = tmp_path / "audio.wav"
        f.write_bytes(b"\x00" * 100)
        data = {"label": "local"}
        gui_mod._cache_put(str(f), None, data)
        assert gui_mod._cache_get(str(f), None) == data


class TestCacheEviction:
    def test_replacing_an_entry_whose_file_is_gone_still_stores_the_new_one(self, _clear_cache):
        gui_mod = _clear_cache
        old = gui_mod._cache_put("https://example.com/a", None, {"v": 1})
        os.unlink(old)
        new = gui_mod._cache_put("https://example.com/a", None, {"v": 2})
        assert new != old
        assert json.loads(open(new, encoding="utf-8").read()) == {"v": 2}
        assert gui_mod._cache_get("https://example.com/a", None) == {"v": 2}

    def test_disk_read_of_an_entry_evicted_meanwhile_is_not_kept_in_memory(self, _clear_cache, monkeypatch):
        gui_mod = _clear_cache
        key = gui_mod._cache_key("https://example.com/a", None)
        path = gui_mod._cache_put("https://example.com/a", None, {"v": 1})
        gui_mod._result_cache_data.clear()
        real_path = gui_mod.Path

        class EvictedWhileReading:
            def __init__(self, name):
                self._path = real_path(name)

            def read_text(self, *args, **kwargs):
                text = self._path.read_text(*args, **kwargs)
                gui_mod._result_cache.pop(key)
                return text

        monkeypatch.setattr(gui_mod, "Path", EvictedWhileReading)
        assert gui_mod._cache_get("https://example.com/a", None) == {"v": 1}
        assert key not in gui_mod._result_cache_data
        assert os.path.isfile(path)


class TestCacheFile:
    def test_returns_none_before_put(self, _clear_cache):
        gui_mod = _clear_cache
        assert gui_mod._cache_file("https://example.com/a", None) is None

    def test_returns_path_after_put(self, _clear_cache):
        gui_mod = _clear_cache
        expected = gui_mod._cache_put("https://example.com/a", None, {"x": 1})
        result = gui_mod._cache_file("https://example.com/a", None)
        assert result == expected
        assert os.path.isfile(result)

    def test_returns_none_if_file_deleted(self, _clear_cache):
        gui_mod = _clear_cache
        path = gui_mod._cache_put("https://example.com/a", None, {"x": 1})
        os.unlink(path)
        assert gui_mod._cache_file("https://example.com/a", None) is None


class TestTransferFunctionsFromDicts:
    def test_single_track_returns_empty(self, _clear_cache):
        gui_mod = _clear_cache
        result = gui_mod._transfer_functions_from_dicts([
            {"label": "A", "spectrum": {"freqs": [100, 200], "psd_db": [-10, -20]}},
        ])
        assert result == []

    def test_empty_list_returns_empty(self, _clear_cache):
        gui_mod = _clear_cache
        assert gui_mod._transfer_functions_from_dicts([]) == []

    def test_two_tracks_same_freqs(self, _clear_cache):
        gui_mod = _clear_cache
        tracks = [
            {"label": "ref", "spectrum": {"freqs": [100, 200, 400], "psd_db": [-20, -30, -40]}},
            {"label": "eq", "spectrum": {"freqs": [100, 200, 400], "psd_db": [-18, -28, -42]}},
        ]
        result = gui_mod._transfer_functions_from_dicts(tracks)
        assert len(result) == 1
        assert result[0]["label"] == "eq \u2212 ref"
        assert result[0]["freqs"] == [100, 200, 400]
        assert result[0]["delta_db"] == [2.0, 2.0, -2.0]
        eq = result[0]["eq"]
        assert set(eq) == {"preamp_db", "bands", "residual_rms_db", "fit_range_hz"}
        assert eq["fit_range_hz"] == [20.0, 400.0]

    def test_reference_without_spectrum_bins_returns_empty(self, _clear_cache):
        gui_mod = _clear_cache
        tracks = [
            {"label": "ref", "spectrum": {"freqs": [], "psd_db": []}},
            {"label": "other", "spectrum": {"freqs": [100, 200], "psd_db": [-10, -20]}},
        ]
        assert gui_mod._transfer_functions_from_dicts(tracks) == []

    def test_track_without_spectrum_bins_is_skipped(self, _clear_cache):
        gui_mod = _clear_cache
        tracks = [
            {"label": "A", "spectrum": {"freqs": [100, 200], "psd_db": [-20, -30]}},
            {"label": "empty", "spectrum": {"freqs": [], "psd_db": []}},
            {"label": "C", "spectrum": {"freqs": [100, 200], "psd_db": [-19, -31]}},
        ]
        result = gui_mod._transfer_functions_from_dicts(tracks)
        assert [tf["label"] for tf in result] == ["C \u2212 A"]

    def test_sample_rate_mismatch_warns_and_clips_to_the_common_band(self, _clear_cache):
        gui_mod = _clear_cache
        tracks = [
            {"label": "ref", "sample_rate": 48000, "spectrum": {"freqs": [100, 200, 400], "psd_db": [-20, -30, -40]}},
            {"label": "other", "sample_rate": 44100, "spectrum": {"freqs": [100, 200], "psd_db": [-22, -28]}},
        ]
        tf = gui_mod._transfer_functions_from_dicts(tracks)[0]
        assert tf["warning"] == "sample rate mismatch (48000 vs 44100); clipped to 200 Hz"
        assert tf["freqs"] == [100, 200]

    def test_matching_or_unknown_sample_rates(self, _clear_cache):
        gui_mod = _clear_cache
        spectrum = {"freqs": [100, 200], "psd_db": [-20, -30]}
        same = gui_mod._transfer_functions_from_dicts([
            {"label": "A", "sample_rate": 48000, "spectrum": spectrum},
            {"label": "B", "sample_rate": 48000, "spectrum": spectrum},
        ])[0]
        unknown = gui_mod._transfer_functions_from_dicts([
            {"label": "A", "sample_rate": 48000, "spectrum": spectrum},
            {"label": "B", "spectrum": spectrum},
        ])[0]
        assert "warning" not in same
        assert unknown["warning"] == "sample_rate unknown; frequency comparison may be approximate"

    def test_three_tracks(self, _clear_cache):
        gui_mod = _clear_cache
        tracks = [
            {"label": "A", "spectrum": {"freqs": [100, 200], "psd_db": [-20, -30]}},
            {"label": "B", "spectrum": {"freqs": [100, 200], "psd_db": [-22, -28]}},
            {"label": "C", "spectrum": {"freqs": [100, 200], "psd_db": [-19, -31]}},
        ]
        result = gui_mod._transfer_functions_from_dicts(tracks)
        assert len(result) == 2
        assert result[0]["label"] == "B \u2212 A"
        assert result[1]["label"] == "C \u2212 A"

    def test_different_freq_grids_interpolates(self, _clear_cache):
        gui_mod = _clear_cache
        tracks = [
            {"label": "ref", "spectrum": {"freqs": [100, 200, 400], "psd_db": [-20, -30, -40]}},
            {"label": "other", "spectrum": {"freqs": [50, 150, 300, 500], "psd_db": [-15, -25, -35, -45]}},
        ]
        result = gui_mod._transfer_functions_from_dicts(tracks)
        assert len(result) == 1
        assert result[0]["freqs"] == [100, 200, 400]
        # delta_db should be computed via interpolation
        assert len(result[0]["delta_db"]) == 3
        # Verify values are rounded to 2 decimal places
        for v in result[0]["delta_db"]:
            assert v == round(v, 2)


def _parallel_get_failures(server, rounds=5, parallel=24):
    """Open ``parallel`` connections at once per round; return the failed requests."""
    import socket
    port = server.server_address[1]
    failures = []

    def one():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
                s.sendall(b"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                data = b""
                while chunk := s.recv(65536):
                    data += chunk
            if not data.startswith(b"HTTP/1.0 200"):
                failures.append(data[:40])
        except OSError as e:
            failures.append(type(e).__name__)

    for _ in range(rounds):
        threads = [threading.Thread(target=one) for _ in range(parallel)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    return failures


class TestHTTPServerBacklog:
    def test_parallel_page_load_connections_are_all_served(self, _mock_webview):
        gui_mod = _mock_webview
        srv = gui_mod._HTTPServer(("127.0.0.1", 0), gui_mod.AnalyzeHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            assert _parallel_get_failures(srv) == []
        finally:
            srv.shutdown()
            srv.server_close()


class TestCommonCss:
    def _get(self, handler_class, path):
        import http.client
        from http.server import HTTPServer
        srv = HTTPServer(("127.0.0.1", 0), handler_class)
        t = threading.Thread(target=srv.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("GET", path, headers={"Host": "127.0.0.1"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        t.join(timeout=5)
        srv.server_close()
        return resp, body

    def test_common_css_served_from_analyze_common(self, _mock_webview):
        from analyze_common.web import COMMON_CSS
        resp, body = self._get(_mock_webview.AnalyzeHandler, "/common/common.css?v=1")
        assert resp.status == 200
        assert resp.getheader("Content-Type").startswith("text/css")
        assert body == COMMON_CSS.read_bytes()

    def test_index_loads_common_css_before_style_css(self, _mock_webview):
        from pathlib import Path
        html = (Path(_mock_webview.FRONTEND_DIR) / "index.html").read_text(encoding="utf-8")
        assert 0 <= html.index('href="common/common.css"') < html.index('href="style.css"')


class TestContentTypeGate:
    """Simple (no-preflight) cross-origin content types are refused."""

    def _post(self, gui_mod, path, body, headers):
        import http.client
        from http.server import HTTPServer
        srv = HTTPServer(("127.0.0.1", 0), gui_mod.AnalyzeHandler)
        t = threading.Thread(target=srv.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("POST", path, body=body, headers={"Content-Length": str(len(body)), **headers})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        t.join(timeout=5)
        srv.server_close()
        return resp.status, data

    @pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", ""])
    def test_analyze_rejects_simple_types(self, _mock_webview, tmp_path, ctype):
        body = json.dumps({"url": str(tmp_path / "a.wav")}).encode()
        headers = {"Content-Type": ctype} if ctype else {}
        status, data = self._post(_mock_webview, "/analyze", body, headers)
        assert status == 415
        assert b"Loading file" not in data

    def test_json_with_charset_reaches_the_handler(self, _mock_webview):
        status, data = self._post(_mock_webview, "/save-image", b"{}",
                                  {"Content-Type": "application/json; charset=utf-8"})
        assert status != 415
        assert b"Content-Type must be" not in data

    def test_upload_needs_octet_stream(self, _mock_webview):
        from urllib.parse import quote
        status, _ = self._post(_mock_webview, "/upload", b"x",
                               {"Content-Type": "text/plain", "X-Filename": quote("a.wav")})
        assert status == 415


class _FakeUpdater:
    """Stands in for analyze_common.update.Updater behind the update endpoints."""

    def __init__(self, check=None, install=None, supported=True, launch_check=True, save_error=None):
        self._check = check
        self._install = install
        self._supported = supported
        self._launch_check = launch_check
        self._save_error = save_error
        self.installed = []
        self.saved = []

    def status(self):
        return {"current": "1.0.0", "supported": self._supported, "launch_check": self._launch_check}

    def launch_check(self):
        return self._launch_check

    def set_launch_check(self, on):
        if self._save_error is not None:
            raise self._save_error
        self.saved.append(on)
        self._launch_check = on

    def check(self):
        if isinstance(self._check, Exception):
            raise self._check
        return self._check

    def install(self, version):
        self.installed.append(version)
        if isinstance(self._install, Exception):
            raise self._install
        return self._install


class TestUpdateEndpoints:
    def _request(self, gui, method, path, body=b"", headers=None):
        import http.client
        from http.server import HTTPServer
        server = HTTPServer(("127.0.0.1", 0), gui.AnalyzeHandler)
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        all_headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        all_headers.update(headers or {})
        connection.request(method, path, body=body or None, headers=all_headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        thread.join(timeout=5)
        server.server_close()
        return response, data

    def _post(self, gui, path, obj=None, headers=None):
        response, data = self._request(gui, "POST", path, json.dumps(obj or {}).encode(), headers)
        return response.status, json.loads(data) if data.startswith(b"{") else data

    def test_update_js_served_from_analyze_common(self, _mock_webview):
        from analyze_common.web import UPDATE_JS
        response, body = self._request(_mock_webview, "GET", "/common/update.js")
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("text/javascript")
        assert body == UPDATE_JS.read_bytes()

    def test_index_loads_update_js_before_main_js(self, _mock_webview):
        from pathlib import Path
        html = (Path(_mock_webview.FRONTEND_DIR) / "index.html").read_text(encoding="utf-8")
        assert 0 <= html.index('src="common/update.js"') < html.index('src="main.js"')

    def test_status_reports_the_updater(self, _mock_webview, monkeypatch):
        monkeypatch.setattr(_mock_webview, "_updater", _FakeUpdater(supported=False))
        assert self._post(_mock_webview, "/update/status") == (
            200, {"current": "1.0.0", "supported": False, "launch_check": True})

    def test_settings_store_the_launch_check(self, _mock_webview, monkeypatch):
        fake = _FakeUpdater()
        monkeypatch.setattr(_mock_webview, "_updater", fake)
        assert self._post(_mock_webview, "/update/settings", {"launch_check": False}) == (
            200, {"launch_check": False})
        assert fake.saved == [False]

    @pytest.mark.parametrize("body", [{}, {"launch_check": "false"}, {"launch_check": 0}, {"launch_check": None}])
    def test_settings_need_a_boolean(self, _mock_webview, monkeypatch, body):
        fake = _FakeUpdater()
        monkeypatch.setattr(_mock_webview, "_updater", fake)
        status, _ = self._post(_mock_webview, "/update/settings", body)
        assert status == 400
        assert fake.saved == []

    def test_settings_save_failure_is_500_with_the_cause(self, _mock_webview, monkeypatch):
        from analyze_common.update import UpdateError
        fake = _FakeUpdater(save_error=UpdateError("The setting could not be saved: read-only"))
        monkeypatch.setattr(_mock_webview, "_updater", fake)
        assert self._post(_mock_webview, "/update/settings", {"launch_check": False}) == (
            500, {"error": "The setting could not be saved: read-only"})

    def test_launch_check_survives_a_new_updater(self, _mock_webview, monkeypatch, tmp_path):
        from analyze_common.settings import SettingsStore
        from analyze_common.update import Updater
        store = tmp_path / "settings.json"
        monkeypatch.setattr(_mock_webview, "_updater", Updater(_mock_webview.UPDATE_CONFIG, SettingsStore(store)))
        self._post(_mock_webview, "/update/settings", {"launch_check": False})
        monkeypatch.setattr(_mock_webview, "_updater", Updater(_mock_webview.UPDATE_CONFIG, SettingsStore(store)))
        assert self._post(_mock_webview, "/update/status")[1]["launch_check"] is False
        assert json.loads(store.read_text())["update_check_at_launch"] is False

    def test_tests_never_reach_the_real_settings_file(self, _mock_webview, _isolated_settings):
        assert _isolated_settings in _mock_webview._updater.settings.path.parents

    def test_check_up_to_date(self, _mock_webview, monkeypatch):
        monkeypatch.setattr(_mock_webview, "_updater", _FakeUpdater(check=None))
        assert self._post(_mock_webview, "/update/check") == (200, {"available": False})

    def test_check_offers_the_newer_version(self, _mock_webview, monkeypatch):
        monkeypatch.setattr(_mock_webview, "_updater", _FakeUpdater(check="9.9.9"))
        assert self._post(_mock_webview, "/update/check") == (200, {"available": True, "version": "9.9.9"})

    def test_check_failure_is_502_with_the_cause(self, _mock_webview, monkeypatch):
        from analyze_common.update import UpdateError
        monkeypatch.setattr(_mock_webview, "_updater", _FakeUpdater(check=UpdateError("offline")))
        assert self._post(_mock_webview, "/update/check") == (502, {"error": "offline"})

    @pytest.mark.parametrize("body", [{}, {"version": ""}, {"version": 1}])
    def test_install_needs_a_version(self, _mock_webview, monkeypatch, body):
        fake = _FakeUpdater()
        monkeypatch.setattr(_mock_webview, "_updater", fake)
        status, _ = self._post(_mock_webview, "/update/install", body)
        assert status == 400
        assert fake.installed == []

    def test_install_failure_is_500_and_the_app_keeps_running(self, _mock_webview, monkeypatch):
        from analyze_common.update import UpdateError
        monkeypatch.setattr(_mock_webview, "_updater", _FakeUpdater(install=UpdateError("bad signature")))
        exits = []
        monkeypatch.setattr(_mock_webview, "_exit_for_update", exits.append)
        assert self._post(_mock_webview, "/update/install", {"version": "9.9.9"}) == (500, {"error": "bad signature"})
        assert exits == []

    def test_install_hands_off_then_exits(self, _mock_webview, monkeypatch):
        from analyze_common.update import Handoff
        fake = _FakeUpdater(install=Handoff("close"))
        monkeypatch.setattr(_mock_webview, "_updater", fake)
        exits = []
        monkeypatch.setattr(_mock_webview, "_exit_for_update", exits.append)
        assert self._post(_mock_webview, "/update/install", {"version": "9.9.9"}) == (200, {"restarting": True})
        assert fake.installed == ["9.9.9"]
        assert exits == ["close"]

    def test_install_without_restart_keeps_running(self, _mock_webview, monkeypatch):
        from analyze_common.update import Handoff
        monkeypatch.setattr(_mock_webview, "_updater", _FakeUpdater(install=Handoff(None, restart_error="no sh")))
        exits = []
        monkeypatch.setattr(_mock_webview, "_exit_for_update", exits.append)
        status, body = self._post(_mock_webview, "/update/install", {"version": "9.9.9"})
        assert (status, body) == (200, {"installed": True, "restart_error": "no sh"})
        assert exits == []

    def test_install_refuses_simple_content_types(self, _mock_webview, monkeypatch):
        fake = _FakeUpdater()
        monkeypatch.setattr(_mock_webview, "_updater", fake)
        status, _ = self._post(_mock_webview, "/update/install", {"version": "9.9.9"},
                               headers={"Content-Type": "text/plain"})
        assert status == 415
        assert fake.installed == []

    def test_install_refuses_a_foreign_host(self, _mock_webview, monkeypatch):
        fake = _FakeUpdater()
        monkeypatch.setattr(_mock_webview, "_updater", fake)
        status, _ = self._post(_mock_webview, "/update/install", {"version": "9.9.9"},
                               headers={"Host": "attacker.example"})
        assert status == 403
        assert fake.installed == []

    def test_close_exit_closes_the_window(self, _mock_webview, monkeypatch):
        window = MagicMock()
        monkeypatch.setattr(_mock_webview, "_window", window)
        monkeypatch.setattr(_mock_webview.os, "_exit", lambda code: pytest.fail("os._exit called"))
        _mock_webview._exit_for_update("close")
        window.destroy.assert_called_once_with()

    def test_immediate_exit_removes_temp_dirs_then_exits(self, _mock_webview, monkeypatch, tmp_path):
        upload, cache = tmp_path / "up", tmp_path / "cache"
        upload.mkdir()
        cache.mkdir()
        (cache / "cache_0001.json").write_text("{}")
        monkeypatch.setattr(_mock_webview, "_upload_dir", str(upload))
        monkeypatch.setattr(_mock_webview, "_cache_dir", str(cache))
        window = MagicMock()
        monkeypatch.setattr(_mock_webview, "_window", window)
        codes = []
        monkeypatch.setattr(_mock_webview.os, "_exit", codes.append)
        lock_file = _mock_webview._instance_lock.path
        _mock_webview._exit_for_update("immediate")
        assert codes == [0]
        assert not upload.exists() and not cache.exists()
        assert not os.path.exists(lock_file)
        window.destroy.assert_not_called()

    def test_main_holds_the_instance_mutex(self, _mock_webview, monkeypatch):
        held = []
        monkeypatch.setattr(_mock_webview, "hold_instance_mutex", held.append)
        _mock_webview.main()
        assert held == [_mock_webview.UPDATE_CONFIG.mutex_name]


    def test_frozen_main_puts_the_bundled_programs_first_on_path(self, _mock_webview, monkeypatch, tmp_path):
        monkeypatch.setattr(_mock_webview, "hold_instance_mutex", lambda name: None)
        monkeypatch.setattr(_mock_webview.sys, "frozen", True, raising=False)
        monkeypatch.setattr(_mock_webview.sys, "_MEIPASS", str(tmp_path), raising=False)
        monkeypatch.setenv("PATH", "existing")
        _mock_webview.main()
        assert os.environ["PATH"] == str(tmp_path / "bin") + os.pathsep + "existing"

    def test_running_the_module_as_a_script_starts_the_app(self, _mock_webview, monkeypatch):
        import runpy
        import warnings
        from analyze_common import update
        monkeypatch.setattr(update, "hold_instance_mutex", lambda name: None)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("analyze_spectrum.gui", run_name="__main__")
        _mock_webview.webview.create_window.assert_called_once()
        assert _mock_webview.webview.create_window.call_args.args[0] == "Spectrum Analyzer"
        _mock_webview.webview.start.assert_called_once()


class TestUiSettingsEndpoints:
    _request = TestUpdateEndpoints._request
    _post = TestUpdateEndpoints._post

    @staticmethod
    def _stored(gui):
        return json.loads(gui._settings.path.read_text(encoding="utf-8"))

    def test_settings_js_carries_the_stored_values(self, _mock_webview):
        _mock_webview._ui_settings.update({"theme": "dark"})
        response, body = self._request(_mock_webview, "GET", "/common/settings.js")
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("text/javascript")
        assert response.getheader("Cache-Control") == "no-store"
        assert body == _mock_webview._ui_settings.script()
        assert body.startswith(b'window.analyzeSettingsStored = {"theme": "dark", "lang": null};\n')

    def test_settings_js_reads_the_file_for_every_page_load(self, _mock_webview):
        _, before = self._request(_mock_webview, "GET", "/common/settings.js")
        self._post(_mock_webview, "/settings", {"lang": "ja"})
        _, after = self._request(_mock_webview, "GET", "/common/settings.js")
        assert b'"lang": null' in before
        assert b'"lang": "ja"' in after

    def test_index_loads_settings_js_before_i18n_js(self, _mock_webview):
        from pathlib import Path
        html = (Path(_mock_webview.FRONTEND_DIR) / "index.html").read_text(encoding="utf-8")
        assert 0 <= html.index('src="common/settings.js"') < html.index('src="i18n.js"')

    def test_post_stores_one_setting_at_a_time(self, _mock_webview):
        assert self._post(_mock_webview, "/settings", {"theme": "light"}) == (
            200, {"theme": "light", "lang": None})
        assert self._post(_mock_webview, "/settings", {"lang": "ja"}) == (
            200, {"theme": "light", "lang": "ja"})
        assert self._stored(_mock_webview) == {"theme": "light", "lang": "ja"}

    @pytest.mark.parametrize("body", [{}, {"theme": "sepia"}, {"lang": "fr"}, {"theme": None},
                                      {"theme": "dark", "lang": "ja"},
                                      {"update_check_at_launch": False}, [], "dark"])
    def test_post_rejects_anything_else_without_writing(self, _mock_webview, body):
        _mock_webview._ui_settings.update({"theme": "dark"})
        before = _mock_webview._settings.path.read_bytes()
        response, data = self._request(_mock_webview, "POST", "/settings", json.dumps(body).encode())
        assert response.status == 400
        assert "error" in json.loads(data)
        assert _mock_webview._settings.path.read_bytes() == before

    def test_post_save_failure_is_500_with_the_cause(self, _mock_webview, monkeypatch):
        def fail(key, value):
            raise OSError("read-only")
        monkeypatch.setattr(_mock_webview._settings, "set", fail)
        assert self._post(_mock_webview, "/settings", {"theme": "dark"}) == (500, {"error": "read-only"})

    def test_post_refuses_a_foreign_host(self, _mock_webview):
        status, _ = self._post(_mock_webview, "/settings", {"theme": "dark"},
                               headers={"Host": "attacker.example"})
        assert status == 403
        assert not _mock_webview._settings.path.exists()

    def test_update_and_ui_settings_share_the_file_and_its_lock(self, _mock_webview):
        assert _mock_webview._updater.settings is _mock_webview._settings
        assert _mock_webview._ui_settings.settings is _mock_webview._settings
        self._post(_mock_webview, "/update/settings", {"launch_check": False})
        self._post(_mock_webview, "/settings", {"theme": "dark"})
        assert self._stored(_mock_webview) == {"update_check_at_launch": False, "theme": "dark"}

    @pytest.mark.parametrize("theme, dark_os, color", [
        ("dark", False, "#1a1a2e"), ("light", True, "#fafafa"),
        (None, True, "#1a1a2e"), (None, False, "#fafafa"),
    ])
    def test_window_starts_in_the_stored_theme(self, _mock_webview, monkeypatch, theme, dark_os, color):
        from analyze_common import ui_settings
        monkeypatch.setattr(ui_settings, "is_dark_mode", lambda: dark_os)
        monkeypatch.setattr(_mock_webview, "hold_instance_mutex", lambda name: None)
        if theme is not None:
            _mock_webview._ui_settings.update({"theme": theme})
        _mock_webview.main()
        assert _mock_webview.webview.create_window.call_args.kwargs["background_color"] == color

    def test_window_keeps_its_color_until_the_page_paints(self, _mock_webview, monkeypatch):
        shown = []
        monkeypatch.setattr(_mock_webview, "hold_instance_mutex", lambda name: None)
        monkeypatch.setattr(_mock_webview, "show_window_color_until_paint", shown.append)
        _mock_webview.main()
        assert shown == [_mock_webview.webview.create_window.return_value]

    def test_quit_runs_the_atexit_cleanup(self, _mock_webview, monkeypatch):
        watch = MagicMock()
        monkeypatch.setattr(_mock_webview, "hold_instance_mutex", lambda name: None)
        monkeypatch.setattr(_mock_webview, "run_atexit_on_app_quit", watch)
        _mock_webview.main()
        watch.assert_called_once_with()


class _Routes:
    """Requests to the app's handler over a real socket, with the sources and dialogs the tests control."""

    _request = TestUpdateEndpoints._request

    def _call(self, gui, path, body=b"", headers=None):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        response, data = self._request(gui, "POST", path, raw, headers)
        return response.status, data

    def _json(self, gui, path, body=b"", headers=None):
        status, data = self._call(gui, path, body, headers)
        return status, json.loads(data)

    @staticmethod
    def _window(gui, monkeypatch, result=None):
        window = MagicMock()
        window.create_file_dialog.return_value = result
        monkeypatch.setattr(gui, "_window", window)
        return window


class TestRequestValidation(_Routes):
    @pytest.fixture(autouse=True)
    def _no_sources(self, _mock_webview, monkeypatch):
        self.resolve = MagicMock()
        monkeypatch.setattr(_mock_webview, "resolve_source", self.resolve)

    def test_unknown_path_is_404(self, _mock_webview):
        assert self._call(_mock_webview, "/nope", {})[0] == 404

    @pytest.mark.parametrize("body, message", [
        (b"{not json", "Invalid JSON body"),
        ({"url": "   "}, "Missing or invalid 'url' field"),
        ({"url": 5}, "Missing or invalid 'url' field"),
        ({"url": "file:///etc/hosts"}, "'url' must use http or https scheme"),
        ({"url": "javascript:alert(1)"}, "'url' must use http or https scheme"),
        ({"url": "a.wav", "duration": True}, "'duration' must be a number, not bool"),
        ({"url": "a.wav", "duration": 0.001}, "'duration' must be >= 0.01 minutes"),
        ({"url": "a.wav", "duration": 241}, "'duration' must be <= 240 minutes"),
    ])
    def test_analyze_rejects_the_request_before_any_work(self, _mock_webview, body, message):
        assert self._json(_mock_webview, "/analyze", body) == (400, {"error": message})
        self.resolve.assert_not_called()

    @pytest.mark.parametrize("body, message", [
        (b"{not json", "Invalid JSON body"),
        ({"sources": ["a.wav", 5]}, "All sources must be non-empty strings"),
        ({"sources": ["a.wav", "  "]}, "All sources must be non-empty strings"),
        ({"sources": ["a.wav", "ftp://host/b.wav"]}, "'url' must use http or https scheme"),
        ({"sources": ["a.wav", "b.wav"], "duration": "x"}, "'duration' must be a number"),
        ({"sources": ["a.wav", "b.wav"], "duration": 240.001}, "'duration' must be <= 240 minutes"),
    ])
    def test_compare_rejects_the_request_before_any_work(self, _mock_webview, body, message):
        assert self._json(_mock_webview, "/compare", body) == (400, {"error": message})
        self.resolve.assert_not_called()

    def test_url_source_reports_the_download_stage(self, _mock_webview, monkeypatch):
        self.resolve.side_effect = FileNotFoundError("stop here")
        status, data = self._call(_mock_webview, "/analyze", {"url": "https://example.com/a"})
        events = [json.loads(line) for line in data.decode().splitlines()]
        assert status == 200
        assert events == [
            {"type": "progress", "stage": "download", "message": "Downloading audio..."},
            {"type": "error", "error": "stop here"},
        ]
        self.resolve.assert_called_once()

    def test_compare_of_cached_tracks_analyzes_nothing(self, _mock_webview):
        gui_mod = _mock_webview
        spectrum = {"freqs": [100, 200], "psd_db": [-20, -30]}
        for name in ("a", "b"):
            gui_mod._cache_put(f"https://example.com/{name}", None,
                               {"label": name, "spectrum": spectrum, "meta": {"source": name}})
        body = {"sources": ["https://example.com/a", "https://example.com/b"]}
        status, data = self._call(gui_mod, "/compare", body)
        events = [json.loads(line) for line in data.decode().splitlines()]
        assert status == 200
        assert [e.get("stage") for e in events if e["type"] == "progress"] == ["cache", "cache", "compare"]
        assert [t["label"] for t in events[-1]["data"]["tracks"]] == ["a", "b"]
        assert events[-1]["data"]["transfer_functions"][0]["label"] == "b \u2212 a"
        self.resolve.assert_not_called()


class TestUnexpectedFailure(_Routes):
    def test_error_in_a_route_is_500_without_its_details(self, _mock_webview, monkeypatch):
        def explode(self):
            raise RuntimeError("secret detail")

        monkeypatch.setattr(_mock_webview.AnalyzeHandler, "_handle_load", explode)
        status, data = self._call(_mock_webview, "/load", {})
        assert status == 500
        assert json.loads(data) == {"error": "Internal server error"}
        assert b"secret detail" not in data

    def test_server_survives_a_route_whose_error_cannot_be_reported(self, _mock_webview, monkeypatch):
        import http.client
        reported = []

        def explode(self):
            raise RuntimeError("first")

        def cannot_report(self, status, message):
            reported.append((status, message))
            raise BrokenPipeError()

        monkeypatch.setattr(_mock_webview.AnalyzeHandler, "_handle_load", explode)
        monkeypatch.setattr(_mock_webview.AnalyzeHandler, "_json_error", cannot_report)
        with pytest.raises(http.client.RemoteDisconnected):
            self._call(_mock_webview, "/load", {})
        assert reported == [(500, "Internal server error")]


class TestSaveRoute(_Routes):
    def test_invalid_json_body(self, _mock_webview, monkeypatch):
        window = self._window(_mock_webview, monkeypatch)
        assert self._json(_mock_webview, "/save", b"{not json") == (400, {"error": "Invalid JSON body"})
        window.create_file_dialog.assert_not_called()

    def test_open_dialog_is_refused_with_409(self, _mock_webview, monkeypatch):
        window = self._window(_mock_webview, monkeypatch)
        with _mock_webview._dialog_lock:
            status, body = self._json(_mock_webview, "/save", {"data": {"x": 1}})
        assert (status, body) == (409, {"error": "A dialog is already open"})
        window.create_file_dialog.assert_not_called()

    def test_dialog_failure_is_500_and_frees_the_dialog(self, _mock_webview, monkeypatch):
        window = self._window(_mock_webview, monkeypatch)
        window.create_file_dialog.side_effect = RuntimeError("boom")
        assert self._json(_mock_webview, "/save", {"data": {"x": 1}}) == (500, {"error": "File dialog error: boom"})
        assert _mock_webview._dialog_lock.acquire(blocking=False)
        _mock_webview._dialog_lock.release()

    def test_unwritable_path_is_500(self, _mock_webview, monkeypatch, tmp_path):
        target = tmp_path / "missing_folder" / "result.json"
        self._window(_mock_webview, monkeypatch, str(target))
        status, body = self._json(_mock_webview, "/save", {"data": {"x": 1}})
        assert status == 500
        assert body["error"].startswith("Failed to write file: ")
        assert not target.exists()


class TestLoadRoute(_Routes):
    def test_dialog_failure_is_500_and_frees_the_dialog(self, _mock_webview, monkeypatch):
        window = self._window(_mock_webview, monkeypatch)
        window.create_file_dialog.side_effect = RuntimeError("boom")
        assert self._json(_mock_webview, "/load", {}) == (500, {"error": "File dialog error: boom"})
        assert _mock_webview._dialog_lock.acquire(blocking=False)
        _mock_webview._dialog_lock.release()

    def test_chosen_folder_is_refused(self, _mock_webview, monkeypatch, tmp_path):
        self._window(_mock_webview, monkeypatch, [str(tmp_path)])
        assert self._json(_mock_webview, "/load", {}) == (400, {"error": f"Not a file: {tmp_path.name}"})

    def test_oversize_file_is_refused_without_reading_it(self, _mock_webview, monkeypatch, tmp_path):
        big = tmp_path / "big.json"
        limit = _mock_webview.AnalyzeHandler._MAX_LOAD_BYTES
        big.write_text(json.dumps({"spectrum": {}, "pad": "x" * limit}), encoding="utf-8")
        self._window(_mock_webview, monkeypatch, [str(big)])
        status, body = self._json(_mock_webview, "/load", {})
        assert (status, body) == (400, {"error": "JSON file exceeds 10 MB: big.json"})

    def test_file_whose_size_cannot_be_read_is_refused(self, _mock_webview, monkeypatch, tmp_path):
        target = tmp_path / "gone.json"
        target.write_text("{}", encoding="utf-8")
        self._window(_mock_webview, monkeypatch, [str(target)])

        def deny(path):
            raise OSError("denied")

        monkeypatch.setattr(_mock_webview.os.path, "getsize", deny)
        assert self._json(_mock_webview, "/load", {}) == (400, {"error": "Failed to read file: denied"})

    def test_file_that_is_not_json_is_refused(self, _mock_webview, monkeypatch, tmp_path):
        target = tmp_path / "broken.json"
        target.write_text("{broken", encoding="utf-8")
        self._window(_mock_webview, monkeypatch, [str(target)])
        status, body = self._json(_mock_webview, "/load", {})
        assert status == 400
        assert body["error"].startswith("Failed to read file: ")

    @pytest.mark.parametrize("meta, source", [
        (None, ""),
        ({"source": 5}, ""),
        ({"source": ""}, ""),
        ({"source": "/nonexistent/clip.wav"}, "/nonexistent/clip.wav"),
        ({"source": "https://example.com/clip"}, "https://example.com/clip"),
    ])
    def test_outdated_result_reports_its_source_and_is_not_cached(self, _mock_webview, monkeypatch, tmp_path, meta, source):
        gui_mod = _mock_webview
        target = tmp_path / "old.json"
        target.write_text(json.dumps({"spectrum": {"freqs": [1], "psd_db": [0]}, "meta": meta}), encoding="utf-8")
        self._window(gui_mod, monkeypatch, [str(target)])
        status, body = self._json(gui_mod, "/load", {})
        assert status == 200
        assert body["schema_outdated"] is True
        assert body["source"] == source
        assert body["source_available"] is source.startswith("https://")
        assert not gui_mod._loaded_cache_data


class TestCacheLoaded:
    @pytest.mark.parametrize("data", [
        {"meta": {"source": "https://example.com/a"}},
        {"spectrum": {}},
        {"spectrum": {}, "meta": None},
        {"spectrum": {}, "meta": {"source": 5}},
        {"spectrum": {}, "meta": {"source": ""}},
        {"spectrum": {}, "meta": {"source": "https://example.com/a", "duration_min": 2}},
    ])
    def test_result_without_a_usable_source_or_with_a_cut_is_not_kept(self, _mock_webview, data):
        gui_mod = _mock_webview
        gui_mod._loaded_cache_data.clear()
        gui_mod.AnalyzeHandler._cache_loaded(data)
        assert not gui_mod._loaded_cache_data

    def test_whole_source_result_is_kept_under_its_source(self, _mock_webview):
        gui_mod = _mock_webview
        gui_mod._loaded_cache_data.clear()
        data = {"spectrum": {}, "meta": {"source": "https://example.com/a"}}
        gui_mod.AnalyzeHandler._cache_loaded(data)
        assert gui_mod._cache_get("https://example.com/a", None) is data
        gui_mod._loaded_cache_data.clear()


class TestUploadRoute(_Routes):
    _OCTET = {"Content-Type": "application/octet-stream"}

    def _upload(self, gui, name, payload=b"\x00" * 32):
        from urllib.parse import quote
        return self._json(gui, "/upload", payload, {**self._OCTET, "X-Filename": quote(name)})

    def test_invalid_content_length(self, _mock_webview):
        status, body = self._json(_mock_webview, "/upload", b"", {**self._OCTET, "Content-Length": "abc"})
        assert (status, body) == (400, {"error": "Invalid Content-Length"})

    def test_file_over_the_limit_is_413_before_any_data_is_read(self, _mock_webview):
        too_big = str(_mock_webview.AnalyzeHandler._MAX_UPLOAD + 1)
        status, body = self._json(_mock_webview, "/upload", b"", {**self._OCTET, "Content-Length": too_big})
        assert (status, body) == (413, {"error": "File too large (max 500 MB)"})

    def test_upper_case_extension_gets_the_lower_case_one_appended(self, _mock_webview):
        status, body = self._upload(_mock_webview, "TRACK.WAV", b"abc")
        assert status == 200
        assert os.path.basename(body["path"]) == "TRACK.WAV.wav"
        assert os.path.dirname(body["path"]) == _mock_webview._upload_dir
        with open(body["path"], "rb") as f:
            assert f.read() == b"abc"

    def test_same_name_uploaded_again_gets_a_number(self, _mock_webview):
        paths = [self._upload(_mock_webview, "dup.wav", bytes([i]))[1]["path"] for i in range(3)]
        assert [os.path.basename(p) for p in paths] == ["dup.wav", "dup_1.wav", "dup_2.wav"]
        for i, path in enumerate(paths):
            with open(path, "rb") as f:
                assert f.read() == bytes([i])

    def test_name_that_leaves_the_upload_folder_is_refused(self, _mock_webview, monkeypatch, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        monkeypatch.setattr(_mock_webview, "_upload_dir", str(uploads))
        monkeypatch.setattr(_mock_webview, "sanitize_filename", lambda name: "../escape.wav")
        status, body = self._upload(_mock_webview, "x.wav")
        assert (status, body) == (400, {"error": "Invalid filename"})
        assert not (tmp_path / "escape.wav").exists()
        assert list(uploads.iterdir()) == []

    @pytest.mark.parametrize("unlink_fails", [False, True], ids=["removed", "removal_fails"])
    def test_failed_write_leaves_no_partial_file(self, _mock_webview, monkeypatch, unlink_fails):
        gui_mod = _mock_webview
        real_open, real_unlink = open, os.unlink

        def failing_open(path, mode="r", *args, **kwargs):
            f = real_open(path, mode, *args, **kwargs)
            f.write(b"partial")
            f.close()
            raise OSError("disk full")

        def unlink(path, *args, **kwargs):
            if unlink_fails and str(path).startswith(gui_mod._upload_dir):
                raise OSError("locked")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(gui_mod, "open", failing_open, raising=False)
        monkeypatch.setattr(gui_mod.os, "unlink", unlink)
        status, body = self._upload(gui_mod, "fail_write.wav")
        assert (status, body) == (400, {"error": "Invalid filename"})
        assert os.path.exists(os.path.join(gui_mod._upload_dir, "fail_write.wav")) is unlink_fails

    def test_write_refused_before_a_file_exists_leaves_nothing(self, _mock_webview, monkeypatch):
        def refuse(path, *args, **kwargs):
            raise ValueError("embedded null byte")

        monkeypatch.setattr(_mock_webview, "open", refuse, raising=False)
        assert self._upload(_mock_webview, "refused.wav") == (400, {"error": "Invalid filename"})
        assert not os.path.exists(os.path.join(_mock_webview._upload_dir, "refused.wav"))

    @pytest.mark.parametrize("unlink_fails", [False, True], ids=["removed", "removal_fails"])
    def test_cut_off_upload_is_refused_and_removed(self, _mock_webview, monkeypatch, unlink_fails):
        import socket
        from http.server import HTTPServer
        gui_mod = _mock_webview
        real_unlink = os.unlink

        def unlink(path, *args, **kwargs):
            if unlink_fails and str(path).startswith(gui_mod._upload_dir):
                raise OSError("locked")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(gui_mod.os, "unlink", unlink)
        server = HTTPServer(("127.0.0.1", 0), gui_mod.AnalyzeHandler)
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        try:
            with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=10) as sock:
                sock.sendall(b"POST /upload HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                             b"Content-Type: application/octet-stream\r\nX-Filename: cut.wav\r\n"
                             b"Content-Length: 100\r\n\r\n" + b"0123456789")
                sock.shutdown(socket.SHUT_WR)
                reply = b""
                while chunk := sock.recv(65536):
                    reply += chunk
        finally:
            thread.join(timeout=5)
            server.server_close()
        assert reply.startswith(b"HTTP/1.0 400")
        assert json.loads(reply.split(b"\r\n\r\n", 1)[1]) == {"error": "Incomplete upload"}
        assert os.path.exists(os.path.join(gui_mod._upload_dir, "cut.wav")) is unlink_fails


class TestUpdateConfig:
    def test_public_key_is_a_raw_ed25519_key(self):
        import base64
        from analyze_spectrum.update import PUBLIC_KEY
        assert len(base64.b64decode(PUBLIC_KEY, validate=True)) == 32

    def test_config_names_this_app(self):
        from analyze_spectrum import __version__
        from analyze_spectrum.update import UPDATE_CONFIG
        assert UPDATE_CONFIG.product == "analyze-spectrum"
        assert UPDATE_CONFIG.repo == "semnil/analyze-spectrum"
        assert UPDATE_CONFIG.current_version == __version__

    @staticmethod
    def _load_build():
        import importlib.util
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location("_build", root / "build.py")
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        return build

    def test_bundle_carries_the_shared_web_files_and_modules(self):
        from pathlib import Path
        from analyze_common.server import GuiHandler
        from analyze_common.web import SETTINGS_JS
        spec = (Path(__file__).resolve().parent.parent / "analyze-spectrum.spec").read_text(encoding="utf-8")
        for path in [SETTINGS_JS] + [path for path, _ in GuiHandler._SHARED_ASSETS.values()]:
            assert f"vendor/py-analyze-common/src/analyze_common/web/{path.name}" in spec
        for module in ("analyze_common.server", "analyze_common.window"):
            assert f'"{module}"' in spec

    def test_build_py_passes_the_config_mutex_to_the_installer(self):
        from analyze_common import build
        from analyze_spectrum.update import UPDATE_CONFIG
        assert build._read_mutex_name(self._load_build().APP) == UPDATE_CONFIG.mutex_name


_RUNNING_INSTANCE = """
import json, os, sys, time
from unittest.mock import MagicMock
sys.modules["webview"] = MagicMock()
from analyze_spectrum import gui
then = time.time() - 3601
for path in (gui._instance_lock.path, gui._cache_dir, gui._upload_dir):
    os.utime(path, (then, then))
print(json.dumps([gui._cache_dir, gui._upload_dir]), flush=True)
sys.stdin.readline()
"""


class TestOrphanSweep:
    def test_the_end_of_the_app_leaves_a_running_instance_alone(self, _mock_webview, tmp_path, monkeypatch):
        import subprocess
        import sys
        import tempfile
        import time
        gui_mod = _mock_webview
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        own = tmp_path / "spectrum_cache_own"
        own.mkdir()
        os.utime(own, (time.time() - 3601, time.time() - 3601))
        monkeypatch.setattr(gui_mod, "_cache_dir", str(own))
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path),
               "TMPDIR": str(tmp_path), "TEMP": str(tmp_path), "TMP": str(tmp_path)}
        other = subprocess.Popen([sys.executable, "-c", _RUNNING_INSTANCE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
        try:
            folders = json.loads(other.stdout.readline())
            gui_mod._cleanup_orphan_tempdirs()
            assert all(os.path.isdir(path) for path in folders)
        finally:
            other.kill()
            other.wait()
            other.stdin.close()
            other.stdout.close()
        deadline = time.monotonic() + 15
        while any(os.path.isdir(path) for path in folders) and time.monotonic() < deadline:
            gui_mod._cleanup_orphan_tempdirs()
            time.sleep(0.1)
        assert not any(os.path.isdir(path) for path in folders)
        assert own.is_dir()

    def test_a_normal_end_leaves_nothing_in_the_temp_folder(self, tmp_path):
        import subprocess
        import sys
        code = ("import sys; from unittest.mock import MagicMock; sys.modules['webview'] = MagicMock(); "
                "from analyze_spectrum import gui; print(gui._instance_lock.path)")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path),
               "TMPDIR": str(tmp_path), "TEMP": str(tmp_path), "TMP": str(tmp_path)}
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
        assert os.path.basename(done.stdout.strip()).startswith("spectrum_instance_")
        assert list(tmp_path.iterdir()) == []
