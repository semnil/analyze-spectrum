"""CLI entry point for analyze-spectrum."""

import argparse
import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from analyze_spectrum import SCHEMA_VERSION, __version__, make_meta
from analyze_spectrum.analysis import analyze_track, compare_tracks
from analyze_spectrum.download import compute_middle, is_url, resolve_source
from analyze_spectrum.pcm import extract_audio, probe_info


def _print_summary(result) -> None:
    """Print analysis summary to stdout."""
    s = result
    print(f"\n  [{s.label}]")
    print(f"  Duration: {s.duration_sec:.2f}s  RMS: {s.rms_dbfs:.1f} dBFS  Peak: {s.peak_dbfs:.1f} dBFS")
    if s.low_intel_ratio_db is not None:
        print(f"  Low/Intel ratio: {s.low_intel_ratio_db:+.1f} dB")
    else:
        print(f"  Low/Intel ratio: N/A")
    print(f"  Spectral centroid: {s.spectral_centroid_hz:.0f} Hz")
    if s.hpf_3db_hz is not None:
        print(f"  HPF -3dB: ~{s.hpf_3db_hz:.0f} Hz", end="")
        if s.rolloff_db_per_decade is not None:
            print(f"  ({s.rolloff_db_per_decade:.0f} dB/dec)", end="")
        print()
    print(f"  Band energy:")
    for name, val in s.band_energy.items():
        print(f"    {name:20s}: {val:+.1f} dB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="analyze-spectrum",
        description="Spectral analysis and EQ verification tool.",
    )
    parser.add_argument("sources", nargs="+",
                        help="Audio file paths or YouTube URLs")
    def _positive_finite_float(v):
        f = float(v)
        if not math.isfinite(f) or f <= 0:
            raise argparse.ArgumentTypeError(f"must be a positive finite number, got {v!r}")
        return f

    parser.add_argument("--duration", type=_positive_finite_float, default=None,
                        help="Analyze only N minutes from the middle")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory for JSON results")
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON to stdout")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    results = []
    with tempfile.TemporaryDirectory(prefix="spectrum_") as workdir:
        for i, source in enumerate(args.sources):
            print(f"[{i + 1}/{len(args.sources)}] Processing: {source}", file=sys.stderr)

            try:
                path, label = resolve_source(source, workdir)
                ch, total_sec = probe_info(path)
            except Exception as exc:
                print(f"  Error: {exc}", file=sys.stderr)
                return 1

            ss, dur = None, None
            if args.duration is not None:
                ss, dur, msg = compute_middle(total_sec, args.duration)
                print(f"  {msg}", file=sys.stderr)

            print(f"  Extracting PCM...", file=sys.stderr)
            try:
                mono, stereo = extract_audio(path, ss=ss, duration=dur, channels=ch)
            except Exception as exc:
                print(f"  Error extracting audio: {exc}", file=sys.stderr)
                return 1

            print(f"  Analyzing spectrum...", file=sys.stderr)
            try:
                result = analyze_track(mono, label=label, stereo_data=stereo)
            except Exception as exc:
                print(f"  Error analyzing: {exc}", file=sys.stderr)
                return 1
            results.append(result)
            _print_summary(result)

    if len(results) >= 2:
        comparison = compare_tracks(results)
        print(f"\n=== Transfer Functions ===")
        for tf in comparison.transfer_functions:
            # Show summary of transfer function
            freqs = tf["freqs"]
            delta = tf["delta_db"]
            low_mask = (freqs >= 20) & (freqs < 200)
            mid_mask = (freqs >= 500) & (freqs < 2000)
            hi_mask = (freqs >= 2000) & (freqs < 5000)
            print(f"  {tf['label']}:")
            print(f"    Low (<200Hz):  {np.mean(delta[low_mask]):+.1f} dB avg")
            print(f"    Mid (500-2k):  {np.mean(delta[mid_mask]):+.1f} dB avg")
            print(f"    Pres (2-5k):   {np.mean(delta[hi_mask]):+.1f} dB avg")

        output_data = comparison.to_dict()
        output_data["meta"] = {
            "schema_version": SCHEMA_VERSION,
            "version": __version__,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "sources": list(args.sources),
        }
    else:
        output_data = results[0].to_dict()
        output_data["meta"] = make_meta(args.sources[0])

    if args.json:
        print(json.dumps(output_data, ensure_ascii=False, allow_nan=False))

    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "analysis.json"
        if out_path.exists():
            n = 1
            while True:
                out_path = out_dir / f"analysis_{n}.json"
                if not out_path.exists():
                    break
                n += 1
        out_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2, allow_nan=False))
        print(f"\nSaved: {out_path}", file=sys.stderr)

    return 0
