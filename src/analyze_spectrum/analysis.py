"""Spectral analysis: Welch PSD, 1/3 octave bands, intelligibility metrics."""

from dataclasses import dataclass, field

import numpy as np
from scipy import signal

SAMPLE_RATE = 48000
NPERSEG = 4096
NOVERLAP = NPERSEG // 2

THIRD_OCTAVE_CENTERS = np.array([
    25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200,
    250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000,
    2500, 3150, 4000, 5000, 6300, 8000, 10000,
])
_THIRD_OCT_FACTOR = 2 ** (1 / 6)

BAND_DEFS = {
    "sub_20_80":       (20, 80),
    "low_80_200":      (80, 200),
    "low_mid_200_500": (200, 500),
    "mid_500_2k":      (500, 2000),
    "presence_2k_5k":  (2000, 5000),
    "air_5k_10k":      (5000, 10000),
}

# ANSI S3.5-1997 derived ranges for Low/Intelligibility ratio
LOW_RANGE = (20, 200)
INTEL_RANGE = (1000, 5000)

# Passband reference for HPF estimation
HPF_PASSBAND = (300, 600)

# True Peak oversampling factor (ITU-R BS.1770)
_TRUE_PEAK_OVERSAMPLE = 4
_TRUE_PEAK_CHUNK = SAMPLE_RATE * 30  # process in 30s chunks


@dataclass
class SpectrumResult:
    """Result of spectral analysis for a single audio track."""

    label: str
    sample_rate: int
    duration_sec: float
    rms_dbfs: float
    peak_dbfs: float

    # Welch PSD
    freqs: np.ndarray
    psd: np.ndarray          # linear power
    psd_db: np.ndarray       # 10*log10(psd)

    # 1/3 octave bands
    band_centers: np.ndarray
    band_energy_db: np.ndarray

    # Summary metrics
    low_intel_ratio_db: float
    spectral_centroid_hz: float
    hpf_3db_hz: float | None
    hpf_6db_hz: float | None
    rolloff_db_per_decade: float | None
    crest_factor_db: float = 0.0
    true_peak_dbtp: float = 0.0
    spectral_tilt_db_oct: float = 0.0
    presence_mid_ratio_db: float = 0.0
    brightness_db: float = 0.0
    hf_rolloff_hz: float | None = None
    band_energy: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dictionary."""
        return {
            "label": self.label,
            "sample_rate": self.sample_rate,
            "duration_sec": round(self.duration_sec, 3),
            "rms_dbfs": round(self.rms_dbfs, 1),
            "peak_dbfs": round(self.peak_dbfs, 1),
            "true_peak_dbtp": round(self.true_peak_dbtp, 1),
            "spectrum": {
                "freqs": self.freqs.tolist(),
                "psd_db": np.round(self.psd_db, 2).tolist(),
            },
            "bands": {
                "centers": self.band_centers.tolist(),
                "energy_db": np.round(self.band_energy_db, 1).tolist(),
            },
            "summary": {
                "low_intel_ratio_db": round(self.low_intel_ratio_db, 1),
                "spectral_centroid_hz": round(self.spectral_centroid_hz, 0),
                "hpf_3db_hz": (round(self.hpf_3db_hz)
                               if self.hpf_3db_hz is not None else None),
                "hpf_6db_hz": (round(self.hpf_6db_hz)
                               if self.hpf_6db_hz is not None else None),
                "rolloff_db_per_decade": (round(self.rolloff_db_per_decade, 1)
                                          if self.rolloff_db_per_decade is not None else None),
                "crest_factor_db": round(self.crest_factor_db, 1),
                "spectral_tilt_db_oct": round(self.spectral_tilt_db_oct, 1),
                "presence_mid_ratio_db": round(self.presence_mid_ratio_db, 1),
                "brightness_db": round(self.brightness_db, 1),
                "hf_rolloff_hz": (round(self.hf_rolloff_hz)
                                  if self.hf_rolloff_hz is not None else None),
                "band_energy": {k: round(v, 1) for k, v in self.band_energy.items()},
            },
        }


@dataclass
class CompareResult:
    """Result of multi-track comparison."""

    tracks: list[SpectrumResult]
    transfer_functions: list[dict]  # [{label, freqs, delta_db}]

    def to_dict(self) -> dict:
        return {
            "tracks": [t.to_dict() for t in self.tracks],
            "transfer_functions": [
                {
                    "label": tf["label"],
                    "freqs": tf["freqs"].tolist(),
                    "delta_db": np.round(tf["delta_db"], 2).tolist(),
                }
                for tf in self.transfer_functions
            ],
        }


def _db(x: float | np.ndarray) -> float | np.ndarray:
    """Convert linear power to dB (10*log10)."""
    return 10 * np.log10(np.maximum(x, 1e-20))


def _band_energy(
    freqs: np.ndarray, psd: np.ndarray, lo: float, hi: float
) -> float:
    """Sum PSD within [lo, hi) Hz band, return linear energy."""
    df = freqs[1] - freqs[0]
    mask = (freqs >= lo) & (freqs < hi)
    return float(np.sum(psd[mask]) * df)


_MAX_CHUNK = SAMPLE_RATE * 600  # 10 minutes per chunk


def compute_welch(
    data: np.ndarray, sr: int = SAMPLE_RATE
) -> tuple[np.ndarray, np.ndarray]:
    """Compute Welch PSD estimate.

    Returns (freqs, psd) where psd is in linear power spectral density.
    Adjusts nperseg/noverlap if the signal is shorter than the default window.
    For long signals (>10 min), processes in chunks and averages PSD to
    avoid excessive memory allocation by scipy.
    """
    n = len(data)
    nperseg = min(NPERSEG, n)
    noverlap = min(NOVERLAP, nperseg - 1) if nperseg > 1 else 0

    if n <= _MAX_CHUNK:
        return signal.welch(data, fs=sr, nperseg=nperseg, noverlap=noverlap)

    # Chunked processing for long signals
    freqs = None
    psd_sum = None
    n_chunks = 0
    for start in range(0, n, _MAX_CHUNK):
        chunk = data[start:start + _MAX_CHUNK]
        if len(chunk) < nperseg:
            break
        f, p = signal.welch(chunk, fs=sr, nperseg=nperseg, noverlap=noverlap)
        if freqs is None:
            freqs = f
            psd_sum = p
        else:
            psd_sum += p
        n_chunks += 1

    if n_chunks == 0:
        # All chunks were shorter than nperseg; fall back to non-chunked
        return signal.welch(data, fs=sr, nperseg=nperseg, noverlap=noverlap)

    return freqs, psd_sum / n_chunks


def compute_third_octave_bands(
    freqs: np.ndarray, psd: np.ndarray
) -> np.ndarray:
    """Compute 1/3 octave band energy in dB for each center frequency.

    When a band is narrower than the frequency resolution (common at low
    frequencies with nperseg=4096 / 48kHz → df=11.7 Hz), interpolate the
    PSD at the band center to estimate energy instead of summing zero bins.
    """
    df = freqs[1] - freqs[0]
    result = np.empty(len(THIRD_OCTAVE_CENTERS))
    for i, fc in enumerate(THIRD_OCTAVE_CENTERS):
        lo = fc / _THIRD_OCT_FACTOR
        hi = fc * _THIRD_OCT_FACTOR
        mask = (freqs >= lo) & (freqs < hi)
        n_bins = np.sum(mask)
        if n_bins >= 1:
            energy = np.sum(psd[mask]) * df
        else:
            # Band is narrower than freq resolution — interpolate PSD
            # at band center and multiply by band width
            psd_interp = float(np.interp(fc, freqs, psd))
            energy = psd_interp * (hi - lo)
        result[i] = _db(energy)
    return result


def compute_low_intel_ratio(freqs: np.ndarray, psd: np.ndarray) -> float:
    """Compute Low (<200Hz) / Intelligibility (1-5kHz) energy ratio in dB.

    Based on ANSI S3.5-1997 band importance function:
    200Hz and below contribute ~6% to SII, while 1-5kHz contributes ~72%.
    A ratio near 0 dB indicates balanced low/intel energy.
    """
    low = _band_energy(freqs, psd, *LOW_RANGE)
    intel = _band_energy(freqs, psd, *INTEL_RANGE)
    return float(_db(low / (intel + 1e-20)))


def compute_spectral_centroid(
    freqs: np.ndarray, psd: np.ndarray,
    lo: float = 80, hi: float = 8000,
) -> float:
    """Compute spectral centroid (energy-weighted mean frequency)."""
    mask = (freqs >= lo) & (freqs <= hi)
    f_sel = freqs[mask]
    p_sel = psd[mask]
    return float(np.sum(f_sel * p_sel) / (np.sum(p_sel) + 1e-20))


def estimate_hpf(
    freqs: np.ndarray, psd_db: np.ndarray,
    passband: tuple[float, float] = HPF_PASSBAND,
) -> tuple[float | None, float | None, float | None]:
    """Estimate HPF -3dB point, -6dB point, and rolloff slope.

    Passband level is the average PSD in the passband region.
    Returns (hpf_3db_hz, hpf_6db_hz, rolloff_db_per_decade).
    """
    pb_mask = (freqs >= passband[0]) & (freqs <= passband[1])
    if not np.any(pb_mask):
        return None, None, None
    passband_level = np.mean(psd_db[pb_mask])

    low_mask = (freqs >= 20) & (freqs <= passband[0])
    f_low = freqs[low_mask]
    db_low = psd_db[low_mask]

    # -3dB crossing
    below_3 = np.where(db_low < passband_level - 3)[0]
    hpf_3db = float(f_low[below_3[-1]]) if len(below_3) > 0 else None

    # -6dB crossing
    below_6 = np.where(db_low < passband_level - 6)[0]
    hpf_6db = float(f_low[below_6[-1]]) if len(below_6) > 0 else None

    # Rolloff slope (dB/decade) via linear regression on log-freq
    slope_mask = (freqs >= 40) & (freqs <= 120)
    if np.sum(slope_mask) >= 3:
        log_f = np.log10(freqs[slope_mask])
        slope = np.polyfit(log_f, psd_db[slope_mask], 1)[0]
        rolloff = float(slope)
    else:
        rolloff = None

    return hpf_3db, hpf_6db, rolloff


def compute_true_peak(data: np.ndarray, sr: int = SAMPLE_RATE) -> float:
    """Compute ITU-R BS.1770 True Peak via 4x oversampling.

    Measures per-channel and returns the maximum across all channels.
    Accepts 1D (mono) or 2D (samples, channels) arrays.
    Processes in chunks to limit memory usage.
    Returns true peak in dBTP.
    """
    if data.ndim == 1:
        data = data[:, np.newaxis]

    peak = 0.0
    for ch in range(data.shape[1]):
        ch_data = data[:, ch]
        for start in range(0, len(ch_data), _TRUE_PEAK_CHUNK):
            chunk = ch_data[start:start + _TRUE_PEAK_CHUNK]
            upsampled = signal.resample_poly(chunk, _TRUE_PEAK_OVERSAMPLE, 1)
            chunk_peak = float(np.max(np.abs(upsampled)))
            if chunk_peak > peak:
                peak = chunk_peak
    return max(float(20 * np.log10(peak + 1e-20)), -120.0)


def compute_spectral_tilt(
    freqs: np.ndarray, psd_db: np.ndarray,
    lo: float = 80, hi: float = 10000,
) -> float:
    """Compute spectral tilt (dB/octave) via linear regression on log2(freq).

    Negative values mean high frequencies are quieter (typical for music).
    Professional mixes typically show -3 to -4 dB/oct.
    """
    mask = (freqs >= lo) & (freqs <= hi)
    if np.sum(mask) < 3:
        return 0.0
    log2_f = np.log2(freqs[mask])
    slope = np.polyfit(log2_f, psd_db[mask], 1)[0]
    return float(slope)


def compute_presence_mid_ratio(freqs: np.ndarray, psd: np.ndarray) -> float:
    """Compute Presence (2-5kHz) / Mid (500-2kHz) energy ratio in dB.

    Positive = voice/instrument "cuts through"; negative = recessed.
    """
    presence = _band_energy(freqs, psd, 2000, 5000)
    mid = _band_energy(freqs, psd, 500, 2000)
    return float(_db(presence / (mid + 1e-20)))


def compute_brightness(freqs: np.ndarray, psd: np.ndarray) -> float:
    """Compute Air (5-10kHz) / (Mid+Presence 500-5kHz) energy ratio in dB.

    Measures relative high-frequency sparkle.
    """
    air = _band_energy(freqs, psd, 5000, 10000)
    mid_pres = _band_energy(freqs, psd, 500, 5000)
    return float(_db(air / (mid_pres + 1e-20)))


def estimate_hf_rolloff(
    freqs: np.ndarray, psd_db: np.ndarray,
    ref_band: tuple[float, float] = (500, 2000),
    threshold: float = -10,
) -> float | None:
    """Estimate high-frequency rolloff point.

    Finds the frequency above ref_band where PSD drops below
    ref_band average + threshold (dB).
    Detects LPF or codec high-frequency cutoff.
    """
    ref_mask = (freqs >= ref_band[0]) & (freqs <= ref_band[1])
    if not np.any(ref_mask):
        return None
    ref_level = np.mean(psd_db[ref_mask])
    target = ref_level + threshold

    hi_mask = freqs > ref_band[1]
    f_hi = freqs[hi_mask]
    db_hi = psd_db[hi_mask]

    below = np.where(db_hi < target)[0]
    if len(below) == 0:
        return None
    return float(f_hi[below[0]])


def analyze_track(
    data: np.ndarray,
    label: str = "track",
    sr: int = SAMPLE_RATE,
    stereo_data: np.ndarray | None = None,
) -> SpectrumResult:
    """Run full spectral analysis on a mono float32 PCM array.

    Args:
        data: mono audio samples (float32, values in [-1, 1]).
        label: identifier for this track (e.g. "original", "v3").
        sr: sample rate in Hz.
        stereo_data: optional stereo PCM (samples, channels) for True Peak.
            If None, True Peak is computed from mono data.

    Returns:
        SpectrumResult with all computed metrics.
    """
    if len(data) == 0:
        raise ValueError("data must not be empty")

    duration = len(data) / sr
    rms = float(20 * np.log10(np.sqrt(np.mean(data ** 2)) + 1e-20))
    peak = float(20 * np.log10(np.max(np.abs(data)) + 1e-20))
    tp_source = stereo_data if stereo_data is not None else data
    true_peak = compute_true_peak(tp_source, sr)
    crest = true_peak - rms

    freqs, psd = compute_welch(data, sr)
    psd_db = _db(psd)

    band_energy_db = compute_third_octave_bands(freqs, psd)
    ratio = compute_low_intel_ratio(freqs, psd)
    centroid = compute_spectral_centroid(freqs, psd)
    hpf_3, hpf_6, rolloff = estimate_hpf(freqs, psd_db)
    tilt = compute_spectral_tilt(freqs, psd_db)
    pres_mid = compute_presence_mid_ratio(freqs, psd)
    bright = compute_brightness(freqs, psd)
    hf_roll = estimate_hf_rolloff(freqs, psd_db)

    bands = {}
    for name, (lo, hi) in BAND_DEFS.items():
        e = _band_energy(freqs, psd, lo, hi)
        bands[name] = float(_db(e))

    return SpectrumResult(
        label=label,
        sample_rate=sr,
        duration_sec=duration,
        rms_dbfs=rms,
        peak_dbfs=peak,
        freqs=freqs,
        psd=psd,
        psd_db=psd_db,
        band_centers=THIRD_OCTAVE_CENTERS,
        band_energy_db=band_energy_db,
        low_intel_ratio_db=ratio,
        spectral_centroid_hz=centroid,
        hpf_3db_hz=hpf_3,
        hpf_6db_hz=hpf_6,
        rolloff_db_per_decade=rolloff,
        crest_factor_db=crest,
        true_peak_dbtp=true_peak,
        spectral_tilt_db_oct=tilt,
        presence_mid_ratio_db=pres_mid,
        brightness_db=bright,
        hf_rolloff_hz=hf_roll,
        band_energy=bands,
    )


def compare_tracks(
    results: list[SpectrumResult],
) -> CompareResult:
    """Compare multiple SpectrumResults and compute transfer functions.

    Transfer functions are computed against the first track (reference).
    """
    if len(results) < 2:
        return CompareResult(tracks=results, transfer_functions=[])

    ref = results[0]
    tfs = []
    for other in results[1:]:
        if len(other.freqs) == len(ref.freqs):
            delta = other.psd_db - ref.psd_db
            freqs = ref.freqs
        else:
            # Interpolate onto the reference frequency grid
            delta = np.interp(ref.freqs, other.freqs, other.psd_db) - ref.psd_db
            freqs = ref.freqs
        tfs.append({
            "label": f"{other.label} − {ref.label}",
            "freqs": freqs,
            "delta_db": delta,
        })

    return CompareResult(tracks=results, transfer_functions=tfs)
