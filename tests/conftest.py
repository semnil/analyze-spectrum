"""Shared fixtures for analyze-spectrum tests, and the repository and package analyze_common.testing's shared tests
check."""

import math
import struct
from pathlib import Path

import pytest

import analyze_spectrum  # noqa: F401  (puts vendor/py-analyze-common on sys.path)
from analyze_common import testing

testing.configure(Path(__file__).resolve().parent.parent, "analyze_spectrum")


def pytest_addoption(parser):
    parser.addoption("--js-coverage", metavar="PATH",
                     help="write the V8 coverage of frontend/*.js that the Playwright tests ran to PATH as LCOV")


def pytest_configure(config):
    if config.getoption("--js-coverage"):
        from tests.js_coverage import Collector
        config.js_coverage = Collector(Path(__file__).resolve().parent.parent)
        config.js_coverage.install()


def pytest_sessionfinish(session):
    collector = getattr(session.config, "js_coverage", None)
    if collector is not None:
        collector.write(session.config.getoption("--js-coverage"))


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


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path_factory, monkeypatch):
    """Keep the settings file in a temp folder, for the store gui.py has already
    built and for any built during the test (test_gui reloads gui.py)."""
    import sys

    import analyze_spectrum  # noqa: F401  (puts vendor/py-analyze-common on sys.path)
    from analyze_common import settings as settings_module
    from analyze_common import update as update_module
    from analyze_common.settings import SETTINGS_NAME

    folder = tmp_path_factory.mktemp("settings")
    monkeypatch.setattr(settings_module, "settings_dir", lambda product: folder / product)
    monkeypatch.setattr(update_module, "settings_dir", lambda product: folder / product)
    gui = sys.modules.get("analyze_spectrum.gui")
    store = getattr(gui, "_settings", None)
    if store is not None:
        monkeypatch.setattr(store, "path", folder / gui.UPDATE_CONFIG.product / SETTINGS_NAME)
    return folder
