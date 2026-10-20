"""The GPL texts the FFmpeg entry of THIRD_PARTY_LICENSES.txt names are in the repository, and the spec and the
installer ship them next to the notice."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXTS = {"licenses/GPL-2.0.txt": "Version 2, June 1991", "licenses/GPL-3.0.txt": "Version 3, 29 June 2007"}


def test_the_texts_are_the_gpl_versions_they_are_named_after():
    for path, version in TEXTS.items():
        head = (ROOT / path).read_text(encoding="utf-8").splitlines()[:2]
        assert [line.strip() for line in head] == ["GNU GENERAL PUBLIC LICENSE", version], path


def test_the_notice_names_each_text_for_its_platform():
    notice = (ROOT / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")
    ffmpeg = notice.split("FFmpeg / FFprobe", 1)[1].split("\n---", 2)[1]
    assert re.search(r"Windows build .*?GPL version 3 or later\..*?licenses/GPL-3\.0\.txt", ffmpeg, re.S)
    assert re.search(r"macOS build .*?GPL version 2 or later\..*?licenses/GPL-2\.0\.txt", ffmpeg, re.S)
    assert "(GPL-3.0-or-later)" in ffmpeg and "(GPL-2.0-or-later)" in ffmpeg


def test_the_bundle_puts_the_texts_next_to_the_notice():
    (spec,) = ROOT.glob("*.spec")
    text = spec.read_text(encoding="utf-8")
    assert '(os.path.join(ROOT, "THIRD_PARTY_LICENSES.txt"), "."),' in text
    assert '(os.path.join(ROOT, "licenses"), "licenses"),' in text
    collect = re.search(r'^coll = COLLECT\(.*?^\s+name="([^"]+)"', text, re.M | re.S).group(1)
    installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert re.search(rf'^Source: "dist\\{re.escape(collect)}\\\*";.*\brecursesubdirs\b', installer, re.M)
