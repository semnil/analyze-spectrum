"""GUI application: pywebview window + local HTTP server for spectral analysis."""

import atexit
import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import numpy as np
import webview

from analyze_spectrum import __version__
from analyze_spectrum.analysis import analyze_track
from analyze_spectrum.download import compute_middle, is_url, resolve_source, sanitize_filename
from analyze_spectrum.pcm import extract_audio, probe_info

# Schema version: increment when the analysis result JSON structure changes
# in a way that requires re-analysis (new metrics, changed field semantics).
_SCHEMA_VERSION = 1

# Temporary directory for uploaded (drag & drop) files, cleaned up on exit
_upload_dir = tempfile.mkdtemp(prefix="spectrum_uploads_")
atexit.register(shutil.rmtree, _upload_dir, True)

# Analysis result cache — avoids re-analysis for same source + duration
_cache_dir = tempfile.mkdtemp(prefix="spectrum_cache_")
atexit.register(shutil.rmtree, _cache_dir, True)
_result_cache: dict[tuple, str] = {}  # (source, duration, [mtime]) -> json path
_result_cache_data: dict[tuple, dict] = {}  # in-memory cache to avoid disk re-reads


def _cache_key(source: str, duration: float | None) -> tuple:
    parts: list = [source, duration]
    if not is_url(source):
        try:
            parts.append(os.path.getmtime(source))
        except OSError:
            pass
    return tuple(parts)


def _cache_get(source: str, duration: float | None) -> dict | None:
    key = _cache_key(source, duration)
    data = _result_cache_data.get(key)
    if data is not None:
        return data
    path = _result_cache.get(key)
    if path and os.path.exists(path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        _result_cache_data[key] = data
        return data
    return None


_cache_seq = 0


def _cache_put(source: str, duration: float | None, result_dict: dict) -> str:
    global _cache_seq
    key = _cache_key(source, duration)
    _cache_seq += 1
    fname = f"cache_{_cache_seq:04d}.json"
    path = os.path.join(_cache_dir, fname)
    Path(path).write_text(
        json.dumps(result_dict, ensure_ascii=False), encoding="utf-8",
    )
    _result_cache[key] = path
    _result_cache_data[key] = result_dict
    return path


def _make_meta(source: str) -> dict:
    return {
        "schema_version": _SCHEMA_VERSION,
        "version": __version__,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }


def _cache_file(source: str, duration: float | None) -> str | None:
    key = _cache_key(source, duration)
    path = _result_cache.get(key)
    return path if path and os.path.exists(path) else None


def _transfer_functions_from_dicts(track_dicts: list[dict]) -> list[dict]:
    """Compute transfer functions from serialized track dicts."""
    if len(track_dicts) < 2:
        return []
    ref = track_dicts[0]
    ref_freqs = np.array(ref["spectrum"]["freqs"])
    ref_psd = np.array(ref["spectrum"]["psd_db"])
    tfs = []
    for other in track_dicts[1:]:
        o_freqs = np.array(other["spectrum"]["freqs"])
        o_psd = np.array(other["spectrum"]["psd_db"])
        if len(o_freqs) == len(ref_freqs):
            delta = o_psd - ref_psd
        else:
            delta = np.interp(ref_freqs, o_freqs, o_psd) - ref_psd
        tfs.append({
            "label": f"{other['label']} \u2212 {ref['label']}",
            "freqs": ref_freqs.tolist(),
            "delta_db": np.round(delta, 2).tolist(),
        })
    return tfs


def _get_base_dir() -> Path:
    """Return the base directory for bundled resources."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


FRONTEND_DIR = _get_base_dir() / "frontend"

_window = None


class _ClientDisconnected(Exception):
    """Raised when the client aborts the NDJSON stream."""


class AnalyzeHandler(SimpleHTTPRequestHandler):
    """Serves frontend files and handles analysis POST requests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    _MAX_BODY = 10 * 1024 * 1024  # 10 MB
    _MAX_IMAGE_BODY = 50 * 1024 * 1024  # 50 MB (base64 PNG can be large)

    def _read_json_body(self, max_size: int | None = None) -> dict | None:
        """Read and parse JSON body. Returns None on parse failure."""
        limit = max_size or self._MAX_BODY
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        if length > limit:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _dialog_path(result) -> str | None:
        """Extract file path from pywebview dialog result."""
        if not result:
            return None
        return result if isinstance(result, str) else result[0]

    def do_POST(self):
        handlers = {
            "/analyze": self._handle_analyze,
            "/compare": self._handle_compare,
            "/save": self._handle_save,
            "/save-image": self._handle_save_image,
            "/load": self._handle_load,
            "/browse": self._handle_browse,
            "/upload": self._handle_upload,
        }
        handler = handlers.get(self.path)
        if handler:
            handler()
        else:
            self.send_error(404)

    def _parse_duration(self, body: dict) -> float | None | str:
        """Parse and validate duration from request body.

        Returns float (valid), None (not specified), or str (error message).
        """
        duration = body.get("duration")
        if duration is None:
            return None
        try:
            duration = float(duration)
            if duration <= 0:
                return "'duration' must be a positive number"
            return duration
        except (ValueError, TypeError):
            return "'duration' must be a number"

    def _start_ndjson(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

    def _run_ndjson(self, fn, *args):
        """Start NDJSON stream and run fn, handling disconnects and errors."""
        self._start_ndjson()
        try:
            fn(*args)
        except _ClientDisconnected:
            return
        except FileNotFoundError as e:
            try:
                self._send_event("error", error=str(e))
            except _ClientDisconnected:
                return
        except Exception as e:
            try:
                self._send_event("error", error=f"Analysis failed: {e}")
            except _ClientDisconnected:
                return

    def _handle_analyze(self):
        body = self._read_json_body()
        if body is None:
            self._json_error(400, "Invalid JSON body")
            return
        source = body.get("url", "")

        if not source or not isinstance(source, str):
            self._json_error(400, "Missing or invalid 'url' field")
            return

        duration = self._parse_duration(body)
        if isinstance(duration, str):
            self._json_error(400, duration)
            return

        self._run_ndjson(self._run_single, source, duration)

    def _handle_compare(self):
        body = self._read_json_body()
        if body is None:
            self._json_error(400, "Invalid JSON body")
            return
        sources = body.get("sources", [])

        if not sources or not isinstance(sources, list) or len(sources) < 2:
            self._json_error(400, "Need at least 2 sources for comparison")
            return

        if len(sources) > 6:
            self._json_error(400, "Maximum 6 tracks for comparison")
            return

        duration = self._parse_duration(body)
        if isinstance(duration, str):
            self._json_error(400, duration)
            return

        self._run_ndjson(self._run_compare, sources, duration)

    def _run_single(self, source: str, duration_min: float | None):
        cached = _cache_get(source, duration_min)
        if cached:
            self._send_event("progress", stage="cache",
                             message="Using cached result...")
            self._send_event("result", data=cached)
            return

        with tempfile.TemporaryDirectory(prefix="spectrum_") as workdir:
            if is_url(source):
                self._send_event("progress", stage="download",
                                 message="Downloading audio...")
            else:
                self._send_event("progress", stage="download",
                                 message="Loading file...")

            path, label = resolve_source(source, workdir)
            self._send_event("progress", stage="download",
                             message=f"Loaded: {label}")

            ch, total_sec = probe_info(path)

            ss, dur = None, None
            if duration_min is not None:
                ss, dur, _ = compute_middle(total_sec, duration_min)

            # Stage 2: PCM extraction
            self._send_event("progress", stage="pcm",
                             message="Extracting PCM...")
            mono, stereo = extract_audio(path, ss=ss, duration=dur, channels=ch)

            # Stage 3: Analysis
            self._send_event("progress", stage="analyze",
                             message="Analyzing spectrum...")
            result = analyze_track(mono, label=label, stereo_data=stereo)
            del stereo

        result_dict = result.to_dict()
        result_dict["meta"] = _make_meta(source)
        _cache_put(source, duration_min, result_dict)
        self._send_event("result", data=result_dict)

    def _run_compare(self, sources: list[str], duration_min: float | None):
        n = len(sources)
        track_dicts: list[dict | None] = [None] * n
        to_analyze: list[tuple[int, str]] = []

        for i, source in enumerate(sources):
            cached = _cache_get(source, duration_min)
            if cached:
                self._send_event("progress", stage="cache",
                                 message=f"[{i+1}/{n}] Cached: {cached.get('label', source)}")
                track_dicts[i] = cached
            else:
                to_analyze.append((i, source))

        if to_analyze:
            with tempfile.TemporaryDirectory(prefix="spectrum_") as workdir:
                for i, source in to_analyze:
                    self._send_event("progress", stage="download",
                                     message=f"[{i+1}/{n}] Loading: {source}")
                    sub = os.path.join(workdir, str(i))
                    os.makedirs(sub, exist_ok=True)
                    path, label = resolve_source(source, sub)
                    ch, total_sec = probe_info(path)

                    ss, dur = None, None
                    if duration_min is not None:
                        ss, dur, _ = compute_middle(total_sec, duration_min)

                    self._send_event("progress", stage="pcm",
                                     message=f"[{i+1}/{n}] Extracting PCM: {label}")
                    mono, stereo = extract_audio(path, ss=ss, duration=dur, channels=ch)

                    self._send_event("progress", stage="analyze",
                                     message=f"[{i+1}/{n}] Analyzing: {label}")
                    result = analyze_track(mono, label=label, stereo_data=stereo)
                    del stereo

                    rd = result.to_dict()
                    rd["meta"] = _make_meta(source)
                    _cache_put(source, duration_min, rd)
                    track_dicts[i] = rd

        self._send_event("progress", stage="compare",
                         message="Computing transfer functions...")
        tfs = _transfer_functions_from_dicts(track_dicts)
        compare_dict = {
            "tracks": track_dicts,
            "transfer_functions": tfs,
            "meta": {
                "schema_version": _SCHEMA_VERSION,
                "version": __version__,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "sources": sources,
            },
        }
        self._send_event("compare_result", data=compare_dict)

    def _handle_save(self):
        body = self._read_json_body()
        if body is None:
            self._json_error(400, "Invalid JSON body")
            return
        data = body.get("data")
        filename = body.get("filename", "spectrum_result.json")
        source = body.get("source")
        duration = body.get("duration")

        if not data:
            self._json_error(400, "Missing 'data' field")
            return

        try:
            result = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("JSON Files (*.json)",),
            )
        except Exception:
            result = None

        save_path = self._dialog_path(result)
        if not save_path:
            self._json_response(200, {"saved": False})
            return

        try:
            cache_file = _cache_file(source, duration) if source else None
            if cache_file:
                shutil.copy2(cache_file, save_path)
            else:
                Path(save_path).write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
        except OSError as e:
            self._json_error(500, f"Failed to write file: {e}")
            return
        self._json_response(200, {"saved": True, "path": save_path})

    def _handle_save_image(self):
        body = self._read_json_body(max_size=self._MAX_IMAGE_BODY)
        if body is None:
            self._json_error(400, "Invalid JSON body")
            return
        data_url = body.get("dataUrl", "")
        filename = body.get("filename", "spectrum_result.png")

        if not data_url or not data_url.startswith("data:image/png;base64,"):
            self._json_error(400, "Missing or invalid 'dataUrl' field")
            return

        try:
            result = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("PNG Images (*.png)",),
            )
        except Exception:
            result = None

        save_path = self._dialog_path(result)
        if not save_path:
            self._json_response(200, {"saved": False})
            return
        try:
            png_data = base64.b64decode(data_url.split(",", 1)[1])
            Path(save_path).write_bytes(png_data)
        except (OSError, ValueError) as e:
            self._json_error(500, f"Failed to write image: {e}")
            return
        self._json_response(200, {"saved": True, "path": save_path})

    def _handle_load(self):
        try:
            result = _window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("JSON Files (*.json)",),
                allow_multiple=True,
            )
        except Exception:
            result = None

        if not result:
            self._json_response(200, {"loaded": False})
            return

        file_paths = result if isinstance(result, (list, tuple)) else [result]
        items = []
        for fp in file_paths:
            try:
                text = Path(fp).read_text(encoding="utf-8")
                data = json.loads(text)
            except (OSError, json.JSONDecodeError) as e:
                self._json_error(400, f"Failed to read file: {e}")
                return
            if "tracks" in data:
                self._json_error(400,
                    "Compare result JSON is no longer supported for loading. "
                    "Please load individual track JSON files instead.")
                return
            if "spectrum" not in data:
                self._json_error(400, f"Invalid analysis JSON: {Path(fp).name}")
                return
            items.append(data)

        if len(items) == 1:
            data = items[0]
            resp = {"loaded": True, "type": "single", "data": data}
            # Schema version check for single file load
            schema_ver = data.get("meta", {}).get("schema_version", 0)
            if schema_ver < _SCHEMA_VERSION:
                source = data.get("meta", {}).get("source", "")
                source_available = False
                if source:
                    if is_url(source):
                        source_available = True
                    else:
                        source_available = os.path.isfile(source)
                resp["schema_outdated"] = True
                resp["source"] = source
                resp["source_available"] = source_available
            else:
                self._cache_loaded(data)
            self._json_response(200, resp)
        else:
            for data in items:
                self._cache_loaded(data)
            self._json_response(200, {"loaded": True, "type": "multi", "items": items})

    @staticmethod
    def _cache_loaded(data: dict):
        """Cache loaded JSON data for reuse."""
        if "spectrum" in data:
            src = data.get("meta", {}).get("source")
            if src:
                _cache_put(src, None, data)

    _AUDIO_TYPES = (
        "Audio/Video Files (*.wav;*.mp3;*.m4a;*.flac;*.ogg;*.opus;*.wma;*.aac;*.aiff;*.aif;*.webm;*.mkv;*.mp4)",
    )

    def _handle_browse(self):
        try:
            result = _window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=self._AUDIO_TYPES,
            )
        except Exception:
            result = None

        file_path = self._dialog_path(result)
        if not file_path:
            self._json_response(200, {"selected": False})
            return
        self._json_response(200, {"selected": True, "path": file_path})

    _MAX_UPLOAD = 500 * 1024 * 1024  # 500 MB
    _ALLOWED_EXTENSIONS = {
        ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus",
        ".wma", ".aac", ".aiff", ".aif", ".webm", ".mkv", ".mp4",
    }

    def _handle_upload(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._json_error(400, "Empty file")
            return
        if length > self._MAX_UPLOAD:
            self._json_error(413, "File too large (max 500 MB)")
            return

        from urllib.parse import unquote
        raw_name = unquote(self.headers.get("X-Filename", "dropped_file"))
        name = sanitize_filename(raw_name)
        _, ext = os.path.splitext(raw_name)
        ext = ext.lower()
        if ext not in self._ALLOWED_EXTENSIONS:
            self._json_error(400, f"Unsupported file type: {ext or '(none)'}")
            return
        if not name.endswith(ext):
            name = name + ext

        dest = os.path.join(_upload_dir, name)
        if os.path.exists(dest):
            base_name, base_ext = os.path.splitext(name)
            dest = os.path.join(_upload_dir, f"{base_name}_{int(time.time())}{base_ext}")

        remaining = length
        with open(dest, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)

        if remaining > 0:
            try:
                os.unlink(dest)
            except OSError:
                pass
            self._json_error(400, "Incomplete upload")
            return

        self._json_response(200, {"uploaded": True, "path": dest})

    def _json_response(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _json_error(self, status, message):
        self._json_response(status, {"error": message})

    def _send_event(self, event_type, **kwargs):
        line = json.dumps({"type": event_type, **kwargs}, ensure_ascii=False)
        try:
            self.wfile.write((line + "\n").encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            raise _ClientDisconnected()

    def log_message(self, format, *args):
        pass


_BG_LIGHT = "#fafafa"
_BG_DARK = "#1a1a2e"


def _read_theme_from_leveldb(storage_key: str, ls_dir: Path) -> str | None:
    """Scan a Chromium/WebKit LevelDB dir for a persisted theme value.

    Returns 'light' / 'dark' / None.  Tolerates corrupted log files.
    """
    try:
        for ldb in sorted(ls_dir.glob("*.log"), reverse=True):
            raw = ldb.read_bytes()
            idx = raw.find(storage_key.encode())
            if idx == -1:
                continue
            tail = raw[idx + len(storage_key):idx + len(storage_key) + 40]
            if b"dark" in tail:
                return "dark"
            if b"light" in tail:
                return "light"
    except Exception:
        pass
    return None


def _resolve_background_color(storage_key: str) -> str:
    """Resolve the pywebview initial background color from the theme setting.

    Reads the WebView localStorage from the platform-specific profile path.
    Falls back to OS preference for 'auto' or when the profile is unreadable.
    """
    from desktop_app_common.platform import IS_MAC, IS_WINDOWS
    from desktop_app_common.theme import is_dark_mode

    mode: str | None = None
    if IS_WINDOWS:
        profile = Path(os.environ.get("LOCALAPPDATA", "")) / "pywebview" / "Default"
        ls_dir = profile / "Local Storage" / "leveldb"
        if ls_dir.is_dir():
            mode = _read_theme_from_leveldb(storage_key, ls_dir)
    elif IS_MAC:
        # pywebview on macOS uses WKWebView; WebKit stores localStorage under
        # ~/Library/WebKit/<bundle-id>/WebsiteData/LocalStorage.  Paths vary
        # across OS versions, so try a few candidates.
        home = Path.home()
        candidates = [
            home / "Library/WebKit/pywebview/WebsiteData/LocalStorage",
            home / "Library/Application Support/pywebview/WebsiteData/LocalStorage",
        ]
        for root in candidates:
            if root.is_dir():
                mode = _read_theme_from_leveldb(storage_key, root)
                if mode:
                    break

    if mode is None:
        return _BG_DARK if is_dark_mode() else _BG_LIGHT
    return _BG_DARK if mode == "dark" else _BG_LIGHT


def main():
    # When frozen, add bundled binaries (ffmpeg, ffprobe, deno) to PATH
    if getattr(sys, "frozen", False):
        bin_dir = str(Path(sys._MEIPASS) / "bin")
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

    server = HTTPServer(("127.0.0.1", 0), AnalyzeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    global _window
    bg = _resolve_background_color("spectrum-theme")
    _window = webview.create_window(
        "Spectrum Analyzer",
        url=f"http://127.0.0.1:{port}/index.html",
        width=1200,
        height=900,
        background_color=bg,
    )

    def _disable_external_drop():
        # Disable native file drop (causes unwanted navigation).
        # JavaScript drop handler in main.js handles D&D via /upload endpoint.
        # On macOS (WKWebView) the JS-side stopImmediatePropagation suffices.
        try:
            _window.gui.webview.AllowExternalDrop = False
        except Exception:
            pass
        try:
            _window.gui.webview.CoreWebView2.Settings.IsSwipeNavigationEnabled = False
        except Exception:
            pass

    from desktop_app_common.platform import IS_WINDOWS
    if IS_WINDOWS:
        _window.events.shown += _disable_external_drop
        _window.events.loaded += _disable_external_drop
    webview.start()
    server.shutdown()


if __name__ == "__main__":
    main()
