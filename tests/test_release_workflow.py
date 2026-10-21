"""release.yaml runs tests/test_ffmpeg_binary.py on the ffmpeg / ffprobe each build ships, before anything is uploaded,
and keeps the release credentials out of the steps that run third-party code: only create-release can write, the
Developer ID identity is imported right before codesign and deleted when codesign ends, and the job that signs
latest.json installs only the pinned yt-dlp.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/release.yaml"
TEST_STEP = "- name: Test the Bundled ffmpeg 🧪"
TEST_RUN = "run: python -m pytest -q tests/test_ffmpeg_binary.py"


def _spec_names():
    """The COLLECT directory and the .app bundle the PyInstaller spec builds."""
    (spec,) = ROOT.glob("*.spec")
    text = spec.read_text(encoding="utf-8")
    collect = re.search(r'^coll = COLLECT\(.*?^\s+name="([^"]+)"', text, re.M | re.S).group(1)
    bundle = re.search(r'BUNDLE\(.*?name="([^"]+\.app)"', text, re.S).group(1)
    return collect, bundle


def _job(job):
    """The text of ``job`` in release.yaml."""
    text = WORKFLOW.read_text(encoding="utf-8")
    return re.search(rf"^  {job}:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S).group(1)


def _steps(job):
    """The steps of ``job`` in release.yaml, each as its own text."""
    return ["- " + step for step in re.split(r"^      - ", _job(job), flags=re.M)[1:]]


def _index(steps, line):
    found = [i for i, step in enumerate(steps) if line in step]
    assert len(found) == 1, f"{line!r} is in {len(found)} steps"
    return found[0]


def test_windows_tests_the_collected_binaries_before_the_upload():
    collect, _ = _spec_names()
    installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert f'Source: "dist\\{collect}\\*"' in installer
    steps = _steps("build-windows")
    test = _index(steps, TEST_STEP)
    assert _index(steps, "run: python build.py --installer") < test < _index(steps, "- name: Upload Artifacts")
    assert f"EXPECT_FFMPEG_DIR: dist/{collect}/_internal/bin\n" in steps[test]
    assert TEST_RUN in steps[test]


def test_macos_tests_the_signed_binaries_before_the_dmg():
    _, bundle = _spec_names()
    steps = _steps("build-macos")
    test = _index(steps, TEST_STEP)
    assert _index(steps, "- name: Codesign .app") < test < _index(steps, "- name: Build DMG")
    assert f'APP="dist/{bundle}"' in steps[_index(steps, "- name: Codesign .app")]
    assert f"EXPECT_FFMPEG_DIR: dist/{bundle}/Contents/Frameworks/bin\n" in steps[test]
    assert TEST_RUN in steps[test]
    assert "if:" not in steps[test]


def test_only_create_release_can_write():
    assert re.search(r"^permissions:\n  contents: read\n", WORKFLOW.read_text(encoding="utf-8"), re.M)
    for job in ("check-event", "build-windows", "build-macos"):
        assert "permissions:" not in _job(job), job
    assert "    permissions:\n      contents: write\n" in _job("create-release")


def test_macos_signing_identity_is_imported_right_before_codesign_and_deleted_after():
    steps = _steps("build-macos")
    imported = _index(steps, "- name: Import Apple Developer ID Certificate")
    codesign = _index(steps, "- name: Codesign .app")
    assert _index(steps, "- name: Install Dependencies") < _index(steps, "- name: Build .app Bundle") < imported
    assert imported + 1 == codesign
    assert "-T /usr/bin/codesign" in steps[imported]
    assert not re.search(r"(?<!\S)-A(?!\S)", steps[imported])
    assert """trap 'security delete-keychain "$KEYCHAIN_PATH"' EXIT""" in steps[codesign]


def test_the_signing_job_installs_only_the_pinned_yt_dlp():
    job = _job("create-release")
    installs = re.findall(r"pip install[^\n]*", job)
    assert installs == ['pip install --no-deps "${pin}"']
    assert "startswith(\"yt-dlp==\")" in job and "pyproject.toml" in job
    assert "cache: pip" not in job


# Blocks every import outside the standard library, the app, analyze_common and yt-dlp, as in create-release.
_ONLY_PINNED = """
import importlib, importlib.abc, sys
allowed = set(sys.stdlib_module_names) | {"analyze_spectrum", "analyze_common", "yt_dlp"}
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] not in allowed:
            raise ModuleNotFoundError(f"not installed in create-release: {name}", name=name)
        return None
sys.meta_path.insert(0, Block())
importlib.import_module("analyze_spectrum.update")
importlib.import_module("analyze_common.update_manifest")
"""


def test_the_manifest_tool_runs_with_only_the_pinned_yt_dlp():
    result = subprocess.run([sys.executable, "-c", _ONLY_PINNED], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
