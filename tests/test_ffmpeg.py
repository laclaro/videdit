"""Tests of probe, runner, snapshot and job, most of them run the real ffmpeg."""

import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone

import pytest

from videdit.core import job, metadata, runner
from videdit.core.errors import Cancelled, ConversionError, ToolError
from videdit.core.metadata import CaptureTime
from videdit.core.options import ConversionOptions, CropRect
from videdit.core.probe import VideoInfo, parse_probe, probe
from videdit.core.snapshot import snapshot_command, snapshot_time, take_snapshot

CAPTURE = CaptureTime(datetime(2020, 4, 12, 15, 30), "+02:00")


def test_parse_probe():
    data = {"streams": [{"codec_type": "audio"},
                        {"codec_type": "video", "width": 1920, "height": 1080,
                         "side_data_list": [{"rotation": -90}]}],
            "format": {"duration": "12.5"}}
    info = parse_probe(data)
    assert info == VideoInfo(1920, 1080, 12.5, 270, True)
    assert info.display_size == (1080, 1920)


def test_parse_probe_rotate_tag_and_missing_audio():
    data = {"streams": [{"codec_type": "video", "width": 640, "height": 480,
                         "duration": "3.0", "tags": {"rotate": "180"}}]}
    assert parse_probe(data) == VideoInfo(640, 480, 3.0, 180, False)


@pytest.mark.parametrize("text, created", [
    ("2020-04-12T13:30:00.000000Z", datetime(2020, 4, 12, 13, 30, tzinfo=timezone.utc)),
    ("2020-04-12 13:30:00", datetime(2020, 4, 12, 13, 30, tzinfo=timezone.utc)),
    ("yesterday", None)])
def test_parse_probe_creation_time(text, created):
    data = {"streams": [{"codec_type": "video", "width": 640, "height": 480}],
            "format": {"duration": "3.0", "tags": {"creation_time": text}}}
    assert parse_probe(data).created == created


def test_parse_probe_local_creation_time():
    data = {"streams": [{"codec_type": "video", "width": 640, "height": 480}],
            "format": {"duration": "3.0",
                       "tags": {"com.apple.quicktime.creationdate": "2020-04-12T15:30:00+0200"}}}
    created = parse_probe(data).local_created
    assert created == datetime(2020, 4, 12, 13, 30, tzinfo=timezone.utc)
    assert created.utcoffset() == timedelta(hours=2)
    data["format"]["tags"]["com.apple.quicktime.creationdate"] = "long ago"
    assert parse_probe(data).local_created is None


def test_parse_probe_without_video():
    with pytest.raises(ToolError):
        parse_probe({"streams": [{"codec_type": "audio"}], "format": {"duration": "1"}})


@pytest.mark.parametrize("line, position", [
    ("out_time_us=1500000\n", 1.5),
    ("out_time_ms=2000000\n", 2.0),
    ("out_time_us=-9223372036854775808\n", 0.0),
    ("out_time_us=N/A\n", None),
    ("out_time=00:00:01.500000\n", None),
    ("progress=continue\n", None)])
def test_parse_progress_line(line, position):
    assert runner.parse_progress_line(line) == position


def test_snapshot_time():
    assert snapshot_time(120.0) == 10.0
    assert snapshot_time(8.0) == 4.0


def test_snapshot_command_applies_rotation():
    command = snapshot_command("in.mp4", "shot.png", 10.0, ConversionOptions(rotate=90))
    assert command[6:] == ["-ss", "10", "-i", "in.mp4", "-frames:v", "1",
                           "-filter:v", "transpose=1", "-update", "1", "shot.png"]


def test_missing_ffmpeg(tmp_path):
    with pytest.raises(ToolError):
        runner.run_ffmpeg(["surely-not-installed-ffmpeg", "x"], tmp_path / "x.mp4", 1.0)


def test_probe(info):
    assert (info.width, info.height) == (640, 360)
    assert info.duration == pytest.approx(4.0, abs=0.1)
    assert info.rotation == 0
    assert info.has_audio
    assert info.created == datetime(2020, 4, 12, 13, 30, tzinfo=timezone.utc)


def test_probe_of_missing_file(ffmpeg, tmp_path):
    with pytest.raises(ToolError):
        probe(tmp_path / "missing.mp4")


def test_convert_with_all_filters(source, info, tmp_path):
    options = ConversionOptions(start=1.0, end=3.0, rotate=90, flip="h",
                                crop=CropRect(200, 400, 80, 120), scales=("50%", "150"),
                                preset="quick", output_dir=str(tmp_path))
    jobs = job.plan_jobs(source, options, info, capture=CAPTURE)
    assert [j.target.name for j in jobs] == ["my source_cut_crop_rot90_fliph_quick_50pct.mp4",
                                             "my source_cut_crop_rot90_fliph_quick_150p.mp4"]
    for planned in jobs:
        progress = []
        job.run_job(planned, options, on_progress=progress.append)
        assert progress[-1] == 1.0
        assert progress == sorted(progress)

    results = [probe(planned.target) for planned in jobs]
    assert [(r.width, r.height) for r in results] == [(100, 200), (150, 300)]
    for result in results:
        assert result.duration == pytest.approx(2.0, abs=0.15)
        assert result.has_audio
    # the results tell when their first frame was shot, one second after the start
    shot = datetime(2020, 4, 12, 13, 30, 1, tzinfo=timezone.utc)
    for planned, result in zip(jobs, results):
        assert result.created == shot
        assert result.local_created == shot
        assert result.local_created.utcoffset() == timedelta(hours=2)
        assert os.path.getmtime(planned.target) == shot.timestamp()
        assert metadata.video_capture_time(planned.target, result) \
            == CaptureTime(datetime(2020, 4, 12, 15, 30, 1), "+02:00")


def test_default_conversion_fades(source, info, tmp_path):
    options = ConversionOptions(output_dir=str(tmp_path / "new" / "dir"))
    planned, = job.plan_jobs(source, options, info)
    job.run_job(planned, options)
    result = probe(planned.target)
    assert (result.width, result.height) == (640, 360)
    assert result.duration == pytest.approx(4.0, abs=0.15)
    # the first frame is black because of the fade in
    frame = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(planned.target),
                            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                           capture_output=True, check=True).stdout
    assert max(frame) < 40


def test_existing_target_needs_force(source, info, tmp_path):
    options = ConversionOptions(end=0.5, fade=0.0, output_dir=str(tmp_path))
    planned, = job.plan_jobs(source, options, info)
    planned.target.write_text("precious")
    with pytest.raises(ConversionError, match="exists already"):
        job.run_job(planned, options)
    assert planned.target.read_text() == "precious"
    options.force = True
    job.run_job(planned, options)
    assert probe(planned.target).duration == pytest.approx(0.5, abs=0.15)


def test_failure_removes_the_target(info, tmp_path):
    options = ConversionOptions(output_dir=str(tmp_path / "out"))
    planned, = job.plan_jobs(tmp_path / "missing.mp4", options, info)
    with pytest.raises(ConversionError, match="missing.mp4"):
        job.run_job(planned, options)
    assert not planned.target.exists()


def test_cancel(ffmpeg, tmp_path):
    target = tmp_path / "long.mp4"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25:duration=3600",
               "-c:v", "libx264", str(target)]
    cancel = threading.Event()
    with pytest.raises(Cancelled):
        runner.run_ffmpeg(command, target, 3600.0, lambda fraction: cancel.set(), cancel)
    assert not target.exists()


def test_snapshot(source, info, tmp_path):
    target = tmp_path / "shot.png"
    assert take_snapshot(source, target, info, ConversionOptions(rotate=90)) == 2.0
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
                           str(target)],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert size == "360x640"
