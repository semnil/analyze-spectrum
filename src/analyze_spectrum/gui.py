"""GUI application: pywebview window + local HTTP server for spectral analysis."""

import atexit
import base64
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections import OrderedDict
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import webview

from analyze_spectrum import SCHEMA_VERSION as _SCHEMA_VERSION, __version__, make_meta as _make_meta
from analyze_spectrum.analysis import _json_safe, analyze_track
from analyze_spectrum.download import compute_middle, is_url, resolve_source, sanitize_filename
from analyze_spectrum.pcm import extract_audio, probe_info

# Temporary directory for uploaded (drag & drop) files, cleaned up on exit
_upload_dir = tempfile.mkdtemp(prefix="spectrum_uploads_")
atexit.register(shutil.rmtree, _upload_dir, True)

# Analysis result cache — avoids re-analysis for same source + duration.
# LRU ordering + bounded capacity prevent unbounded disk growth across a
# long-running session.
_cache_dir = tempfile.mkdtemp(prefix="spectrum_cache_")
atexit.register(shutil.rmtree, _cache_dir, True)


def _cleanup_orphan_tempdirs() -> None:
    """Remove spectrum_* temp directories left by a previous hard-killed run.

    TemporaryDirectory's `with` block cleans up on normal exit, but if the
    webview window is force-closed while a worker is inside PCM extraction
    the directory can survive across sessions.  Sweep them once at shutdown,
    excluding the current process's own tmpdirs.  An mtime threshold of
    1 hour guards against deleting tmpdirs owned by a parallel running
    instance whose files are still fresh.
    """
    own = {_upload_dir, _cache_dir}
    seen = set()
    now = time.time()
    for prefix in ("spectrum_", "spectrum_cache_", "spectrum_uploads_"):
        for path in glob.glob(os.path.join(tempfile.gettempdir(), prefix + "*")):
            if path in own or path in seen:
                continue
            seen.add(path)
            try:
                if os.path.islink(path) or not os.path.isdir(path):
                    continue
                if now - os.path.getmtime(path) <= 3600:
                    continue
                shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass


atexit.register(_cleanup_orphan_tempdirs)
_CACHE_MAX_ENTRIES = 10
_result_cache: "OrderedDict[tuple, str]" = OrderedDict()  # key -> json path
_result_cache_data: "OrderedDict[tuple, dict]" = OrderedDict()  # key -> data
# External /load payloads are kept separate so /analyze can force recomputation
# without being shadowed by a stale user-supplied JSON for the same source.
_loaded_cache_data: "OrderedDict[tuple, dict]" = OrderedDict()
# ThreadingHTTPServer may run concurrent requests; guard cache mutations.
_cache_lock = threading.Lock()
_dialog_lock = threading.Lock()


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
    with _cache_lock:
        data = _result_cache_data.get(key)
        if data is not None:
            _result_cache_data.move_to_end(key)
            if key in _result_cache:
                _result_cache.move_to_end(key)
            return data
        loaded = _loaded_cache_data.get(key)
        if loaded is not None:
            _loaded_cache_data.move_to_end(key)
            return loaded
        path = _result_cache.get(key)
        if path:
            _result_cache.move_to_end(key)
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        with _cache_lock:
            if _result_cache.get(key) == path:
                _result_cache_data[key] = data
                _result_cache_data.move_to_end(key)
        return data
    return None


_cache_seq = 0


def _cache_put(source: str, duration: float | None, result_dict: dict) -> str:
    global _cache_seq
    key = _cache_key(source, duration)
    evicted_paths: list[str] = []
    with _cache_lock:
        # Any /load-derived entry for this key is stale now; drop it so the
        # freshly computed result is used instead.
        _loaded_cache_data.pop(key, None)
        # Evict the previous on-disk copy for this key to prevent orphan files
        # accumulating in _cache_dir across re-analyses of the same source.
        old_path = _result_cache.get(key)
        if old_path:
            evicted_paths.append(old_path)
        _cache_seq += 1
        fname = f"cache_{_cache_seq:04d}.json"
        path = os.path.join(_cache_dir, fname)
        _result_cache[key] = path
        _result_cache.move_to_end(key)
        _result_cache_data[key] = result_dict
        _result_cache_data.move_to_end(key)
        # LRU eviction: drop oldest entries until within capacity.  Also
        # evict any /load-derived payload for the same key; otherwise a
        # subsequent /analyze would see the stale loaded copy instead of
        # recomputing.
        while len(_result_cache) > _CACHE_MAX_ENTRIES:
            old_key, old_p = _result_cache.popitem(last=False)
            _result_cache_data.pop(old_key, None)
            _loaded_cache_data.pop(old_key, None)
            evicted_paths.append(old_p)
    Path(path).write_text(
        json.dumps(result_dict, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    for p in evicted_paths:
        try:
            os.unlink(p)
        except OSError:
            pass
    return path


def _cache_file(source: str, duration: float | None) -> str | None:
    key = _cache_key(source, duration)
    with _cache_lock:
        path = _result_cache.get(key)
        if path:
            _result_cache.move_to_end(key)
    return path if path and os.path.exists(path) else None


def _transfer_functions_from_dicts(track_dicts: list[dict]) -> list[dict]:
    """Compute transfer functions from serialized track dicts.

    When sample rates differ between tracks, clip the reference frequency
    grid to the common Nyquist band so we never extrapolate above the other
    track's highest bin.
    """
    if len(track_dicts) < 2:
        return []
    ref = track_dicts[0]
    ref_freqs = np.array(ref["spectrum"]["freqs"])
    ref_psd = np.array(ref["spectrum"]["psd_db"])
    ref_sr = ref.get("sample_rate")
    # Empty / malformed spectra would raise IndexError on ref_freqs[-1].  Skip
    # transfer-function computation so the compare view still renders tracks.
    if ref_freqs.size == 0:
        return []
    tfs = []
    for other in track_dicts[1:]:
        o_freqs = np.array(other["spectrum"]["freqs"])
        o_psd = np.array(other["spectrum"]["psd_db"])
        o_sr = other.get("sample_rate")
        if o_freqs.size == 0:
            continue
        nyquist = min(float(ref_freqs[-1]), float(o_freqs[-1]))
        grid_mask = ref_freqs <= nyquist
        grid = ref_freqs[grid_mask]
        ref_psd_clipped = ref_psd[grid_mask]
        if len(o_freqs) == len(grid) and np.array_equal(o_freqs, grid):
            delta = o_psd[:len(grid)] - ref_psd_clipped
        else:
            delta = np.interp(grid, o_freqs, o_psd) - ref_psd_clipped
        tf = {
            "label": f"{other['label']} \u2212 {ref['label']}",
            "freqs": grid.tolist(),
            "delta_db": np.round(delta, 2).tolist(),
        }
        if ref_sr is None or o_sr is None:
            tf["warning"] = "sample_rate unknown; frequency comparison may be approximate"
        elif ref_sr != o_sr:
            tf["warning"] = (
                f"sample rate mismatch ({ref_sr} vs {o_sr}); "
                f"clipped to {nyquist:.0f} Hz"
            )
        tfs.append(tf)
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
    _MAX_LOAD_BYTES = 10 * 1024 * 1024  # 10 MB cap for /load JSON files
    _ALLOWED_HOSTS = ("127.0.0.1", "localhost")

    def _check_host(self) -> bool:
        """Reject requests whose Host header is not a loopback literal.

        Defends against DNS rebinding: a malicious page could ask the browser
        to resolve an attacker-controlled name to 127.0.0.1 and talk to this
        server. Rejecting non-loopback Host literals blocks that.
        """
        host = self.headers.get("Host", "")
        host_name = host.split(":", 1)[0] if host else ""
        if host_name not in self._ALLOWED_HOSTS:
            self.send_error(403, "Forbidden: invalid Host")
            return False
        return True

    def _read_json_body(self, max_size: int | None = None) -> dict | None:
        """Read and parse JSON body. Returns None on parse failure."""
        limit = max_size or self._MAX_BODY
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return None
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

    def do_GET(self):
        if not self._check_host():
            return
        super().do_GET()

    def do_POST(self):
        if not self._check_host():
            return
        _STREAM_ENDPOINTS = ("/analyze", "/compare")
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
        if not handler:
            self.send_error(404)
            return
        if self.path in _STREAM_ENDPOINTS:
            handler()
        else:
            try:
                handler()
            except Exception:
                traceback.print_exc()
                try:
                    self._json_error(500, "Internal server error")
                except Exception:
                    pass

    def _parse_duration(self, body: dict) -> float | None | str:
        """Parse and validate duration from request body.

        Returns float (valid), None (not specified), or str (error message).
        """
        duration = body.get("duration")
        if duration is None:
            return None
        # Reject bool explicitly: Python's `bool ⊂ int`, so float(True) == 1.0
        # would silently accept {"duration": true} from the JSON body.
        if isinstance(duration, bool):
            return "'duration' must be a number, not bool"
        try:
            duration = float(duration)
            if not math.isfinite(duration):
                return "'duration' must be a finite number"
            if duration <= 0:
                return "'duration' must be a positive number"
            if duration < 0.01:
                return "'duration' must be >= 0.01 minutes"
            return duration
        except (ValueError, TypeError):
            return "'duration' must be a number"

    def _start_ndjson(self):
        # Stream NDJSON progress + final result.
        # No Content-Length / Transfer-Encoding: chunked, so require close
        # to make message framing unambiguous.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Connection", "close")
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
        except subprocess.CalledProcessError as e:
            # Do not leak full ffmpeg/ffprobe stderr (may contain local paths,
            # codec internals, or long stack traces).  Keep only the last 200
            # bytes for diagnostics.
            stderr_tail = ""
            if e.stderr:
                tail = e.stderr[-200:]
                if isinstance(tail, bytes):
                    tail = tail.decode("utf-8", errors="replace")
                stderr_tail = tail.strip()
            msg = "ffmpeg failed during PCM extraction"
            if stderr_tail:
                msg = f"{msg}: {stderr_tail}"
            try:
                self._send_event("error", error=msg)
            except _ClientDisconnected:
                return
        except Exception as e:
            try:
                self._send_event("error", error=f"Analysis failed: {e}")
            except _ClientDisconnected:
                return

    @staticmethod
    def _reject_bad_scheme(source: str) -> str | None:
        """Return error message if source looks URL-like but not http/https.

        Bare filesystem paths are allowed through (resolved as local files).
        This blocks file://, javascript:, ftp://, etc. before the NDJSON
        stream starts.
        """
        if "://" in source or source.startswith("javascript:"):
            if not source.startswith(("http://", "https://")):
                return "'url' must use http or https scheme"
        return None

    def _handle_analyze(self):
        body = self._read_json_body()
        if body is None:
            self._json_error(400, "Invalid JSON body")
            return
        source = body.get("url", "")

        if not source or not isinstance(source, str):
            self._json_error(400, "Missing or invalid 'url' field")
            return

        # Strip whitespace-only payloads which resolve_source would otherwise
        # hand off to yt-dlp / the filesystem, producing a confusing error
        # mid-stream instead of a clean 400.
        source = source.strip()
        if not source:
            self._json_error(400, "Missing or invalid 'url' field")
            return

        bad = self._reject_bad_scheme(source)
        if bad:
            self._json_error(400, bad)
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

        if not all(isinstance(s, str) and s.strip() for s in sources):
            self._json_error(400, "All sources must be non-empty strings")
            return

        for s in sources:
            bad = self._reject_bad_scheme(s)
            if bad:
                self._json_error(400, bad)
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
        # Sanitize the suggested filename before showing the native dialog so
        # crafted labels (path separators, control chars) cannot preseed a
        # save path outside the user's chosen directory.
        filename = sanitize_filename(body.get("filename", "spectrum_result.json"))
        source = body.get("source")
        duration = body.get("duration")

        if not data:
            self._json_error(400, "Missing 'data' field")
            return

        if not _dialog_lock.acquire(blocking=False):
            self._json_error(409, "A dialog is already open")
            return
        try:
            result = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("JSON Files (*.json)",),
            )
        except Exception:
            result = None
        finally:
            _dialog_lock.release()

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
                    json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False),
                    encoding="utf-8",
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
        filename = sanitize_filename(body.get("filename", "spectrum_result.png"))

        if not data_url or not data_url.startswith("data:image/png;base64,"):
            self._json_error(400, "Missing or invalid 'dataUrl' field")
            return

        if not _dialog_lock.acquire(blocking=False):
            self._json_error(409, "A dialog is already open")
            return
        try:
            result = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("PNG Images (*.png)",),
            )
        except Exception:
            result = None
        finally:
            _dialog_lock.release()

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
        if not _dialog_lock.acquire(blocking=False):
            self._json_error(409, "A dialog is already open")
            return
        try:
            result = _window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("JSON Files (*.json)",),
                allow_multiple=True,
            )
        except Exception:
            result = None
        finally:
            _dialog_lock.release()

        if not result:
            self._json_response(200, {"loaded": False})
            return

        file_paths = result if isinstance(result, (list, tuple)) else [result]
        items = []
        for fp in file_paths:
            if not Path(fp).is_file():
                self._json_error(400, f"Not a file: {Path(fp).name}")
                return
            # Reject oversize JSON upfront rather than OOM on read_text.
            try:
                size = os.path.getsize(fp)
            except OSError as e:
                self._json_error(400, f"Failed to read file: {e}")
                return
            if size > self._MAX_LOAD_BYTES:
                self._json_error(
                    400,
                    f"JSON file exceeds {self._MAX_LOAD_BYTES // (1024 * 1024)} MB: "
                    f"{Path(fp).name}",
                )
                return
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
            # Schema version check for single file load.  Treat meta as an
            # empty dict when missing or explicitly null so chained .get()
            # calls never raise AttributeError on old / hand-edited JSON.
            meta = data.get("meta")
            if not isinstance(meta, dict):
                meta = {}
            schema_ver = meta.get("schema_version", 0)
            # Defend against malformed JSON: coerce non-int values to 0 so the
            # '<' comparison below cannot raise TypeError (str vs int).
            if not isinstance(schema_ver, int) or isinstance(schema_ver, bool):
                schema_ver = 0
            if schema_ver < _SCHEMA_VERSION:
                source = meta.get("source", "")
                if not isinstance(source, str):
                    source = ""
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
        """Cache loaded JSON data for reuse within the current session only.

        External JSON is kept in the in-memory LRU map so the UI can restore
        it, but is NOT written to _cache_dir — we do not want to persist
        user-supplied payloads (which may be large or out-of-spec) across
        app restarts or pollute disk as the user browses files.
        """
        if "spectrum" not in data:
            return
        meta = data.get("meta")
        if not isinstance(meta, dict):
            return
        src = meta.get("source")
        if not isinstance(src, str) or not src:
            return
        key = _cache_key(src, None)
        with _cache_lock:
            _loaded_cache_data[key] = data
            _loaded_cache_data.move_to_end(key)
            while len(_loaded_cache_data) > _CACHE_MAX_ENTRIES:
                _loaded_cache_data.popitem(last=False)

    _AUDIO_TYPES = (
        "Audio/Video Files (*.wav;*.mp3;*.m4a;*.flac;*.ogg;*.opus;*.wma;*.aac;*.aiff;*.aif;*.webm;*.mkv;*.mp4)",
    )

    def _handle_browse(self):
        if not _dialog_lock.acquire(blocking=False):
            self._json_error(409, "A dialog is already open")
            return
        try:
            result = _window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=self._AUDIO_TYPES,
            )
        except Exception:
            result = None
        finally:
            _dialog_lock.release()

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
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self._json_error(400, "Invalid Content-Length")
            return
        if length <= 0:
            self._json_error(400, "Empty file")
            return
        if length > self._MAX_UPLOAD:
            self._json_error(413, "File too large (max 500 MB)")
            return

        from urllib.parse import unquote
        raw_name = unquote(self.headers.get("X-Filename", "dropped_file"))
        name = sanitize_filename(raw_name)
        _, ext = os.path.splitext(name)
        ext = ext.lower()
        if ext not in self._ALLOWED_EXTENSIONS:
            self._json_error(400, f"Unsupported file type: {ext or '(none)'}")
            return
        if not name.endswith(ext):
            name = name + ext

        dest = os.path.join(_upload_dir, name)
        if os.path.commonpath([_upload_dir, os.path.abspath(dest)]) != _upload_dir:
            self._json_error(400, "Invalid filename")
            return
        try:
            if os.path.exists(dest):
                base_name, base_ext = os.path.splitext(name)
                n = 1
                while True:
                    dest = os.path.join(_upload_dir, f"{base_name}_{n}{base_ext}")
                    if not os.path.exists(dest):
                        break
                    n += 1

            remaining = length
            with open(dest, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
        except (OSError, ValueError):
            # crafted X-Filename (null byte, path traversal, permission, etc.)
            try:
                if os.path.exists(dest):
                    os.unlink(dest)
            except OSError:
                pass
            self._json_error(400, "Invalid filename")
            return

        if remaining > 0:
            try:
                os.unlink(dest)
            except OSError:
                pass
            self._json_error(400, "Incomplete upload")
            return

        self._json_response(200, {"uploaded": True, "path": dest})

    def _json_response(self, status, obj):
        # Previously, a NaN/Inf hidden inside externally-loaded JSON would
        # raise ValueError here and drop the TCP connection mid-response,
        # which WebKit surfaces as a terse "Load failed" with no diagnostics.
        # Sanitize on retry instead so the client always sees a proper JSON
        # body and the traceback is preserved in stderr for debugging.
        try:
            body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError):
            traceback.print_exc()
            body = json.dumps(
                _json_safe(obj), ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        # wfile (SocketIO, wbufsize=0) delegates to socket.send() which may
        # perform a partial write when body exceeds SO_SNDBUF (~128 KB).
        # sendall() loops internally until every byte is delivered.
        self.request.sendall(body)

    def _json_error(self, status, message):
        self._json_response(status, {"error": message})

    def _send_event(self, event_type, **kwargs):
        line = json.dumps({"type": event_type, **kwargs},
                          ensure_ascii=False, allow_nan=False)
        try:
            self.request.sendall((line + "\n").encode("utf-8"))
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
        candidates = list(ls_dir.glob("*.log")) + list(ls_dir.glob("*.ldb"))
        for ldb in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
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
    from analyze_common.platform import IS_MAC, IS_WINDOWS
    from analyze_common.theme import is_dark_mode

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

    server = ThreadingHTTPServer(("127.0.0.1", 0), AnalyzeHandler)
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

    from analyze_common.platform import IS_WINDOWS
    if IS_WINDOWS:
        _window.events.shown += _disable_external_drop
        _window.events.loaded += _disable_external_drop
    webview.start()
    server.shutdown()


if __name__ == "__main__":
    main()
