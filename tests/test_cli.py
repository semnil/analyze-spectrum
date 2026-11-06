"""Tests for analyze_spectrum.cli module."""

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from analyze_spectrum.download import is_url


class TestIsUrl:
    def test_https(self):
        assert is_url("https://www.youtube.com/watch?v=abc")

    def test_http(self):
        assert is_url("http://example.com/file.m4a")

    def test_local_path(self):
        assert not is_url("/path/to/file.m4a")
        assert not is_url("file.wav")
        assert not is_url("C:\\Users\\file.m4a")


class TestEqBandsOption:
    def test_negative_rejected(self):
        from analyze_spectrum.cli import main
        with pytest.raises(SystemExit):
            main(["a.wav", "--eq-bands", "-1"])

    def test_json_carries_capped_eq(self, wav_file, wav_file_b, capsys):
        import json
        from analyze_spectrum.cli import main
        assert main([wav_file, wav_file_b, "--json", "--eq-bands", "1"]) == 0
        out = capsys.readouterr().out
        data = json.loads(out[out.index("{"):])
        eq = data["transfer_functions"][0]["eq"]
        assert len(eq["bands"]) <= 1
        assert "Estimated EQ" in out


class TestCliRun:
    def test_single_json_and_output_collision(self, wav_file, tmp_path, capsys):
        import json
        from analyze_spectrum import SCHEMA_VERSION
        from analyze_spectrum.cli import main

        out = tmp_path / "out"
        out.mkdir()
        for name in ("analysis.json", "analysis_1.json"):
            (out / name).write_text("keep", encoding="utf-8")
        assert main([wav_file, "--duration", "0.005", "--json", "--output-dir", str(out)]) == 0
        printed = capsys.readouterr()
        data = json.loads(printed.out[printed.out.index("{"):])
        assert json.loads((out / "analysis_2.json").read_text()) == data
        assert data["meta"]["schema_version"] == SCHEMA_VERSION
        assert data["meta"]["source"] == wav_file
        assert data["duration_sec"] == pytest.approx(0.3, abs=0.001)
        assert data["label"] == "test_440hz"
        assert all((out / name).read_text() == "keep" for name in ("analysis.json", "analysis_1.json"))

    @pytest.mark.parametrize("duration", ["0", "-1", "nan", "inf", "-inf", "abc"])
    def test_invalid_duration_starts_no_work(self, duration):
        from analyze_spectrum import cli

        with patch.object(cli, "resolve_source") as resolve:
            with pytest.raises(SystemExit) as error:
                cli.main(["a.wav", "--duration=" + duration])
        assert error.value.code == 2
        resolve.assert_not_called()

    @pytest.mark.parametrize("stage, message", [
        ("resolve_source", "Error: broken"),
        ("probe_info", "Error: broken"),
        ("extract_audio", "Error extracting audio: broken"),
        ("analyze_track", "Error analyzing: broken"),
    ])
    def test_failed_stage_stops_later_work_and_removes_temp_directory(self, tmp_path, capsys, stage, message):
        from pathlib import Path
        from analyze_spectrum import cli

        workdirs = []

        def resolve(source, workdir):
            workdirs.append(Path(workdir))
            return str(tmp_path / "audio.wav"), "Clip"

        with patch.object(cli, "resolve_source", side_effect=resolve) as source, \
             patch.object(cli, "probe_info", return_value=(1, 5.0)) as probe, \
             patch.object(cli, "extract_audio", return_value=(np.ones(4), np.ones((4, 1)))) as extract, \
             patch.object(cli, "analyze_track") as analyze, \
             patch.object(cli, "compare_tracks") as compare:
            steps = {"resolve_source": source, "probe_info": probe, "extract_audio": extract, "analyze_track": analyze}
            steps[stage].side_effect = RuntimeError("broken")
            out = tmp_path / "out"
            assert cli.main(["a.wav", "b.wav", "--output-dir", str(out)]) == 1
            ordered = list(steps)
            for later in ordered[ordered.index(stage) + 1:]:
                steps[later].assert_not_called()
            compare.assert_not_called()
        assert message in capsys.readouterr().err
        assert source.call_count == 1
        assert not out.exists()
        if stage == "resolve_source":
            workdirs.append(Path(source.call_args.args[1]))
        assert workdirs and all(not workdir.exists() for workdir in workdirs)


def test_the_cli_holds_the_instance_lock_while_its_work_folder_exists(wav_file, tmp_path, monkeypatch):
    import glob
    import tempfile
    from analyze_spectrum import cli

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    pattern = str(tmp_path / "spectrum_instance_*.lock")
    seen = []
    resolve = cli.resolve_source

    def watching(source, workdir):
        seen.extend(glob.glob(pattern))
        return resolve(source, workdir)

    monkeypatch.setattr(cli, "resolve_source", watching)
    assert cli.main([wav_file]) == 0
    assert len(seen) == 1
    assert glob.glob(pattern) == []
