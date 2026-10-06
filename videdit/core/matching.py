"""Find the photo which was taken closest to a video."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import metadata

log = logging.getLogger(__name__)

# raw files are left out on purpose, they have a developed sibling
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".png", ".webp"}


@dataclass(frozen=True)
class Photo:
    path: Path
    taken: datetime


@dataclass(frozen=True)
class Match:
    """A photo and its distance in seconds to the recording time of a video."""
    photo: Photo
    distance: float


def video_interval(capture, duration):
    """Return the wall clock times at which the recording started and ended"""
    start = capture.start(duration).replace(tzinfo=None)
    return start, start + timedelta(seconds=duration)


class PhotoIndex:
    """Capture times of the photos of a directory, scanned only once."""

    def __init__(self, photos):
        self.photos = sorted(photos, key=lambda photo: photo.taken)

    @classmethod
    def scan(cls, directory):
        """Collect the photos below the given directory with their exif capture time"""
        photos = []
        for folder, _, names in os.walk(directory):
            for name in sorted(names):
                path = Path(folder) / name
                if path.suffix.lower() not in PHOTO_SUFFIXES:
                    continue
                taken = metadata.photo_capture_time(path)
                if taken is None:
                    log.warning("%s skipped, it has no capture time.", path)
                    continue
                photos.append(Photo(path, taken))
        return cls(photos)

    def closest(self, start, end):
        """
        Return the photo closest to the recording. Photos taken while
        recording have the distance 0. None if there are no photos.
        """
        best = None
        for photo in self.photos:
            if photo.taken < start:
                distance = (start - photo.taken).total_seconds()
            else:
                distance = max(0.0, (photo.taken - end).total_seconds())
            if best is None or distance < best.distance:
                best = Match(photo, distance)
        return best

    def match(self, start, end, tolerance):
        """Return the closest photo if it lies within the tolerance in seconds"""
        best = self.closest(start, end)
        if best is None or best.distance > tolerance:
            return None
        return best
