"""release.yaml runs tests/test_ffmpeg_binary.py on the ffmpeg / ffprobe each build ships, before anything is uploaded,
and keeps the release credentials away from third-party code: only create-release can write and it runs no Python,
the update signing key is in a job with a read-only token that installs only the pinned yt-dlp wheel, and the
Developer ID identity is imported right before codesign and deleted when codesign ends.

This file is a mirror of tests/test_release_workflow.py in analyze-loudness and analyze-spectrum; only APP differs.
"""

import re
import subprocess
import sys
from pathlib import Path

APP = "analyze_spectrum"
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


def _jobs():
    """Every job of release.yaml by id, each as its own text."""
    body = WORKFLOW.read_text(encoding="utf-8").split("\njobs:\n", 1)[1]
    return dict(re.findall(r"^  (\S+):\n(.*?)(?=^  \S|\Z)", body, re.M | re.S))


def _steps(job):
    """The steps of ``job`` in release.yaml, each as its own text."""
    return ["- " + step for step in re.split(r"^      - ", _jobs()[job], flags=re.M)[1:]]


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


def test_workflow_token_is_read_only_by_default():
    header = WORKFLOW.read_text(encoding="utf-8").split("\njobs:\n", 1)[0]
    assert re.search(r"^permissions:\n  contents: read\n", header, re.M)
    writers = [job for job, body in _jobs().items() if re.search(r"^\s+\w[\w-]*: write$", body, re.M)]
    assert writers == ["create-release"]


def test_update_signing_key_job_holds_no_write_token_or_unpinned_package():
    jobs = _jobs()
    (signer,) = [job for job, body in jobs.items() if "secrets.UPDATE_SIGNING_KEY" in body]
    body = jobs[signer]
    assert re.search(r"^    permissions:\n      contents: read\n", body, re.M)
    assert "write" not in body
    assert body.count("uses: actions/checkout@") == body.count("persist-credentials: false") == 1
    assert "cache:" not in body
    installs = re.findall(r"pip install[^\n]*", body)
    assert installs and all("--no-deps" in line and "--only-binary :all:" in line for line in installs)
    assert all(" -e " not in line and "--upgrade" not in line for line in installs)


def test_release_job_runs_no_python_and_holds_no_signing_key():
    body = _jobs()["create-release"]
    assert "softprops/action-gh-release@" in body
    assert "secrets." not in body
    assert "actions/checkout@" not in body
    assert "pip " not in body and "python" not in body


def test_macos_signing_identity_is_imported_right_before_codesign_and_deleted_after():
    steps = _steps("build-macos")
    imported = _index(steps, "- name: Import Apple Developer ID Certificate")
    codesign = _index(steps, "- name: Codesign .app")
    assert _index(steps, "- name: Install Dependencies") < _index(steps, "- name: Build .app Bundle") < imported
    assert imported + 1 == codesign
    assert "-T /usr/bin/codesign" in steps[imported]
    assert not re.search(r"(?<!\S)-A(?!\S)", steps[imported])
    assert """trap 'security delete-keychain "$KEYCHAIN_PATH"' EXIT""" in steps[codesign]


# Blocks every import outside the standard library, the app, analyze_common and yt-dlp, as in the signing job.
_ONLY_PINNED = f"""
import importlib, importlib.abc, sys
allowed = set(sys.stdlib_module_names) | {{"{APP}", "analyze_common", "yt_dlp"}}
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] not in allowed:
            raise ModuleNotFoundError(f"not installed in the signing job: {{name}}", name=name)
        return None
sys.meta_path.insert(0, Block())
importlib.import_module("{APP}.update")
importlib.import_module("analyze_common.update_manifest")
"""


def test_the_manifest_tool_runs_with_only_the_pinned_yt_dlp():
    result = subprocess.run([sys.executable, "-c", _ONLY_PINNED], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
