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
