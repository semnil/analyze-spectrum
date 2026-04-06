"""Tests for analyze_spectrum.download module."""

import pytest

from analyze_spectrum.download import sanitize_filename, compute_middle


class TestSanitizeFilename:
    def test_basic(self):
        assert sanitize_filename("hello") == "hello"

    def test_special_chars(self):
        assert sanitize_filename('a/b\\c:d*e?"f<g>h|i') == "a_b_c_d_e__f_g_h_i"

    def test_strip_dots_spaces(self):
        assert sanitize_filename("  .hello. ") == "hello"

    def test_empty(self):
        assert sanitize_filename("") == "untitled"

    def test_long(self):
        name = "a" * 300
        assert len(sanitize_filename(name)) == 200


class TestComputeMiddle:
    def test_short_source(self):
        ss, dur, msg = compute_middle(30, 1.0)
        assert ss == 0.0
        assert dur == 30

    def test_long_source(self):
        ss, dur, msg = compute_middle(600, 2.0)
        assert dur == 120
        assert ss == 240  # (600-120)/2

    def test_exact_match(self):
        ss, dur, msg = compute_middle(60, 1.0)
        assert ss == 0.0
        assert dur == 60

    def test_zero_duration_raises(self):
        with pytest.raises(ValueError, match="positive"):
            compute_middle(120, 0.0)

    def test_negative_duration_raises(self):
        with pytest.raises(ValueError, match="positive"):
            compute_middle(120, -1.0)
