"""Tests for analyze_spectrum.cli module."""

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from analyze_spectrum.download import is_url


class TestIsUrl:
    def test_https(self):
        assert is_url("https://www.youtube.com/watch?v=abc")

    def test_http(self):
        assert is_url("http://example.com/file.m4a")

    def test_local_path(self):
        assert not is_url("/path/to/file.m4a")
        assert not is_url("file.wav")
        assert not is_url("C:\\Users\\file.m4a")


class TestEqBandsOption:
    def test_negative_rejected(self):
        from analyze_spectrum.cli import main
        with pytest.raises(SystemExit):
            main(["a.wav", "--eq-bands", "-1"])

    def test_json_carries_capped_eq(self, wav_file, wav_file_b, capsys):
        import json
        from analyze_spectrum.cli import main
        assert main([wav_file, wav_file_b, "--json", "--eq-bands", "1"]) == 0
        out = capsys.readouterr().out
        data = json.loads(out[out.index("{"):])
        eq = data["transfer_functions"][0]["eq"]
        assert len(eq["bands"]) <= 1
        assert "Estimated EQ" in out
