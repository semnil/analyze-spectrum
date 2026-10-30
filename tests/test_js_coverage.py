"""tests/js_coverage.py: matching V8 ranges to lines, and the LCOV it writes (the same file as analyze-loudness's)."""

import pytest

pytest.importorskip("playwright")

from tests.js_coverage import Collector, _code_lines  # noqa: E402

SOURCE = "function f(x) {\n  // note\n  if (x) {\n    return 1;\n  }\n\n  return '\U0001F600';\n}\nf(0);\n"


def _script(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "app.js").write_text(SOURCE, encoding="utf-8")
    return tmp_path / "frontend" / "app.js"


def _offset(text):
    """UTF-16 offset of the first occurrence of text in SOURCE."""
    head = SOURCE[:SOURCE.index(text)]
    return len(head.encode("utf-16-le")) // 2


def _functions(end=None):
    end = len(SOURCE.encode("utf-16-le")) // 2 if end is None else end
    block = {"startOffset": _offset("{\n    return"), "endOffset": _offset("\n\n  return"), "count": 0}
    return [
        {"functionName": "", "ranges": [{"startOffset": 0, "endOffset": end, "count": 1}]},
        {"functionName": "f", "ranges": [
            {"startOffset": 0, "endOffset": _offset("\nf(0)") + 1, "count": 1}, block]},
    ]


def test_code_lines_skip_blank_and_comment_lines_and_count_utf16_units():
    lines = _code_lines(SOURCE)
    assert [number for number, _, _ in lines] == [1, 3, 4, 5, 7, 8, 9]
    _, start, end = lines[4]
    assert (start, end) == (_offset("return '"), _offset("\n}\nf(0)"))


def test_a_line_takes_the_count_of_the_innermost_range_that_holds_it(tmp_path):
    collector = Collector(tmp_path)
    local = _script(tmp_path)
    collector._add(local, _functions())
    collector._add(local, _functions())
    assert collector.hits["frontend/app.js"] == {1: 2, 3: 2, 4: 0, 5: 0, 7: 2, 8: 2, 9: 2}


def test_a_script_of_another_length_than_the_file_fails(tmp_path):
    with pytest.raises(AssertionError, match="UTF-16 units"):
        Collector(tmp_path)._add(_script(tmp_path), _functions(end=len(SOURCE)))


def test_urls_map_to_frontend_scripts_outside_vendor(tmp_path):
    _script(tmp_path)
    (tmp_path / "frontend" / "vendor").mkdir()
    (tmp_path / "frontend" / "vendor" / "lib.js").write_text("x\n", encoding="utf-8")
    collector = Collector(tmp_path)
    assert collector._source("http://127.0.0.1:1/frontend/app.js") == (tmp_path / "frontend" / "app.js").resolve()
    assert collector._source("http://127.0.0.1:1/app.js?v=1") == (tmp_path / "frontend" / "app.js").resolve()
    assert collector._source("http://127.0.0.1:1/vendor/lib.js") is None
    assert collector._source("http://127.0.0.1:1/common/update.js") is None
    assert collector._source("http://127.0.0.1:1/index.html") is None


def test_lcov_lists_every_frontend_script_with_unloaded_ones_at_zero(tmp_path):
    local = _script(tmp_path)
    (tmp_path / "frontend" / "unused.js").write_text("const a = 1;\n", encoding="utf-8")
    collector = Collector(tmp_path)
    collector._add(local, _functions())
    output = tmp_path / "out.lcov"
    collector.write(output)
    records = output.read_text(encoding="utf-8").split("end_of_record\n")
    assert records[0].splitlines() == [
        "TN:", "SF:frontend/app.js", "DA:1,1", "DA:3,1", "DA:4,0", "DA:5,0", "DA:7,1", "DA:8,1", "DA:9,1",
        "LF:7", "LH:5"]
    assert records[1].splitlines() == ["TN:", "SF:frontend/unused.js", "DA:1,0", "LF:1", "LH:0"]
