"""The ffmpeg / ffprobe on PATH, read through the app's own PCM and probe paths.

The input is a 48 kHz 16-bit stereo WAV written with numpy, with a different
sine in each channel. At the analysis sample rate there is no resampling, so
the float32 PCM ffmpeg returns equals each 16-bit sample divided by 32768.

With ``EXPECT_FFMPEG_DIR`` set (the ffmpeg update workflow), the binaries in
that directory go first on PATH, must be the ones found, and a missing one
fails the module instead of skipping it.
"""

import math
import os
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from analyze_spectrum.analysis import SAMPLE_RATE
from analyze_spectrum.pcm import extract_audio, probe_info

SECONDS = 3


@pytest.fixture(scope="module", autouse=True)
def _binaries():
    expected = os.environ.get("EXPECT_FFMPEG_DIR")
    if not expected:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            pytest.skip("ffmpeg / ffprobe not on PATH")
        yield
        return
    directory = Path(expected).resolve()
    patch = pytest.MonkeyPatch()
    patch.setenv("PATH", str(directory) + os.pathsep + os.environ.get("PATH", ""))
    try:
        for tool in ("ffmpeg", "ffprobe"):
            found = shutil.which(tool)
            assert found is not None and Path(found).parent.resolve() == directory, (
                f"{tool} resolves to {found}, not to a file in {directory}")
        yield
    finally:
        patch.undo()


@pytest.fixture(scope="module")
def stereo_wav(tmp_path_factory):
    t = np.arange(SAMPLE_RATE * SECONDS) / SAMPLE_RATE
    left = np.round(0.5 * 32767 * np.sin(2 * math.pi * 1000 * t))
    right = np.round(0.25 * 32767 * np.sin(2 * math.pi * 440 * t))
    pcm = np.stack([left, right], axis=1).astype("<i2")
    path = tmp_path_factory.mktemp("tone") / "stereo.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm.tobytes())
    return str(path), pcm.astype(np.float32) / 32768


def test_ffprobe_reads_channels_and_duration(stereo_wav):
    channels, duration = probe_info(stereo_wav[0])
    assert channels == 2
    assert duration == pytest.approx(SECONDS, abs=1e-3)


def test_pcm_is_the_written_samples(stereo_wav):
    path, expected = stereo_wav
    mono, stereo = extract_audio(path)
    assert stereo.dtype == np.float32
    assert stereo.shape == expected.shape
    assert np.array_equal(stereo, expected)
    assert np.array_equal(mono, 0.5 * expected[:, 0] + 0.5 * expected[:, 1])


def test_pcm_of_a_middle_section(stereo_wav):
    path, expected = stereo_wav
    _, stereo = extract_audio(path, ss=1.0, duration=1.0)
    assert stereo.shape == (SAMPLE_RATE, 2)
    assert np.array_equal(stereo, expected[SAMPLE_RATE:2 * SAMPLE_RATE])
