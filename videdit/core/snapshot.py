"""Extract a still image of a video, e.g. to select the crop area on it."""

from __future__ import annotations

from . import process
from .filters import _seconds, transpose_filters


def snapshot_time(duration, wanted=10.0):
    """Return the position of the snapshot, short videos use their middle"""
    return min(wanted, duration / 2)


def snapshot_command(source, target, position, options, ffmpeg="ffmpeg"):
    """
    Return the ffmpeg command writing one frame to target. The frame is
    rotated and flipped like the converted video, so that a crop rectangle
    selected on it fits.
    """
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-ss", _seconds(position), "-i", str(source), "-frames:v", "1"]
    filters = transpose_filters(options)
    if filters:
        command += ["-filter:v", ",".join(filters)]
    return command + ["-update", "1", str(target)]


def take_snapshot(source, target, info, options, position=None, ffmpeg="ffmpeg"):
    """Write a snapshot image of the video and return its position in seconds"""
    if position is None:
        position = snapshot_time(info.duration)
    process.run_tool(snapshot_command(source, target, position, options, ffmpeg))
    return position
