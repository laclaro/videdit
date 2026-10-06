"""Read the technical properties of a video file with ffprobe."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from . import process
from .errors import ToolError


@dataclass(frozen=True)
class VideoInfo:
    """Properties of a video file needed to plan a conversion."""
    width: int
    height: int
    duration: float
    rotation: int = 0
    has_audio: bool = True
    # creation time stored in the file (UTC), None if absent
    created: datetime | None = None
    # the same as local time of the camera with its UTC offset, if stored
    local_created: datetime | None = None

    @property
    def display_size(self):
        """Width and height as displayed, i.e. after applying the rotation flag."""
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height


def _rotation(stream):
    """Get the rotation flag of a video stream in degrees (0, 90, 180, 270)"""
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            return int(side_data["rotation"]) % 360
    return int(stream.get("tags", {}).get("rotate", 0)) % 360


def _created(data):
    """Get the creation time of the recording as stored in the container"""
    text = data.get("format", {}).get("tags", {}).get("creation_time")
    try:
        created = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created


def _local_created(data):
    """Get the creation time with the UTC offset of the camera, as written by phones and videdit"""
    text = data.get("format", {}).get("tags", {}).get("com.apple.quicktime.creationdate")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None


def parse_probe(data):
    """Construct the VideoInfo from the parsed JSON output of ffprobe"""
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ToolError("No video stream found")
    duration = data.get("format", {}).get("duration", video.get("duration"))
    if duration is None:
        raise ToolError("The video duration is unknown")
    return VideoInfo(width=int(video["width"]),
                     height=int(video["height"]),
                     duration=float(duration),
                     rotation=_rotation(video),
                     has_audio=any(s.get("codec_type") == "audio" for s in streams),
                     created=_created(data),
                     local_created=_local_created(data))


def probe(path, ffprobe="ffprobe"):
    """Use ffprobe to determine size, duration, rotation and creation time of a video"""
    result = process.run_tool([ffprobe, "-v", "error", "-print_format", "json",
                               "-show_format", "-show_streams", path])
    return parse_probe(json.loads(result.stdout))
