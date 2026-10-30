"""release.yaml runs tests/test_ffmpeg_binary.py on the ffmpeg / ffprobe each build ships, before anything is uploaded,
and keeps the release credentials away from code that is not pinned: only create-release can write and it runs no
Python, the update signing key is in a job with a read-only token, the Developer ID identity is imported right before
codesign and deleted when codesign ends, and each package and build tool a release job installs is checked against a
SHA256 (requirements/*.txt, Inno Setup, create-dmg). Each requirements/*.txt is also a resolution uv accepts for the
command in its header.

This file is a mirror of tests/test_release_workflow.py in analyze-loudness and analyze-spectrum; only APP differs.
"""

import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

APP = "analyze_spectrum"
ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/release.yaml"
TEST_STEP = "- name: Test the Bundled ffmpeg 🧪"
TEST_RUN = "run: python -m pytest -q tests/test_ffmpeg_binary.py"
LOCKS = ("release.txt", "release-build.txt", "sign-manifest.txt")
BUILD_INSTALLS = [
    "pip install --require-hashes --no-deps -r requirements/release-build.txt",
    "pip install --require-hashes --no-deps --no-build-isolation -r requirements/release.txt",
    "pip install --no-deps --no-build-isolation -e .",
]
SIGN_INSTALLS = ["pip install --require-hashes --no-deps --only-binary :all: -r requirements/sign-manifest.txt"]


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


def _lock(name):
    """{canonical name: (version, number of SHA256 hashes)} of requirements/<name>, and the uv command in its header."""
    text = (ROOT / "requirements" / name).read_text(encoding="utf-8")
    command = re.search(r"^#\s+(uv pip compile .*)$", text, re.M).group(1)
    entries = {}
    for block in re.split(r"\n(?=\S)", text):
        first = block.split("\n", 1)[0]
        if not first.strip() or first.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9._-]+)==([^\s;\\]+)(?: ;[^\\]*)? \\", first)
        assert match, f"{name}: not a pinned, hashed requirement: {first!r}"
        hashes = re.findall(r"--hash=sha256:[0-9a-f]{64}", block)
        entries[canonicalize_name(match.group(1))] = (match.group(2), len(hashes))
    return entries, command


def _pins(name, folder=ROOT / "requirements"):
    """{(canonical name, version, environment marker)} of folder/<name>; the marker as packaging writes it, "" when
    there is none."""
    text = (folder / name).read_text(encoding="utf-8")
    return {(canonicalize_name(match.group(1)), match.group(2),
             str(Marker(match.group(3).strip())) if match.group(3) else "")
            for match in re.finditer(r"^([A-Za-z0-9._-]+)==([^\s;\\]+)(?: ;([^\\]*))? \\$", text, re.M)}


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
    assert re.findall(r"pip install[^\n]*", body) == SIGN_INSTALLS


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


def test_build_jobs_install_only_hash_pinned_packages():
    for job in ("build-windows", "build-macos"):
        assert re.findall(r"pip install[^\n]*", _jobs()[job]) == BUILD_INSTALLS, job
        steps = _steps(job)
        install = steps[_index(steps, "- name: Install Dependencies")]
        assert "shell: bash" in install or "shell: bash" in _jobs()[job].split("steps:", 1)[0], job


def test_build_tools_are_checked_against_a_sha256():
    assert "choco install" not in WORKFLOW.read_text(encoding="utf-8")
    assert "brew install" not in WORKFLOW.read_text(encoding="utf-8")
    steps = _steps("build-windows")
    inno = steps[_index(steps, "- name: Install Inno Setup")]
    assert re.search(r"INNOSETUP_SHA256: [0-9a-f]{64}\n", inno)
    assert "(Get-FileHash $installer -Algorithm SHA256).Hash" in inno and "-ne $env:INNOSETUP_SHA256" in inno
    steps = _steps("build-macos")
    dmg = steps[_index(steps, "- name: Install create-dmg")]
    assert re.search(r"CREATE_DMG_SHA256: [0-9a-f]{64}\n", dmg)
    assert 'echo "${CREATE_DMG_SHA256}  ${archive}" | shasum -a 256 -c -' in dmg


def test_locks_are_pinned_and_hashed_for_the_release_python():
    (python,) = set(re.findall(r"python-version: '([0-9.]+)'", WORKFLOW.read_text(encoding="utf-8")))
    for name in LOCKS:
        entries, command = _lock(name)
        assert entries and all(hashes for _, hashes in entries.values()), name
        assert {"--universal", "--generate-hashes", f"--python-version {python}"} <= set(
            re.findall(r"--universal|--generate-hashes|--python-version [0-9.]+", command)), command
        assert command.endswith(f" -o requirements/{name}"), command


def _assert_satisfies(lock, requirements):
    for text in requirements:
        requirement = Requirement(text)
        name = canonicalize_name(requirement.name)
        assert name in lock, text
        assert requirement.specifier.contains(lock[name][0], prereleases=True), (text, lock[name][0])


def test_locks_match_pyproject():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    extras = project["optional-dependencies"]
    release, _ = _lock("release.txt")
    _assert_satisfies(release, project["dependencies"] + extras["gui"] + extras["dev"])
    build, _ = _lock("release-build.txt")
    _assert_satisfies(build, ["pip", "setuptools"] + pyproject["build-system"]["requires"])
    assert all(build[name][0] == release[name][0] for name in set(build) & set(release))
    sign, _ = _lock("sign-manifest.txt")
    assert set(sign) == {"yt-dlp"}
    assert sign["yt-dlp"][0] == release["yt-dlp"][0]


def test_locks_resolve_with_their_own_pins(tmp_path):
    """uv resolves the command in each lock's header again with the lock itself as a constraint, so every pin in the
    lock meets the requirements of the other packages in it, and the resolution holds the same packages at the same
    versions under the same environment markers as the lock: none it needs is missing from the lock, or pinned for
    other platforms (the release jobs install with --no-deps), and none in the lock is left over."""
    for name in LOCKS:
        _, command = _lock(name)
        args = shlex.split(command)[3:]
        args[args.index("-o") + 1] = str(tmp_path / name)
        result = subprocess.run([sys.executable, "-m", "uv", "pip", "compile", "--quiet", *args,
                                 "-c", f"requirements/{name}"], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, f"{name}: {result.stderr}"
        resolved, pinned = _pins(name, tmp_path), _pins(name)
        assert resolved == pinned, (
            f"{name}: missing {sorted(resolved - pinned)}, left over {sorted(pinned - resolved)}")


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
