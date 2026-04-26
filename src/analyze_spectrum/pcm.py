"""Extract mono float32 PCM from audio files via ffmpeg."""

import subprocess
import tempfile
from pathlib import Path

import numpy as np

from analyze_common.ffmpeg import ffmpeg_kwargs, probe_info  # noqa: F401
from analyze_spectrum.analysis import SAMPLE_RATE


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

    Mono downmix contract:
        - 1 ch source: passthrough.
        - 2 ch source: 0.5*L + 0.5*R to preserve per-channel levels.
          (ffmpeg's default -ac 1 uses sqrt(2)/2 ≈ 0.707 which adds
          ~+3 dB for correlated stereo; we avoid that path.)
        - 3 ch or more (surround): mean across all channels.  This keeps
          LFE / center / surrounds from being silently dropped.
    """
    if channels < 1:
        raise ValueError(f"channels must be >= 1, got {channels}")
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
            cmd, check=True, capture_output=True,
            timeout=600, **ffmpeg_kwargs(),
        )

        raw = np.fromfile(tmp_path, dtype=np.float32)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if len(raw) == 0:
        raise RuntimeError(f"ffmpeg produced empty PCM output for: {path}")

    remainder = len(raw) % channels
    if remainder != 0:
        raw = raw[:-remainder]

    stereo = raw.reshape(-1, channels)
    if channels == 1:
        mono = stereo[:, 0].copy()
    elif channels == 2:
        mono = 0.5 * stereo[:, 0] + 0.5 * stereo[:, 1]
    else:
        mono = stereo.mean(axis=1).astype(np.float32)
    return mono, stereo
