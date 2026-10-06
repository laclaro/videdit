"""Plan and run the conversions of one video file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from . import metadata, runner
from .errors import ConversionError
from .filters import build_command, plan_filters
from .matching import video_interval
from .naming import output_path
from .probe import probe
from .settings import ToolPaths


@dataclass(frozen=True)
class Job:
    """One output file to create, a video yields one job per requested scale."""
    source: Path
    target: Path
    command: list = field(compare=False)
    duration: float = 0.0
    # moment the first frame of the result was shot, becomes its file time
    created: Any = None


@dataclass(frozen=True)
class Prepared:
    """Everything known about a video before its conversion starts."""
    info: Any
    capture: Any
    # the photo closest to the video and the same if it is within the tolerance
    closest: Any
    match: Any
    jobs: list


def find_photo(capture, info, options, index):
    """Return the Match of the photo related to the video, None if there is none"""
    start, end = video_interval(capture, info.duration)
    return index.match(start, end, options.photo_tolerance)


def plan_jobs(source, options, info, photo=None, tools=None, capture=None):
    """
    Return the jobs for a video file. photo is the path of the related photo
    used by the rename option. With the CaptureTime of the video its capture
    time and camera are written into the results. Nothing is executed, so
    this serves a dry run.
    """
    options.validate()
    tools = tools or ToolPaths()
    created = tags = None
    if capture is not None:
        created = capture.start(info.duration) + timedelta(seconds=options.start or 0.0)
        tags = metadata.output_tags(created, metadata.camera_device(source))
    jobs = []
    for scale in options.parsed_scales():
        target = output_path(source, options, scale, photo)
        command = build_command(source, target, options, info, scale, tools.ffmpeg, tags)
        duration = plan_filters(options, info, scale).duration
        jobs.append(Job(Path(source), target, command, duration, created))
    return jobs


def prepare(source, options, tools=None, index=None):
    """
    Examine a video file and plan its conversion. index is the PhotoIndex of
    the photo directory, without it no related photo is searched.
    """
    options.validate()
    tools = tools or ToolPaths()
    info = probe(source, tools.ffprobe)
    capture = metadata.video_capture_time(source, info, options.time_offset)
    closest = match = None
    if index is not None:
        closest = index.closest(*video_interval(capture, info.duration))
        if closest is not None and closest.distance <= options.photo_tolerance:
            match = closest
    jobs = plan_jobs(source, options, info, match.photo.path if match else None, tools,
                     capture)
    return Prepared(info, capture, closest, match, jobs)


def run_job(job, options, on_progress=None, cancel_event=None):
    """Convert the video and give the result the time the video was shot"""
    if job.target.exists() and not options.force:
        raise ConversionError("{} exists already. Use force to overwrite it.".format(job.target))
    job.target.parent.mkdir(parents=True, exist_ok=True)
    runner.run_ffmpeg(job.command, job.target, job.duration, on_progress, cancel_event)
    if job.created is not None:
        os.utime(job.target, (job.created.timestamp(), job.created.timestamp()))
