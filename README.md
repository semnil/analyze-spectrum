# analyze-spectrum

> 日本語版は [README.ja.md](README.ja.md) を参照してください.

A tool that comprehensively analyzes the frequency spectrum of a YouTube video or a local audio file.

![Spectrum Analyzer](docs/screenshot.png)

## Features

- **Welch PSD analysis**: Power Spectral Density estimation with scipy.signal.welch
- **1/3-octave band analysis**: 25Hz-10kHz (27 bands)
- **Level metrics**: RMS (dBFS), True Peak (dBTP, ITU-R BS.1770), Crest Factor
- **Spectral shape**: Spectral Tilt (dB/oct), Presence/Mid Ratio, Brightness, HF Rolloff
- **Low/Intelligibility ratio**: low-end / intelligibility balance evaluation based on ANSI S3.5-1997
- **HPF estimation**: the -3dB/-6dB points of the High-Pass Filter + the rolloff slope
- **A/B comparison**: Transfer Function (PSD difference) calculation for up to 6 tracks
- **EQ estimation**: estimates a preamp and peaking filters (frequency, gain, Q) from the Transfer Function and shows them in a table (in the CLI, `--eq-bands` sets the number of bands)
- **GUI**: a desktop app built on pywebview + a local HTTP server
- **5 kinds of charts**: PSD overlay, 1/3 oct bars, Transfer function, Low-end detail, Mid-high detail

## Quick Start

### CLI

```bash
python3 -m venv .venv            # Windows: python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Single file analysis
analyze-spectrum ./recording.m4a
analyze-spectrum "https://www.youtube.com/watch?v=XXXXX"

# A/B comparison (first track = reference)
analyze-spectrum original.m4a eq_v1.m4a eq_v2.m4a

# Analyze only 2 minutes from the middle
analyze-spectrum "https://..." --duration 2

# JSON output
analyze-spectrum ./recording.m4a --json --output-dir ./results
```

### GUI

```bash
pip install -e ".[gui]"
analyze-spectrum-gui
```

In the GUI, enter a URL, or load a local file with the Browse button or drag & drop;
the Analyze button runs a single analysis, and "+ Add Track" registers multiple tracks for a comparison run with Compare.
Dark mode is supported (a 3-way switch Light / Dark / Auto; the default follows the OS setting).
The chosen theme and display language (EN / JA) are kept when the app is restarted.

### Auto-update

The installed app (the installer version on Windows, the DMG version on macOS) checks at launch whether the latest GitHub release has a newer version.
When there is a newer version, it asks "Update now?" and downloads only when OK is chosen.
The downloaded installer is applied after its signature is checked with the public key built into the app, and then the app restarts. Cancel does nothing.

The check at launch can be turned off in the settings dialog opened from the settings button on the toolbar. "Check now" in the same dialog checks by hand as well.
The check at launch shows nothing when there is no newer version or when the check fails.

- Windows: a User Account Control (UAC) prompt appears when the installer runs. The app has already closed by then, so choosing "No" leaves it not updated and the app stays closed. Launching it again shows the update prompt again

The update check and the download connect to the releases on github.com and the delivery host that GitHub redirects release file downloads to (release-assets.githubusercontent.com). The User-Agent of the requests is the app name and version (for example `analyze-spectrum/1.3.1`).

## Architecture

```
pywebview (WebView2) ──HTTP──> Local HTTP Server (gui.py)
                                  │
                                  ├── yt_dlp.YoutubeDL API (URL download)
                                  ├── ffmpeg → PCM (mono + stereo float32, 48kHz)
                                  └── scipy.signal.welch → analysis results
```

See [docs/architecture.md](docs/architecture.md) for details.

## Analysis Metrics

| Metric | Description |
|--------|-------------|
| RMS | Root Mean Square level (dBFS) |
| True Peak | ITU-R BS.1770 True Peak (dBTP, 4x oversampling, per-channel) |
| Crest Factor | True Peak - RMS (dB) |
| Low/Intel Ratio | `10*log10(E[20-200Hz] / E[1-5kHz])` -- energy ratio between the low band and the intelligibility band |
| Spectral Centroid | Energy-weighted mean frequency (80-8kHz) |
| Spectral Tilt | Linear regression of PSD dB against log2(freq) (dB/octave) |
| Presence/Mid Ratio | Presence(2-5kHz) / Mid(500-2kHz) energy ratio |
| Brightness | Air(5-10kHz) / (Mid+Presence 500-5kHz) energy ratio |
| HPF -3dB | The -3dB crossing point from the passband (300-600Hz) reference |
| HF Rolloff | The frequency where the level falls 10dB below the mid-band average |
| Band Energy | Energy per band: Sub / Low / Low-Mid / Mid / Presence / Air |

## System requirements

- Windows (x64)
- macOS: **v1.3.0 and later are for Apple Silicon (M1 and later) only**. Intel Macs (x86_64) are not supported (the bundled ffmpeg / ffprobe were switched to Apple Silicon native builds only, in response to the warning macOS 26 shows that support for apps for Intel processors is ending). If you use an Intel Mac, please use [v1.2.0](../../releases/tag/v1.2.0)

## Build & Distribution

```bash
# Download assets + PyInstaller bundle
python build.py

# + Inno Setup installer (.exe)
python build.py --installer
```

### Prerequisites

- Python 3.12+
- PyInstaller (`pip install pyinstaller`)
- Inno Setup 6 (only when generating the installer)

### Build Assets

`build.py` downloads the following automatically:

- ffmpeg / ffprobe (Windows: BtbN/FFmpeg-Builds, macOS: osxexperts.net. The series and the macOS SHA256 are in `build_assets/ffmpeg.json`)
- deno (GitHub Releases, needed for yt-dlp's YouTube JS extraction)
- uPlot (jsDelivr CDN)

yt-dlp is managed as a Python dependency (`pyproject.toml`), and PyInstaller bundles it automatically.

SHA256 checksums are verified (update them with `python build.py --update-checksums`).

## Project Structure

```
analyze-spectrum/
├── src/analyze_spectrum/
│   ├── analysis.py        # Welch PSD, 1/3 oct, metrics
│   ├── cli.py             # CLI entry point
│   ├── gui.py             # pywebview + HTTP server
│   ├── download.py        # yt_dlp.YoutubeDL API, source resolution
│   ├── pcm.py             # ffmpeg → PCM (mono + stereo)
│   └── update.py          # auto-update config (release repo, public key)
├── frontend/
│   ├── index.html
│   ├── main.js
│   ├── style.css
│   └── charts/            # spectrum, octave, transfer, lowend, midhigh
├── tests/
├── docs/
│   └── architecture.md
├── build.py
├── analyze-spectrum.spec
└── installer.iss
```

## Dependencies

### Runtime

- numpy >= 1.26
- scipy >= 1.12
- yt-dlp
- pywebview >= 5.0 (GUI only)
- certifi (GUI only, CA bundle for the update check)

### External Tools

- ffmpeg / ffprobe

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v

# With coverage
pytest tests/ --cov=analyze_spectrum --cov-report=html
```

## License

See [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt) for bundled third-party software licenses.
