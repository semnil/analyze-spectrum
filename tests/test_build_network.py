"""build.py fetches over HTTPS through analyze_common.network."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_build_fetches_through_network():
    direct = re.compile(r"urllib\.request\.(urlopen|urlretrieve|HTTPSHandler)\(|http\.client\.HTTPSConnection\(")
    lines = (ROOT / "build.py").read_text(encoding="utf-8").splitlines()
    assert [f"build.py:{number}" for number, line in enumerate(lines, 1) if direct.search(line)] == []
