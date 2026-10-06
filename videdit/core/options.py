"""Conversion options shared by the command line and the graphical interface."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, fields

from .errors import OptionsError

ROTATIONS = (90, -90, 180)
FLIPS = ("h", "v")
# options which describe one particular video or run and are not remembered
PER_FILE_FIELDS = ("start", "end", "crop", "force")

_TIME_OFFSET = re.compile(r"[+-]\d{2}:\d{2}")


@dataclass(frozen=True)
class Preset:
    """Encoder settings of a quality preset."""
    crf: int
    audio_bitrate: str | None
    faststart: bool


PRESETS = {"default": Preset(crf=19, audio_bitrate=None, faststart=False),
           "quick": Preset(crf=30, audio_bitrate="96k", faststart=True)}


def parse_time(value):
    """Get seconds from a number of seconds or a time string [hh:]mm:ss"""
    parts = str(value).strip().split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise OptionsError("Invalid time '{}'".format(value)) from None
    if len(numbers) > 3 or any(not math.isfinite(n) or n < 0 for n in numbers):
        raise OptionsError("Invalid time '{}'".format(value))
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def format_time(seconds):
    """Construct the time string hh:mm:ss from seconds"""
    minutes, seconds = divmod(round(seconds, 3), 60)
    hours, minutes = divmod(int(minutes), 60)
    text = "{:02d}:{:02d}:{:06.3f}".format(hours, minutes, seconds)
    return text.rstrip("0").rstrip(".") if "." in text else text


def parse_aspect(text):
    """Get the ratio width/height from an aspect string like 16:9"""
    try:
        width, height = (float(part) for part in str(text).split(":"))
    except ValueError:
        raise OptionsError("Invalid aspect ratio '{}', expected e.g. 16:9".format(text)) from None
    if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
        raise OptionsError("Invalid aspect ratio '{}'".format(text))
    return width / height


@dataclass(frozen=True)
class CropRect:
    """Crop rectangle in pixels of the rotated/flipped video."""
    width: int
    height: int
    x: int = 0
    y: int = 0

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0 or self.x < 0 or self.y < 0:
            raise OptionsError("Invalid crop rectangle {}:{}:{}:{}".format(
                self.width, self.height, self.x, self.y))

    @classmethod
    def parse(cls, text):
        """Construct the rectangle from a string W:H:X:Y"""
        try:
            width, height, x, y = (int(part) for part in str(text).split(":"))
        except ValueError:
            raise OptionsError("Invalid crop '{}', expected W:H:X:Y".format(text)) from None
        return cls(width, height, x, y)


@dataclass(frozen=True)
class Scale:
    """Output size, either relative in percent or as length of the short edge."""
    value: float
    relative: bool

    @classmethod
    def parse(cls, text):
        """Construct from a string like 50% (relative) or 720 (short edge in pixels)"""
        text = str(text).strip()
        relative = text.endswith("%")
        try:
            value = float(text.rstrip("%"))
        except ValueError:
            raise OptionsError("Invalid scale '{}', expected e.g. 50% or 720".format(text)) from None
        if not math.isfinite(value) or value <= 0:
            raise OptionsError("Invalid scale '{}'".format(text))
        return cls(value, relative)

    @property
    def label(self):
        """Short name used in output file names."""
        return "{:g}{}".format(self.value, "pct" if self.relative else "p")


@dataclass
class ConversionOptions:
    """Everything the user can choose for a conversion."""
    preset: str = "default"
    crf: int | None = None
    start: float | None = None
    end: float | None = None
    fade: float = 0.3
    fade_black: float = 0.1
    scales: tuple = ()
    rotate: int | None = None
    flip: str | None = None
    crop: CropRect | None = None
    crop_aspect: str | None = None
    photo_dir: str | None = None
    photo_tolerance: float = 300.0
    rename: bool = False
    show_photo: bool = False
    output_dir: str | None = None
    time_offset: str | None = None
    force: bool = False

    def validate(self):
        """Raise OptionsError if the options are inconsistent."""
        if self.preset not in PRESETS:
            raise OptionsError("Unknown preset '{}'".format(self.preset))
        if self.crf is not None and not 0 <= self.crf <= 51:
            raise OptionsError("crf must be between 0 and 51")
        for name in ("start", "end"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise OptionsError("{} must not be negative".format(name))
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise OptionsError("start must be before end")
        if self.fade < 0 or self.fade_black < 0:
            raise OptionsError("Fade times must not be negative")
        if self.rotate is not None and self.rotate not in ROTATIONS:
            raise OptionsError("rotate must be one of {}".format(ROTATIONS))
        if self.flip is not None and self.flip not in FLIPS:
            raise OptionsError("flip must be one of {}".format(FLIPS))
        if self.crop_aspect is not None:
            parse_aspect(self.crop_aspect)
        if self.photo_tolerance < 0:
            raise OptionsError("The photo tolerance must not be negative")
        if self.rename and not self.photo_dir:
            raise OptionsError("rename needs a photo directory")
        if self.time_offset is not None and not _TIME_OFFSET.fullmatch(self.time_offset):
            raise OptionsError("Invalid time offset '{}', expected e.g. +02:00".format(
                self.time_offset))
        self.parsed_scales()

    def parsed_scales(self):
        """Return the requested scales without duplicates, [None] means original size."""
        scales = []
        for text in self.scales:
            scale = Scale.parse(text)
            if scale not in scales:
                scales.append(scale)
        return scales or [None]

    @property
    def cuts(self):
        """True if only a part of the video is converted."""
        return self.start is not None or self.end is not None

    @property
    def crops(self):
        """True if the video is cropped."""
        return self.crop is not None or self.crop_aspect is not None

    def to_dict(self, sticky_only=False):
        """Return a JSON compatible dictionary, optionally without per-file options."""
        data = asdict(self)
        data["scales"] = list(self.scales)
        if sticky_only:
            for name in PER_FILE_FIELDS:
                del data[name]
        return data

    @classmethod
    def from_dict(cls, data):
        """Construct validated options from a dictionary, unknown keys are ignored."""
        known = {field.name for field in fields(cls)}
        values = {key: value for key, value in data.items() if key in known}
        try:
            if values.get("crop") is not None:
                values["crop"] = CropRect(**values["crop"])
            if "scales" in values:
                values["scales"] = tuple(values["scales"])
            options = cls(**values)
            options.validate()
        except TypeError as error:
            raise OptionsError("Invalid options: {}".format(error)) from None
        return options
