import json
import os
import sys
from pathlib import Path

import pytest

from videdit.core import dependencies, settings
from videdit.core.options import ConversionOptions, CropRect
from videdit.core.settings import Settings, ToolPaths


@pytest.fixture
def path(tmp_path):
    return tmp_path / "videdit" / "settings.json"


def test_missing_file_yields_defaults(path):
    assert settings.load(path) == Settings()


def test_round_trip_keeps_sticky_options_only(path):
    options = ConversionOptions(preset="quick", scales=("720",), photo_dir="/photos",
                                photo_tolerance=120.0, crop_aspect="16:9",
                                start=3.0, end=9.0, crop=CropRect(100, 100))
    settings.save(Settings(options, ToolPaths(ffmpeg="/opt/ffmpeg")), path)
    loaded = settings.load(path)
    assert loaded.tools.ffmpeg == "/opt/ffmpeg"
    assert loaded.options.preset == "quick"
    assert loaded.options.scales == ("720",)
    assert loaded.options.photo_tolerance == 120.0
    assert loaded.options.crop_aspect == "16:9"
    assert loaded.options.start is None
    assert loaded.options.end is None
    assert loaded.options.crop is None
    assert os.listdir(path.parent) == ["settings.json"]


@pytest.mark.parametrize("content", ["{not json", "[]",
                                     json.dumps({"options": {"preset": "fast"}})])
def test_broken_files_yield_defaults(path, caplog, content):
    path.parent.mkdir(parents=True)
    path.write_text(content)
    with caplog.at_level("WARNING", logger="videdit"):
        assert settings.load(path) == Settings()
    assert "Ignoring settings file" in caplog.text


def test_unknown_keys_are_ignored(path):
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"options": {"fade": 1.0, "old": 1},
                                "tools": {"ffprobe": "fp", "exiftool": "x"}}))
    loaded = settings.load(path)
    assert loaded.options.fade == 1.0
    assert loaded.tools == ToolPaths(ffprobe="fp")


def test_default_path_follows_xdg(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/cfg")
    assert settings.default_path() == Path("/cfg/videdit/settings.json")
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert settings.default_path() == Path.home() / ".config" / "videdit" / "settings.json"


def test_missing_tools():
    tools = ToolPaths(ffmpeg="surely-not-installed-ffmpeg", ffprobe="sh")
    assert tools.missing() == ["ffmpeg"]


def test_dependency_check(monkeypatch):
    assert dependencies.check(ToolPaths(ffmpeg="sh", ffprobe="sh")) == []
    problem, = dependencies.check(ToolPaths(ffmpeg="surely-not-installed", ffprobe="sh"))
    assert problem.fatal and "surely-not-installed was not found" in problem.message
    monkeypatch.setitem(sys.modules, "exifread", None)
    monkeypatch.setattr(dependencies.importlib.util, "find_spec", lambda name: None)
    problem, = dependencies.check(ToolPaths(ffmpeg="sh", ffprobe="sh"))
    assert not problem.fatal and "exifread" in problem.message
