"""Tests for analyze_spectrum.pcm module."""

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from analyze_spectrum.pcm import SAMPLE_RATE

FFMPEG = "/opt/tools/ffmpeg"


class TestExtractAudio:
    def test_sample_rate_constant(self):
        assert SAMPLE_RATE == 48000

    def test_extract_audio_without_ffmpeg_on_path_raises(self):
        """No ffmpeg on PATH: FileNotFoundError before any process starts."""
        import analyze_spectrum.pcm as pcm_mod

        with patch("analyze_spectrum.pcm.find_executable", return_value=None), \
             patch("analyze_spectrum.pcm.subprocess.run") as mock_run:
            with pytest.raises(FileNotFoundError, match="ffmpeg"):
                pcm_mod.extract_audio("input.m4a")
        mock_run.assert_not_called()

    def test_extract_audio_builds_correct_cmd(self):
        """Verify ffmpeg command construction without running ffmpeg."""
        import analyze_spectrum.pcm as pcm_mod

        with patch("analyze_spectrum.pcm.find_executable", return_value=FFMPEG), \
             patch("analyze_spectrum.pcm.subprocess.run") as mock_run, \
             patch("analyze_spectrum.pcm.np.fromfile") as mock_fromfile, \
             patch("analyze_spectrum.pcm.Path") as mock_path:
            mock_run.return_value = MagicMock(returncode=0)
            # Return mono data (1 channel)
            mock_fromfile.return_value = np.array([0.1, 0.2], dtype=np.float32)
            mock_path.return_value.unlink = MagicMock()

            with patch("analyze_spectrum.pcm.tempfile.NamedTemporaryFile") as mock_tmp:
                mock_tmp.return_value.__enter__ = MagicMock(
                    return_value=MagicMock(name="/tmp/test.pcm")
                )
                mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
                mock_tmp.return_value.name = "/tmp/test.pcm"

                mono, stereo = pcm_mod.extract_audio("input.m4a", channels=1)

            assert mock_run.called
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == FFMPEG
            assert "-ar" in cmd
            assert "48000" in cmd
            assert "-ac" in cmd
            assert "-f" in cmd
            assert "f32le" in cmd

    def test_extract_audio_with_ss_and_duration(self):
        """Verify ss and duration flags are passed to ffmpeg."""
        import analyze_spectrum.pcm as pcm_mod

        with patch("analyze_spectrum.pcm.find_executable", return_value=FFMPEG), \
             patch("analyze_spectrum.pcm.subprocess.run") as mock_run, \
             patch("analyze_spectrum.pcm.np.fromfile") as mock_fromfile, \
             patch("analyze_spectrum.pcm.Path") as mock_path:
            mock_run.return_value = MagicMock(returncode=0)
            mock_fromfile.return_value = np.array([0.1], dtype=np.float32)
            mock_path.return_value.unlink = MagicMock()

            with patch("analyze_spectrum.pcm.tempfile.NamedTemporaryFile") as mock_tmp:
                mock_tmp.return_value.__enter__ = MagicMock()
                mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
                mock_tmp.return_value.name = "/tmp/test.pcm"

                mono, stereo = pcm_mod.extract_audio(
                    "input.m4a", ss=30.0, duration=60.0, channels=1
                )

            cmd = mock_run.call_args[0][0]
            assert "-ss" in cmd
            assert "30.0" in cmd
            assert "-t" in cmd
            assert "60.0" in cmd

    def test_extract_audio_stereo_mono_derivation(self):
        """Verify mono is derived from stereo with 0.5*L + 0.5*R."""
        import analyze_spectrum.pcm as pcm_mod

        # Simulate stereo: L=1.0, R=0.5 repeated
        raw = np.array([1.0, 0.5, 1.0, 0.5], dtype=np.float32)

        with patch("analyze_spectrum.pcm.find_executable", return_value=FFMPEG), \
             patch("analyze_spectrum.pcm.subprocess.run") as mock_run, \
             patch("analyze_spectrum.pcm.np.fromfile") as mock_fromfile, \
             patch("analyze_spectrum.pcm.Path") as mock_path:
            mock_run.return_value = MagicMock(returncode=0)
            mock_fromfile.return_value = raw
            mock_path.return_value.unlink = MagicMock()

            with patch("analyze_spectrum.pcm.tempfile.NamedTemporaryFile") as mock_tmp:
                mock_tmp.return_value.__enter__ = MagicMock()
                mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
                mock_tmp.return_value.name = "/tmp/test.pcm"

                mono, stereo = pcm_mod.extract_audio("input.m4a", channels=2)

        assert stereo.shape == (2, 2)
        np.testing.assert_allclose(mono, [0.75, 0.75])


@pytest.fixture
def pcm_output(tmp_path, monkeypatch):
    from pathlib import Path
    from analyze_spectrum import pcm

    make_temp = pcm.tempfile.NamedTemporaryFile
    monkeypatch.setattr(pcm.tempfile, "NamedTemporaryFile", lambda **kwargs: make_temp(dir=tmp_path, **kwargs))
    monkeypatch.setattr(pcm, "find_executable", lambda name: FFMPEG)
    state = {"raw": np.array([], dtype=np.float32), "error": None, "calls": []}

    def run(command, **kwargs):
        state["calls"].append((command, kwargs))
        state["raw"].tofile(command[-1])
        if state["error"]:
            raise state["error"]

    monkeypatch.setattr(pcm.subprocess, "run", run)
    state["files"] = lambda: list(Path(tmp_path).iterdir())
    return state


@pytest.mark.parametrize("channels, raw, expected", [
    (1, [0.2, -0.4], [0.2, -0.4]),
    (2, [1, -1, 0.2, 0.6, 9], [0, 0.4]),
    (3, [1, 0.5, -0.6, -1, 0.2, 0.5, 9, 9], [0.3, -0.1]),
])
def test_pcm_downmix_trims_partial_frame_and_removes_temp_file(pcm_output, channels, raw, expected):
    from analyze_spectrum.pcm import extract_audio

    pcm_output["raw"] = np.array(raw, dtype=np.float32)
    mono, stereo = extract_audio("input.wav", channels=channels)
    np.testing.assert_allclose(mono, expected, atol=1e-7)
    assert stereo.shape == (len(expected), channels)
    assert mono.dtype == stereo.dtype == np.float32
    assert pcm_output["files"]() == []


@pytest.mark.parametrize("failure", ["empty", "process", "timeout"])
def test_pcm_failure_removes_partial_file(pcm_output, failure):
    import subprocess
    from analyze_spectrum.pcm import extract_audio

    error_type = RuntimeError
    if failure != "empty":
        pcm_output["raw"] = np.array([0.2], dtype=np.float32)
        error = subprocess.CalledProcessError(1, [FFMPEG]) if failure == "process" else subprocess.TimeoutExpired([FFMPEG], 600)
        pcm_output["error"] = error
        error_type = type(error)
    with pytest.raises(error_type):
        extract_audio("input.wav", channels=1)
    assert pcm_output["files"]() == []


@pytest.mark.parametrize("channels", [0, -1])
def test_invalid_channel_count_starts_no_process(pcm_output, channels):
    from analyze_spectrum.pcm import extract_audio

    with pytest.raises(ValueError, match="channels must be >= 1"):
        extract_audio("input.wav", channels=channels)
    assert pcm_output["calls"] == []
    assert pcm_output["files"]() == []
