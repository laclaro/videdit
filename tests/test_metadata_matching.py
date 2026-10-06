import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from videdit.core import job, metadata, process
from videdit.core.errors import ToolError
from videdit.core.matching import Match, Photo, PhotoIndex, video_interval
from videdit.core.metadata import (CaptureTime, camera_creation_time, format_offset,
                                   parse_exif_datetime, parse_offset, photo_capture_time,
                                   video_capture_time)
from videdit.core.options import ConversionOptions
from videdit.core.probe import VideoInfo, probe

START = datetime(2020, 4, 12, 15, 30, 0)
END = datetime(2020, 4, 12, 15, 31, 0)
# 15:30 in Berlin (summer time)
CREATED = datetime(2020, 4, 12, 13, 30, tzinfo=timezone.utc)


def video(created=CREATED):
    return VideoInfo(1920, 1080, 60.0, created=created)


def index_of(*times):
    return PhotoIndex([Photo(Path("{}.jpg".format(i)), datetime(2020, 4, 12, *time))
                       for i, time in enumerate(times)])


@pytest.mark.parametrize("text", ["2020:04:12 15:30:05", "2020:04:12 15:30:05.25",
                                  "2020:04:12 15:30:05+02:00", " 2020:04:12 15:30:05 "])
def test_parse_exif_datetime(text):
    assert parse_exif_datetime(text) == datetime(2020, 4, 12, 15, 30, 5)


@pytest.mark.parametrize("text", ["", "-", "0000:00:00 00:00:00", "2020-04-12", 1586698205])
def test_parse_exif_datetime_invalid(text):
    assert parse_exif_datetime(text) is None


@pytest.mark.parametrize("text", ["+02:00", "-05:30", "+00:00"])
def test_offset_round_trip(text):
    assert format_offset(parse_offset(text)) == text


def test_capture_time_start():
    assert CaptureTime(START, "+02:00").start(60.0) == CREATED
    assert CaptureTime(START, "+02:00").start(60.0).utcoffset() == parse_offset("+02:00")
    assert CaptureTime(END, "+02:00", at_end=True).start(60.0) == CREATED


def test_photo_capture_time(make_photo, tmp_path):
    photo = make_photo(tmp_path / "a.jpg", original="2020:04:12 15:30:00",
                       digitized="2020:04:12 16:00:00")
    assert photo_capture_time(photo) == START


def test_photo_capture_time_falls_back_to_digitized(make_photo, tmp_path):
    photo = make_photo(tmp_path / "a.jpg", original="0000:00:00 00:00:00",
                       digitized="2020:04:12 15:31:00")
    assert photo_capture_time(photo) == END


def test_photo_without_capture_time(make_photo, tmp_path):
    assert photo_capture_time(make_photo(tmp_path / "a.jpg")) is None
    (tmp_path / "broken.jpg").write_bytes(b"not a picture")
    assert photo_capture_time(tmp_path / "broken.jpg") is None
    assert photo_capture_time(tmp_path / "missing.jpg") is None


def test_video_capture_time_uses_the_time_zone_of_the_computer(berlin):
    assert video_capture_time("C0001.MP4", video()) == CaptureTime(START, "+02:00")
    winter = datetime(2020, 1, 12, 14, 30, tzinfo=timezone.utc)
    assert video_capture_time("C0001.MP4", video(winter)) \
        == CaptureTime(datetime(2020, 1, 12, 15, 30), "+01:00")


def test_video_capture_time_with_given_offset(berlin):
    assert video_capture_time("C0001.MP4", video(), "-05:30") \
        == CaptureTime(datetime(2020, 4, 12, 8, 0), "-05:30")


def test_video_capture_time_falls_back_to_modification_time(berlin, tmp_path):
    path = tmp_path / "C0001.MP4"
    path.touch()
    os.utime(path, (CREATED.timestamp(), CREATED.timestamp()))
    assert video_capture_time(path, video(None)) == CaptureTime(START, "+02:00", at_end=True)


def test_camera_creation_time(make_sony_video, tmp_path):
    clip = make_sony_video(tmp_path / "C0001.MP4", "2020-04-12T15:30:00+02:00")
    assert camera_creation_time(clip) == CREATED
    assert camera_creation_time(clip).utcoffset() == parse_offset("+02:00")


def test_camera_creation_time_of_other_files(make_sony_video, tmp_path):
    assert camera_creation_time(make_sony_video(tmp_path / "a.mp4", "yesterday")) is None
    assert camera_creation_time(make_sony_video(tmp_path / "b.mp4", "2020-04-12T15:30:00")) is None
    (tmp_path / "c.mts").write_bytes(bytes(range(256)) * 20)
    assert camera_creation_time(tmp_path / "c.mts") is None
    (tmp_path / "empty.mp4").touch()
    assert camera_creation_time(tmp_path / "empty.mp4") is None
    assert camera_creation_time(tmp_path / "missing.mp4") is None


def test_camera_creation_time_from_the_xml_file(tmp_path):
    clip = tmp_path / "C0001.MP4"
    clip.write_bytes(bytes(64))
    assert camera_creation_time(clip) is None
    (tmp_path / "C0001M01.XML").write_text(
        '<NonRealTimeMeta><CreationDate value="2020-04-12T15:30:00+02:00"/></NonRealTimeMeta>')
    assert camera_creation_time(clip) == CREATED


def test_embedded_time_wins_over_the_xml_file(make_sony_video, tmp_path):
    clip = make_sony_video(tmp_path / "C0001.MP4", "2020-04-12T15:30:00+02:00")
    (tmp_path / "C0001M01.XML").write_text('<CreationDate value="2021-01-01T00:00:00+01:00"/>')
    assert camera_creation_time(clip) == CREATED


@pytest.mark.parametrize("zone", ["Europe/Berlin", "America/New_York"])
def test_video_capture_time_prefers_the_offset_of_the_camera(make_sony_video, tmp_path,
                                                            computer_timezone, zone):
    computer_timezone(zone)
    clip = make_sony_video(tmp_path / "C0001.MP4", "2020-04-12T15:30:00+02:00")
    assert video_capture_time(clip, video(None)) == CaptureTime(START, "+02:00")
    assert video_capture_time(clip, video(None), "+03:00") \
        == CaptureTime(datetime(2020, 4, 12, 16, 30), "+03:00")


def test_video_capture_time_of_camera_in_utc(make_sony_video, tmp_path, berlin):
    clip = make_sony_video(tmp_path / "C0001.MP4", "2020-04-12T13:30:00+00:00")
    assert video_capture_time(clip, video()) \
        == CaptureTime(datetime(2020, 4, 12, 13, 30), "+00:00")


def test_output_tags():
    created = CaptureTime(START, "+02:00").start(60.0)
    assert metadata.output_tags(created) == {
        "creation_time": "2020-04-12T13:30:00.000000Z",
        "com.apple.quicktime.creationdate": "2020-04-12T15:30:00+0200"}
    assert metadata.output_tags(created, ("Sony", "ILCE-6300")) == {
        "creation_time": "2020-04-12T13:30:00.000000Z",
        "com.apple.quicktime.creationdate": "2020-04-12T15:30:00+0200",
        "com.apple.quicktime.make": "Sony", "com.apple.quicktime.model": "ILCE-6300"}


def test_video_capture_time_uses_the_stored_local_time(computer_timezone):
    computer_timezone("America/New_York")
    local = datetime(2020, 4, 12, 15, 30, tzinfo=timezone(parse_offset("+02:00")))
    info = VideoInfo(1920, 1080, 60.0, created=CREATED, local_created=local)
    assert video_capture_time("C0001.MP4", info) == CaptureTime(START, "+02:00")


def test_video_interval():
    assert video_interval(CaptureTime(START, "+02:00"), 60.0) == (START, END)
    assert video_interval(CaptureTime(END, "+02:00", at_end=True), 60.0) == (START, END)


def test_no_photos():
    assert PhotoIndex([]).closest(START, END) is None
    assert PhotoIndex([]).match(START, END, 300) is None


@pytest.mark.parametrize("taken, distance", [((15, 29, 30), 30.0), ((15, 31, 45), 45.0),
                                             ((15, 30, 20), 0.0)])
def test_distance_is_measured_from_the_edges_of_the_recording(taken, distance):
    assert index_of(taken).closest(START, END).distance == distance


def test_closest_photo_wins():
    index = index_of((15, 20, 0), (15, 31, 10), (15, 29, 40), (16, 0, 0))
    assert index.closest(START, END) \
        == Match(Photo(Path("1.jpg"), datetime(2020, 4, 12, 15, 31, 10)), 10.0)


def test_tolerance():
    index = index_of((15, 36, 0))
    assert index.match(START, END, 299) is None
    assert index.match(START, END, 300).distance == 300.0


def test_scan_reads_photos_recursively(make_photo, tmp_path, caplog):
    make_photo(tmp_path / "a.JPG", original="2020:04:12 15:00:00")
    make_photo(tmp_path / "sub" / "b.jpeg", original="2020:04:12 14:00:00")
    make_photo(tmp_path / "a.ARW", original="2020:04:12 15:00:00")
    make_photo(tmp_path / "undated.jpg")
    (tmp_path / "notes.txt").write_text("no photo")
    with caplog.at_level("WARNING", logger="videdit"):
        index = PhotoIndex.scan(tmp_path)
    assert index.photos == [Photo(tmp_path / "sub" / "b.jpeg", datetime(2020, 4, 12, 14)),
                            Photo(tmp_path / "a.JPG", datetime(2020, 4, 12, 15))]
    assert "undated.jpg skipped" in caplog.text
    assert "notes.txt" not in caplog.text and "a.ARW" not in caplog.text


def test_scan_of_missing_directory(tmp_path):
    assert PhotoIndex.scan(tmp_path / "missing").photos == []


def test_video_matches_photo(make_photo, berlin, tmp_path, ffmpeg):
    """A video and a photo of the same minute, read with ffprobe and exifread"""
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=64x64:rate=5:duration=1", "-metadata",
                    "creation_time=2020-04-12T13:30:00Z", str(clip)], check=True)
    photo = make_photo(tmp_path / "photos" / "DSC0042.JPG", original="2020:04:12 15:30:20")
    info = probe(clip)
    capture = video_capture_time(clip, info)
    options = ConversionOptions(photo_dir=str(tmp_path / "photos"), rename=True)
    match = job.find_photo(capture, info, options, PhotoIndex.scan(options.photo_dir))
    assert match == Match(Photo(photo, datetime(2020, 4, 12, 15, 30, 20)), 19.0)
    planned, = job.plan_jobs(clip, options, info, match.photo.path)
    assert planned.target == tmp_path / "photos" / "DSC0042_clip.mp4"


def test_example_files(testdata, ffmpeg, computer_timezone):
    """The clip of a Sony ILCE-6300 and a photo taken 19 seconds after its start"""
    computer_timezone("America/New_York")
    clip = testdata / "C0031.MP4"
    info = probe(clip)
    assert (info.width, info.height, info.duration) == (1920, 1080, 2.4)
    assert info.created == datetime(2026, 10, 6, 19, 38, 22, tzinfo=timezone.utc)

    capture = video_capture_time(clip, info)
    assert capture == CaptureTime(datetime(2026, 10, 6, 21, 38, 22), "+02:00")
    assert capture.start(info.duration) == info.created

    index = PhotoIndex.scan(testdata)
    assert index.photos == [Photo(testdata / "DSC02287.JPG", datetime(2026, 10, 6, 21, 38, 41))]
    match = job.find_photo(capture, info, ConversionOptions(), index)
    assert match.distance == pytest.approx(16.6)


def test_example_xml_file_agrees_with_the_clip(testdata, tmp_path):
    created = datetime(2026, 10, 6, 19, 38, 22, tzinfo=timezone.utc)
    assert camera_creation_time(testdata / "C0031.MP4") == created
    assert metadata.camera_device(testdata / "C0031.MP4") == ("Sony", "ILCE-6300")
    assert metadata.camera_device(testdata / "DSC02287.JPG") is None
    # the XML file alone, next to a video without embedded metadata
    shutil.copy(testdata / "C0031M01.XML", tmp_path)
    (tmp_path / "C0031.MP4").write_bytes(bytes(64))
    assert camera_creation_time(tmp_path / "C0031.MP4") == created
    assert camera_creation_time(tmp_path / "C0031.MP4").utcoffset() == parse_offset("+02:00")


def test_missing_exifread_is_explained(make_photo, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "exifread", None)
    make_photo(tmp_path / "a.jpg", original="2020:04:12 15:30:00")
    with pytest.raises(ToolError, match="python3-exifread"):
        PhotoIndex.scan(tmp_path)
