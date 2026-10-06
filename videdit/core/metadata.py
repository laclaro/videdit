"""
Determine capture times and the metadata to write into the converted video.

The exif data of photos is read with the exifread module, the creation time
of videos comes from ffprobe (see probe.py) and ffmpeg writes the metadata of
the result, so no further program is needed.

Photos carry no time zone, so times are compared as wall clock time of the
camera. Videos store their creation time in UTC. Sony cameras additionally
embed the local time with its UTC offset, which is preferred. Otherwise the
creation time is converted with the time zone of this computer.
"""

from __future__ import annotations

import logging
import os
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .errors import ToolError

log = logging.getLogger(__name__)

# exif tags which tell when a photo was taken, the most reliable first
PHOTO_TIME_TAGS = ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized")
# metadata keys of the converted video, they are understood by most photo
# collections: the capture time with UTC offset and the camera
CREATION_DATE_KEY = "com.apple.quicktime.creationdate"
MAKE_KEY = "com.apple.quicktime.make"
MODEL_KEY = "com.apple.quicktime.model"

_DATETIME = re.compile(r"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})")
_CREATION_DATE = re.compile(rb'<CreationDate\s+value="([^"]+)"')
_DEVICE = re.compile(rb'<Device\s+manufacturer="([^"]*)"\s+modelName="([^"]*)"')
# the metadata box of a camera is small, anything bigger is not read
_MAX_META_SIZE = 1 << 20


def parse_offset(text):
    """Convert an UTC offset like +02:00 to a timedelta"""
    sign = -1 if text[0] == "-" else 1
    return sign * timedelta(hours=int(text[1:3]), minutes=int(text[4:6]))


def format_offset(delta):
    """Format a timedelta as UTC offset like +02:00"""
    minutes = round(delta.total_seconds() / 60)
    return "{}{:02d}:{:02d}".format("-" if minutes < 0 else "+", *divmod(abs(minutes), 60))


@dataclass(frozen=True)
class CaptureTime:
    """Time a video was shot as wall clock time of the camera and its UTC offset."""
    wall: datetime
    offset: str
    # True if the time marks the end of the recording rather than its start
    at_end: bool = False

    def start(self, duration):
        """Return the moment the recording of the given duration started, with time zone"""
        wall = self.wall - timedelta(seconds=duration) if self.at_end else self.wall
        return wall.replace(tzinfo=timezone(parse_offset(self.offset)))


def parse_exif_datetime(text):
    """Convert an exif date like '2020:04:12 15:30:00', returns None for invalid dates"""
    match = _DATETIME.match(str(text).strip())
    if match is None:
        return None
    try:
        return datetime(*(int(group) for group in match.groups()))
    except ValueError:
        return None


def photo_capture_time(path):
    """Read the time a photo was taken from its exif data, None if it has none"""
    try:
        import exifread
    except ImportError:
        raise ToolError("The Python module exifread is needed to read photos, e.g. from "
                        "the package python3-exifread or with: pip install exifread") from None
    try:
        with open(path, "rb") as file:
            tags = exifread.process_file(file, details=False)
    except Exception as error:
        log.warning("%s is not readable: %s", path, error)
        return None
    for tag in PHOTO_TIME_TAGS:
        taken = parse_exif_datetime(tags.get(tag, ""))
        if taken is not None:
            return taken
    return None


def _top_level_boxes(file):
    """Yield type, position and size of the content of the top level boxes of an MP4 file"""
    position = 0
    while True:
        file.seek(position)
        header = file.read(16)
        if len(header) < 16:
            return
        size, kind = struct.unpack(">I4s", header[:8])
        head = 8
        if size == 1:
            size, head = struct.unpack(">Q", header[8:])[0], 16
        if size < head:
            return
        yield kind, position + head, size - head
        position += size


def _creation_date(xml):
    """Get the CreationDate of the metadata of a Sony camera, None without UTC offset"""
    match = _CREATION_DATE.search(xml)
    if match is None:
        return None
    try:
        created = datetime.fromisoformat(match.group(1).decode("ascii"))
    except ValueError:
        return None
    return created if created.tzinfo is not None else None


def _embedded_xml(path):
    """Read the metadata box of an MP4 file"""
    with open(path, "rb") as file:
        for kind, position, size in _top_level_boxes(file):
            if kind == b"meta" and size <= _MAX_META_SIZE:
                file.seek(position)
                return file.read(size)
    return b""


def _sidecar_xml(path):
    """Read the file C0001M01.XML next to the video C0001.MP4"""
    path = Path(path)
    for suffix in ("M01.XML", "M01.xml"):
        sidecar = path.with_name(path.stem + suffix)
        if sidecar.is_file():
            with open(sidecar, "rb") as file:
                return file.read(_MAX_META_SIZE)
    return b""


def camera_xml(path):
    """
    Return the metadata Sony cameras write for a video. It is embedded in the
    MP4 file and also stored in an XML file next to it. Empty for videos
    having neither.
    """
    try:
        for read in (_embedded_xml, _sidecar_xml):
            xml = read(path)
            if _CREATION_DATE.search(xml):
                return xml
    except OSError:
        pass
    return b""


def camera_creation_time(path):
    """
    Read the start of the recording including the UTC offset of the camera
    from the metadata of Sony cameras, None for other videos.
    """
    return _creation_date(camera_xml(path))


def camera_device(path):
    """Read manufacturer and model from the metadata of Sony cameras, None for other videos"""
    match = _DEVICE.search(camera_xml(path))
    if match is None:
        return None
    return tuple(group.decode("utf-8", "replace") for group in match.groups())


def video_capture_time(path, info, time_offset=None):
    """
    Determine when a video was shot. The local time stored by the camera is
    used if there is one, then the creation time in UTC. Other videos fall
    back to the modification time of the file, which marks the end of the
    recording. time_offset overrides the UTC offset of the camera.
    """
    camera = camera_creation_time(path) or info.local_created
    moment, at_end = camera or info.created, False
    if moment is None:
        moment, at_end = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc), True
        log.info("Using the modification time of %s, it has no creation time.", path)
    if time_offset is not None:
        local = moment.astimezone(timezone(parse_offset(time_offset)))
    elif camera is not None:
        local = moment
    else:
        local = moment.astimezone()
    return CaptureTime(local.replace(tzinfo=None), format_offset(local.utcoffset()), at_end)


def output_tags(created, device=None):
    """
    Return the metadata of a converted video: created is the moment its
    first frame was shot with the time zone of the camera, device the
    manufacturer and model of the camera.
    """
    tags = {"creation_time": created.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            CREATION_DATE_KEY: created.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if device is not None:
        tags[MAKE_KEY], tags[MODEL_KEY] = device
    return tags
