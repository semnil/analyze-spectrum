"""Extract mono float32 PCM from audio files via ffmpeg."""

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from analyze_spectrum import _subprocess_kwargs
from analyze_spectrum.analysis import SAMPLE_RATE


def probe_info(path: str) -> tuple[int, float]:
    """Return (channels, duration_sec) via a single ffprobe call."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "a:0",
         "-show_format", path],
        capture_output=True, text=True, encoding="utf-8", **_subprocess_kwargs(),
    )
    if r.returncode != 0:
        stderr_tail = (r.stderr or "")[-500:]
        raise RuntimeError(f"ffprobe failed (exit {r.returncode}): {stderr_tail}")
    stdout = r.stdout or ""
    if not stdout.strip():
        raise RuntimeError(f"ffprobe returned empty output for: {path}")
    info = json.loads(stdout)

    channels = 2
    streams = info.get("streams", [])
    if streams:
        channels = int(streams[0].get("channels", 2))
    if channels < 1:
        channels = 1

    dur = info.get("format", {}).get("duration")
    if dur is None:
        raise RuntimeError(f"ffprobe could not determine duration for: {path}")
    return channels, float(dur)


def extract_audio(
    path: str,
    sr: int = SAMPLE_RATE,
    ss: float | None = None,
    duration: float | None = None,
    channels: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract audio via a single ffmpeg call.

    Returns (mono, stereo) where:
        mono: 1D float32 array for spectral analysis
        stereo: 2D (samples, channels) float32 for True Peak (ITU-R BS.1770)

    Mono is derived from stereo in Python using 0.5*L + 0.5*R to preserve
    per-channel levels. ffmpeg's default -ac 1 uses sqrt(2)/2 ≈ 0.707
    which adds ~+3 dB for correlated stereo.
    """
    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = ["ffmpeg", "-y"]
        if ss is not None:
            cmd += ["-ss", str(ss)]
        cmd += ["-i", path]
        if duration is not None:
            cmd += ["-t", str(duration)]
        cmd += ["-ar", str(sr), "-ac", str(channels), "-f", "f32le", tmp_path]

        subprocess.run(
            cmd, check=True, capture_output=True, **_subprocess_kwargs()
        )

        raw = np.fromfile(tmp_path, dtype=np.float32)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if len(raw) == 0:
        raise RuntimeError(f"ffmpeg produced empty PCM output for: {path}")

    stereo = raw.reshape(-1, channels)
    if channels >= 2:
        mono = 0.5 * stereo[:, 0] + 0.5 * stereo[:, 1]
    else:
        mono = stereo[:, 0].copy()
    return mono, stereo
