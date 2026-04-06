"""Tests for analyze_spectrum.pcm module."""

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from analyze_spectrum.pcm import SAMPLE_RATE


class TestExtractAudio:
    def test_sample_rate_constant(self):
        assert SAMPLE_RATE == 48000

    def test_extract_audio_builds_correct_cmd(self):
        """Verify ffmpeg command construction without running ffmpeg."""
        import analyze_spectrum.pcm as pcm_mod

        with patch("analyze_spectrum.pcm.subprocess.run") as mock_run, \
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
            assert cmd[0] == "ffmpeg"
            assert "-ar" in cmd
            assert "48000" in cmd
            assert "-ac" in cmd
            assert "-f" in cmd
            assert "f32le" in cmd

    def test_extract_audio_with_ss_and_duration(self):
        """Verify ss and duration flags are passed to ffmpeg."""
        import analyze_spectrum.pcm as pcm_mod

        with patch("analyze_spectrum.pcm.subprocess.run") as mock_run, \
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

        with patch("analyze_spectrum.pcm.subprocess.run") as mock_run, \
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
