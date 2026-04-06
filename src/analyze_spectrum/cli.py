"""CLI entry point for analyze-spectrum."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

from analyze_spectrum import __version__
from analyze_spectrum.analysis import analyze_track, compare_tracks
from analyze_spectrum.download import compute_middle, is_url, resolve_source
from analyze_spectrum.pcm import extract_audio, probe_info


def _print_summary(result) -> None:
    """Print analysis summary to stdout."""
    s = result
    print(f"\n  [{s.label}]")
    print(f"  Duration: {s.duration_sec:.2f}s  RMS: {s.rms_dbfs:.1f} dBFS  Peak: {s.peak_dbfs:.1f} dBFS")
    print(f"  Low/Intel ratio: {s.low_intel_ratio_db:+.1f} dB")
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
    parser.add_argument("--duration", type=float, default=None,
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

            path, label = resolve_source(source, workdir)
            ch, total_sec = probe_info(path)

            ss, dur = None, None
            if args.duration is not None:
                ss, dur, msg = compute_middle(total_sec, args.duration)
                print(f"  {msg}", file=sys.stderr)

            print(f"  Extracting PCM...", file=sys.stderr)
            mono, stereo = extract_audio(path, ss=ss, duration=dur, channels=ch)

            print(f"  Analyzing spectrum...", file=sys.stderr)
            result = analyze_track(mono, label=label, stereo_data=stereo)
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
    else:
        output_data = results[0].to_dict()

    if args.json:
        print(json.dumps(output_data, ensure_ascii=False))

    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "analysis.json"
        out_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2))
        print(f"\nSaved: {out_path}", file=sys.stderr)

    return 0
