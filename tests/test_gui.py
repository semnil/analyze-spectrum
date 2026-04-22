"""Tests for analyze_spectrum.gui module."""

import importlib
import json
import os
from unittest.mock import patch, MagicMock

import pytest


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
