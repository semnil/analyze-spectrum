"""The installed yt-dlp-ejs is the one the installed yt-dlp solves YouTube's challenges with.

yt-dlp uses the solver scripts of yt-dlp-ejs only when the package's major.minor version is the one it names and the
scripts' SHA3-512 are the ones it names (`yt_dlp/extractor/youtube/jsc/_builtin/ejs.py`); otherwise it warns, and the
app passes `no_warnings`. A Dependabot pull request that moves only one of the two fails here.
"""
import hashlib

import yt_dlp_ejs
import yt_dlp_ejs.yt.solver as solver
from yt_dlp.extractor.youtube.jsc._builtin.vendor import _info
from yt_dlp.utils import version_tuple


def _sha3_512(code):
    return hashlib.sha3_512(code.encode()).hexdigest()


def test_yt_dlp_ejs_version_is_the_one_yt_dlp_supports():
    assert version_tuple(yt_dlp_ejs.version, lenient=True)[:2] == version_tuple(_info.VERSION, lenient=True)[:2]


def test_yt_dlp_ejs_scripts_have_the_hashes_yt_dlp_expects():
    assert _sha3_512(solver.core()) == _info.HASHES["yt.solver.core.min.js"]
    assert _sha3_512(solver.lib()) == _info.HASHES["yt.solver.lib.min.js"]
