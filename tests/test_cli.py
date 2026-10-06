import os
import shlex
from datetime import datetime, timezone

import pytest

from videdit import cli
from videdit.core import settings
from videdit.core.options import ConversionOptions, CropRect
from videdit.core.probe import probe
from videdit.core.settings import Settings


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    """Keep the settings of the user out of the tests"""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def parse(*arguments):
    return vars(cli.build_parser().parse_args(arguments))


def test_only_given_arguments_are_set():
    assert parse("a.mp4") == {"files": ["a.mp4"]}


def test_all_options():
    given = parse("a.mp4", "b.mp4", "-n", "-f", "-o", "out", "--preset", "quick", "--crf", "23",
                  "--start", "5", "--end", "00:01:10", "--fade", "0.5", "--fade-black", "0",
                  "--scale", "720", "--scale", "50%", "--rotate", "-90", "--flip", "h",
                  "--crop", "640:360:2:4", "--crop-aspect", "16:9", "--photo-dir", "photos",
                  "--photo-tolerance", "60", "--rename", "--show-photo",
                  "--time-offset", "+02:00")
    assert given.pop("files") == ["a.mp4", "b.mp4"]
    assert given.pop("dry_run") is True
    assert cli.options_from_args(given, ConversionOptions()) == ConversionOptions(
        preset="quick", crf=23, start=5.0, end=70.0, fade=0.5, fade_black=0.0,
        scales=("720", "50%"), rotate=-90, flip="h", crop=CropRect(640, 360, 2, 4),
        crop_aspect="16:9", photo_dir="photos", photo_tolerance=60.0, rename=True,
        show_photo=True, output_dir="out", time_offset="+02:00", force=True)


def test_arguments_override_saved_options():
    saved = ConversionOptions(fade=1.0, scales=("720",), photo_dir="photos", rename=True,
                              rotate=90)
    given = parse("a.mp4", "--no-fade", "--no-scale", "--no-rename")
    options = cli.options_from_args(given, saved)
    assert (options.fade, options.scales, options.rename) == (0.0, (), False)
    assert (options.photo_dir, options.rotate) == ("photos", 90)
    assert cli.saved_options_in_use(given, saved) == ["rotate=90", "photo_dir=photos"]


@pytest.mark.parametrize("arguments", [
    ["a.mp4", "--start", "soon"], ["a.mp4", "--crop", "640x360"], ["a.mp4", "--rotate", "45"],
    ["a.mp4", "--scale", "big"], ["a.mp4", "--rename"], ["a.mp4", "--start", "9", "--end", "3"],
    ["a.mp4", "--photo-dir", "/surely/missing"], []])
def test_usage_errors(arguments, capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)
    assert raised.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_missing_file(tmp_path, capsys):
    assert cli.main([str(tmp_path / "missing.mp4")]) == 1
    assert "missing.mp4: No such file" in capsys.readouterr().err


def test_missing_ffmpeg(tmp_path, capsys):
    settings.save(Settings(tools=settings.ToolPaths(ffmpeg="surely-not-installed")))
    assert cli.main(["a.mp4"]) == 2
    assert "surely-not-installed was not found" in capsys.readouterr().err


def test_dry_run_prints_the_commands(source, tmp_path, capsys):
    assert cli.main([str(source), "-n", "-o", str(tmp_path), "--scale", "180",
                     "--scale", "50%", "--start", "1"]) == 0
    first, second = (shlex.split(line) for line in capsys.readouterr().out.splitlines())
    assert first[-1] == str(tmp_path / "my source_cut_180p.mp4")
    assert second[-1] == str(tmp_path / "my source_cut_50pct.mp4")
    assert "scale=320:180" in first[first.index("-filter:v") + 1]
    assert os.listdir(tmp_path) == ["config"] or os.listdir(tmp_path) == []


def test_saved_options_are_used_and_can_be_ignored(source, tmp_path, capsys):
    settings.save(Settings(ConversionOptions(rotate=90, fade=0.0)))
    assert cli.main([str(source), "-n"]) == 0
    captured = capsys.readouterr()
    assert "transpose=1" in captured.out
    assert "Using saved options: fade=0.0, rotate=90" in captured.err
    assert cli.main([str(source), "-n", "--defaults"]) == 0
    captured = capsys.readouterr()
    assert "transpose" not in captured.out and "fade=t=in" in captured.out
    assert "saved options" not in captured.err


def test_convert_next_to_the_related_photo(source, make_photo, berlin, tmp_path, capsys):
    # the test video was created at 15:30:00 in Berlin and lasts 4 seconds
    photo = make_photo(tmp_path / "photos" / "DSC0042.JPG", original="2020:04:12 15:30:30")
    make_photo(tmp_path / "photos" / "DSC0001.JPG", original="2020:04:12 12:00:00")
    arguments = [str(source), "--photo-dir", str(tmp_path / "photos"), "--rename",
                 "--scale", "180", "--end", "1", "--no-fade"]
    assert cli.main(arguments) == 0
    target = photo.with_name("DSC0042_my source_cut_180p.mp4")
    result = probe(target)
    assert (result.width, result.height) == (320, 180)
    assert result.duration == pytest.approx(1.0, abs=0.15)
    assert os.path.getmtime(target) == datetime(2020, 4, 12, 13, 30,
                                                tzinfo=timezone.utc).timestamp()
    assert "Related photo, 26s apart: {}".format(photo) in capsys.readouterr().err

    assert cli.main(arguments) == 1
    assert "exists already" in capsys.readouterr().err
    assert cli.main(arguments + ["--force"]) == 0


def test_no_related_photo(source, make_photo, berlin, tmp_path, capsys):
    photo = make_photo(tmp_path / "photos" / "DSC0001.JPG", original="2020:04:12 12:00:00")
    assert cli.main([str(source), "-n", "--photo-dir", str(tmp_path / "photos"),
                     "--rename"]) == 0
    captured = capsys.readouterr()
    assert "No related photo found. The closest one, 12600s apart, is {}".format(photo) \
        in captured.err
    assert shlex.split(captured.out)[-1] == str(source.with_name("my source_conv.mp4"))


def test_example_files(testdata, tmp_path, capsys):
    assert cli.main([str(testdata / "C0031.MP4"), "-n", "--photo-dir", str(testdata),
                     "--rename", "--scale", "720"]) == 0
    captured = capsys.readouterr()
    assert "Related photo, 17s apart" in captured.err
    assert shlex.split(captured.out)[-1] == str(testdata / "DSC02287_C0031_720p.mp4")
