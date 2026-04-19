"""Tests for analyze_spectrum.analysis module."""

import numpy as np
import pytest

from analyze_spectrum.analysis import (
    NPERSEG,
    SAMPLE_RATE,
    THIRD_OCTAVE_CENTERS,
    SpectrumResult,
    CompareResult,
    analyze_track,
    compare_tracks,
    compute_low_intel_ratio,
    compute_spectral_centroid,
    compute_third_octave_bands,
    compute_welch,
    estimate_hpf,
)


def _sine(freq: float, duration: float = 1.0, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Generate a sine wave at the given frequency."""
    t = np.arange(int(sr * duration)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _white_noise(duration: float = 2.0, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Generate white noise."""
    rng = np.random.default_rng(42)
    return (0.1 * rng.standard_normal(int(sr * duration))).astype(np.float32)


class TestComputeWelch:
    def test_returns_freqs_and_psd(self):
        data = _sine(1000)
        freqs, psd = compute_welch(data)
        assert len(freqs) == len(psd)
        assert freqs[0] == 0.0
        assert freqs[-1] <= SAMPLE_RATE / 2

    def test_peak_at_signal_freq(self):
        data = _sine(1000, duration=2.0)
        freqs, psd = compute_welch(data)
        peak_idx = np.argmax(psd)
        peak_freq = freqs[peak_idx]
        assert abs(peak_freq - 1000) < 20

    def test_short_signal(self):
        # Signal shorter than nperseg should still work (welch auto-adjusts)
        short = np.zeros(100, dtype=np.float32)
        freqs, psd = compute_welch(short)
        assert len(freqs) > 0

    def test_chunked_long_signal(self):
        """Signals exceeding _MAX_CHUNK are processed in chunks."""
        from analyze_spectrum.analysis import _MAX_CHUNK
        # Create signal just over 1 chunk (use noise for consistent PSD)
        n = _MAX_CHUNK + SAMPLE_RATE * 60  # 11 minutes
        rng = np.random.default_rng(99)
        data = (0.1 * rng.standard_normal(n)).astype(np.float32)
        freqs, psd = compute_welch(data)
        assert len(freqs) > 0
        assert np.all(np.isfinite(psd))
        # Should have same freq resolution as non-chunked
        assert abs(freqs[1] - freqs[0] - SAMPLE_RATE / NPERSEG) < 0.01


class TestThirdOctaveBands:
    def test_band_count(self):
        data = _white_noise()
        freqs, psd = compute_welch(data)
        bands = compute_third_octave_bands(freqs, psd)
        assert len(bands) == len(THIRD_OCTAVE_CENTERS)

    def test_all_finite(self):
        data = _white_noise()
        freqs, psd = compute_welch(data)
        bands = compute_third_octave_bands(freqs, psd)
        assert np.all(np.isfinite(bands))

    def test_tone_concentrated(self):
        # 1kHz tone should have high energy in 1kHz band
        data = _sine(1000, duration=2.0)
        freqs, psd = compute_welch(data)
        bands = compute_third_octave_bands(freqs, psd)
        idx_1k = np.argmin(np.abs(THIRD_OCTAVE_CENTERS - 1000))
        # 1kHz band should be near the maximum
        assert bands[idx_1k] >= np.max(bands) - 3

    def test_low_freq_interpolation(self):
        """Low-freq bands (25-40 Hz) should not be -200 dB even with standard nperseg."""
        data = _white_noise(duration=3.0)
        freqs, psd = compute_welch(data)
        bands = compute_third_octave_bands(freqs, psd)
        # 25 Hz band (index 0) should be reasonable, not -200 dB
        assert bands[0] > -120
        # Difference between low bands and mid bands should be bounded
        mid_avg = np.mean(bands[10:15])
        assert abs(bands[0] - mid_avg) < 30


class TestLowIntelRatio:
    def test_low_heavy_positive(self):
        # 100Hz tone: low band has all energy, intel band has none
        data = _sine(100, duration=2.0)
        freqs, psd = compute_welch(data)
        ratio = compute_low_intel_ratio(freqs, psd)
        assert ratio > 20

    def test_high_tone_negative(self):
        # 3kHz tone: intel band has energy, low has none
        data = _sine(3000, duration=2.0)
        freqs, psd = compute_welch(data)
        ratio = compute_low_intel_ratio(freqs, psd)
        assert ratio < -20

    def test_white_noise_near_zero(self):
        data = _white_noise(duration=5.0)
        freqs, psd = compute_welch(data)
        ratio = compute_low_intel_ratio(freqs, psd)
        # White noise: ratio depends on bandwidth ratio
        # 180Hz bandwidth vs 4000Hz bandwidth => should be negative
        assert ratio < 0


class TestSpectralCentroid:
    def test_sine_at_freq(self):
        data = _sine(2000, duration=2.0)
        freqs, psd = compute_welch(data)
        centroid = compute_spectral_centroid(freqs, psd)
        assert abs(centroid - 2000) < 100

    def test_low_tone_low_centroid(self):
        data = _sine(200, duration=2.0)
        freqs, psd = compute_welch(data)
        centroid = compute_spectral_centroid(freqs, psd)
        assert centroid < 500


class TestEstimateHpf:
    def test_no_hpf_returns_none(self):
        data = _white_noise(duration=3.0)
        freqs, psd = compute_welch(data)
        psd_db = 10 * np.log10(psd + 1e-20)
        hpf3, hpf6, slope = estimate_hpf(freqs, psd_db)
        # White noise has no HPF, so -3dB point should be None or very low
        # (depends on noise realization, but should not be above 100Hz)
        if hpf3 is not None:
            assert hpf3 < 50

    def test_filtered_signal(self):
        from scipy.signal import butter, sosfilt
        data = _white_noise(duration=3.0)
        sos = butter(2, 200, btype="high", fs=SAMPLE_RATE, output="sos")
        filtered = sosfilt(sos, data).astype(np.float32)
        freqs, psd = compute_welch(filtered)
        psd_db = 10 * np.log10(psd + 1e-20)
        hpf3, hpf6, slope = estimate_hpf(freqs, psd_db)
        if hpf3 is not None:
            assert 100 < hpf3 < 300


class TestAnalyzeTrack:
    def test_returns_spectrum_result(self):
        data = _white_noise()
        result = analyze_track(data, label="test")
        assert isinstance(result, SpectrumResult)
        assert result.label == "test"
        assert result.sample_rate == SAMPLE_RATE
        assert result.duration_sec > 0

    def test_to_dict_serializable(self):
        import json
        data = _white_noise()
        result = analyze_track(data, label="test")
        d = result.to_dict()
        # Should be JSON-serializable
        json_str = json.dumps(d)
        assert len(json_str) > 0

    def test_band_energy_keys(self):
        data = _white_noise()
        result = analyze_track(data, label="test")
        expected_keys = {"sub_20_80", "low_80_200", "low_mid_200_500",
                         "mid_500_2k", "presence_2k_5k", "air_5k_10k"}
        assert set(result.band_energy.keys()) == expected_keys

    def test_empty_array_raises(self):
        with pytest.raises(ValueError, match="at least 2 samples"):
            analyze_track(np.array([], dtype=np.float32))

    def test_single_sample_raises(self):
        with pytest.raises(ValueError, match="at least 2 samples"):
            analyze_track(np.array([0.1], dtype=np.float32))

    def test_nan_inf_samples_serialize_strict_json(self):
        """NaN/±Inf samples must not leak into the JSON output."""
        import json
        data = _white_noise(duration=2.0).copy()
        data[100:200] = np.nan
        data[300:400] = np.inf
        data[500:600] = -np.inf
        result = analyze_track(data, label="nan_inf")
        d = result.to_dict()
        # allow_nan=False must not raise
        json_str = json.dumps(d, allow_nan=False)
        assert "NaN" not in json_str
        assert "Infinity" not in json_str


    def test_silent_input_returns_none_metrics(self):
        data = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)
        result = analyze_track(data, label="silent")
        assert result.low_intel_ratio_db is None
        assert result.presence_mid_ratio_db is None
        assert result.brightness_db is None
        d = result.to_dict()
        assert d["summary"]["low_intel_ratio_db"] is None

    def test_two_samples_minimum(self):
        data = np.array([0.1, -0.1], dtype=np.float32)
        result = analyze_track(data, label="tiny")
        assert result.duration_sec > 0


class TestCompareTracks:
    def test_single_track_no_tf(self):
        data = _white_noise()
        r = analyze_track(data, label="a")
        comp = compare_tracks([r])
        assert len(comp.transfer_functions) == 0

    def test_two_tracks_one_tf(self):
        d1 = _white_noise(duration=2.0)
        d2 = _white_noise(duration=2.0) * 0.5  # attenuated
        r1 = analyze_track(d1, label="ref")
        r2 = analyze_track(d2, label="cut")
        comp = compare_tracks([r1, r2])
        assert len(comp.transfer_functions) == 1
        assert "cut − ref" in comp.transfer_functions[0]["label"]

    def test_to_dict_serializable(self):
        import json
        d1 = _white_noise(duration=2.0)
        d2 = _white_noise(duration=2.0)
        r1 = analyze_track(d1, label="a")
        r2 = analyze_track(d2, label="b")
        comp = compare_tracks([r1, r2])
        d = comp.to_dict()
        json_str = json.dumps(d)
        assert len(json_str) > 0

    def test_three_tracks(self):
        results = [analyze_track(_white_noise(), label=f"v{i}") for i in range(3)]
        comp = compare_tracks(results)
        assert len(comp.transfer_functions) == 2

    def test_different_length_tracks(self):
        # Short signal produces different nperseg, hence different freq array length
        short = _sine(1000, duration=0.05)  # ~2400 samples, nperseg < 4096
        long = _white_noise(duration=2.0)   # ~96000 samples, nperseg = 4096
        r1 = analyze_track(long, label="ref")
        r2 = analyze_track(short, label="short")
        assert len(r1.freqs) != len(r2.freqs)
        comp = compare_tracks([r1, r2])
        assert len(comp.transfer_functions) == 1
        tf = comp.transfer_functions[0]
        assert len(tf["delta_db"]) == len(r1.freqs)
