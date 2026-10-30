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
        _mock_webview._exit_for_update("immediate")
        assert codes == [0]
        assert not upload.exists() and not cache.exists()
        window.destroy.assert_not_called()

    def test_main_holds_the_instance_mutex(self, _mock_webview, monkeypatch):
        held = []
        monkeypatch.setattr(_mock_webview, "hold_instance_mutex", held.append)
        _mock_webview.main()
        assert held == [_mock_webview.UPDATE_CONFIG.mutex_name]


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

    def test_build_py_passes_the_config_mutex_to_the_installer(self):
        from analyze_common import build
        from analyze_spectrum.update import UPDATE_CONFIG
        assert build._read_mutex_name(self._load_build().APP) == UPDATE_CONFIG.mutex_name
