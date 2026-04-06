"""Shared fixtures for analyze-spectrum tests."""

import math
import struct

import pytest


def _make_wav_bytes(freq: float = 440.0, duration: float = 0.5, sr: int = 48000) -> bytes:
    """Generate a minimal WAV file (mono, 16-bit PCM) as raw bytes."""

    n_samples = int(sr * duration)
    samples = []
    for i in range(n_samples):
        t = i / sr
        val = int(32767 * 0.5 * math.sin(2 * math.pi * freq * t))
        samples.append(struct.pack("<h", max(-32768, min(32767, val))))
    pcm = b"".join(samples)

    # WAV header
    n_channels = 1
    bits_per_sample = 16
    byte_rate = sr * n_channels * bits_per_sample // 8
    block_align = n_channels * bits_per_sample // 8
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, n_channels, sr, byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )
    return header + pcm


@pytest.fixture()
def wav_file(tmp_path):
    """Create a temporary WAV file (440Hz sine, 0.5s, 48kHz mono 16-bit)."""
    path = tmp_path / "test_440hz.wav"
    path.write_bytes(_make_wav_bytes(440.0, 0.5))
    return str(path)


@pytest.fixture()
def wav_file_b(tmp_path):
    """Create a second WAV file (1kHz sine) for comparison tests."""
    path = tmp_path / "test_1khz.wav"
    path.write_bytes(_make_wav_bytes(1000.0, 0.5))
    return str(path)
