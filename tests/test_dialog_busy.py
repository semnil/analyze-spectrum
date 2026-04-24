"""Tests for dialog busy rejection (non-blocking _dialog_lock)."""

import json
import sys
import threading
from http.server import HTTPServer
from unittest.mock import MagicMock

import pytest

if "webview" not in sys.modules:
    sys.modules["webview"] = MagicMock()

import analyze_spectrum.gui as _gui_mod  # noqa: E402


@pytest.fixture()
def _server():
    """Create a test HTTP server per test."""
    srv = HTTPServer(("127.0.0.1", 0), _gui_mod.AnalyzeHandler)
    yield srv
    srv.server_close()


@pytest.fixture()
def _mock_window():
    """Set up a mock pywebview window and restore after test."""
    old = _gui_mod._window
    _gui_mod._window = MagicMock()
    yield _gui_mod._window
    _gui_mod._window = old


def _post_sync(server, path, body=None):
    """Send a POST request to the test server and return (status, body_dict)."""
    import http.client
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port)
    payload = json.dumps(body).encode() if body else b""
    headers = {"Content-Type": "application/json",
               "Content-Length": str(len(payload))}
    conn.request("POST", path, body=payload, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()
    try:
        return resp.status, json.loads(data)
    except json.JSONDecodeError:
        return resp.status, data


def _serve_post(server, path, body=None):
    """Handle one request in a thread and return (status, body_dict)."""
    t = threading.Thread(target=server.handle_request)
    t.start()
    result = _post_sync(server, path, body)
    t.join(timeout=5)
    return result


class TestDialogBusyRejection:
    """Concurrent dialog requests should be rejected with 409."""

    def test_load_rejected_while_dialog_open(self, _server, _mock_window):
        """A second /load while the first dialog is still open returns 409."""
        dialog_entered = threading.Event()
        dialog_release = threading.Event()

        def blocking_dialog(*args, **kwargs):
            dialog_entered.set()
            dialog_release.wait(timeout=5)
            return None

        _mock_window.create_file_dialog.side_effect = blocking_dialog

        first_result = {}

        def first_load():
            first_result.update(dict(zip(
                ("status", "body"),
                _serve_post(_server, "/load", {}),
            )))

        t1 = threading.Thread(target=first_load)
        t1.start()
        dialog_entered.wait(timeout=5)

        status2, body2 = _serve_post(_server, "/load", {})
        assert status2 == 409
        assert "dialog" in body2["error"].lower()

        dialog_release.set()
        t1.join(timeout=5)
        assert first_result["status"] == 200

    def test_browse_rejected_while_dialog_open(self, _server, _mock_window):
        """A /browse while a /load dialog is open returns 409."""
        dialog_entered = threading.Event()
        dialog_release = threading.Event()

        def blocking_dialog(*args, **kwargs):
            dialog_entered.set()
            dialog_release.wait(timeout=5)
            return None

        _mock_window.create_file_dialog.side_effect = blocking_dialog

        def first_load():
            _serve_post(_server, "/load", {})

        t1 = threading.Thread(target=first_load)
        t1.start()
        dialog_entered.wait(timeout=5)

        status2, body2 = _serve_post(_server, "/browse", {})
        assert status2 == 409
        assert "dialog" in body2["error"].lower()

        dialog_release.set()
        t1.join(timeout=5)

    def test_load_multi_file_still_works(self, _server, _mock_window, tmp_path):
        """Multi-file load still works correctly after the try-lock change."""
        data_a = {
            "meta": {"source": "a.wav", "schema_version": _gui_mod._SCHEMA_VERSION},
            "spectrum": {"freqs": [100], "psd_db": [-20]},
        }
        data_b = {
            "meta": {"source": "b.wav", "schema_version": _gui_mod._SCHEMA_VERSION},
            "spectrum": {"freqs": [100], "psd_db": [-25]},
        }
        file_a = tmp_path / "a.json"
        file_b = tmp_path / "b.json"
        file_a.write_text(json.dumps(data_a))
        file_b.write_text(json.dumps(data_b))

        _mock_window.create_file_dialog.return_value = [str(file_a), str(file_b)]

        status, body = _serve_post(_server, "/load", {})
        assert status == 200
        assert body["loaded"] is True
        assert body["type"] == "multi"
        assert len(body["items"]) == 2
