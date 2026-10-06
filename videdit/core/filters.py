"""
Translate conversion options into ffmpeg arguments. Nothing in this module
runs a program, so the result can be printed (dry run) or tested as is.

The filters are always applied in the order rotate/flip, crop, scale, fade.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import OptionsError
from .options import PRESETS, CropRect, parse_aspect

_ROTATE = {90: ["transpose=1"], -90: ["transpose=2"], 180: ["hflip", "vflip"]}
_FLIP = {"h": ["hflip"], "v": ["vflip"]}


def _even(value):
    """Round down to an even number, h264 needs even picture dimensions"""
    return int(value) // 2 * 2


def _seconds(value):
    """Format seconds for ffmpeg without trailing zeros"""
    return "{:.3f}".format(value).rstrip("0").rstrip(".")


@dataclass(frozen=True)
class FilterPlan:
    """Filters and resulting geometry of one output file."""
    video: tuple
    audio: tuple
    width: int
    height: int
    start: float
    duration: float


def transpose_filters(options):
    """Construct the rotate and flip filters"""
    return _ROTATE.get(options.rotate, []) + _FLIP.get(options.flip, [])


def crop_rect(options, width, height):
    """
    Return the crop rectangle for a picture of the given size or None if
    nothing is cut off. An aspect ratio yields the largest centred rectangle.
    """
    if options.crop is not None:
        rect = CropRect(_even(options.crop.width), _even(options.crop.height),
                        _even(options.crop.x), _even(options.crop.y))
        if rect.x + rect.width > width or rect.y + rect.height > height:
            raise OptionsError("The crop rectangle exceeds the picture size "
                               "{}x{}".format(width, height))
    elif options.crop_aspect is not None:
        aspect = parse_aspect(options.crop_aspect)
        if width / height > aspect:
            crop_width, crop_height = _even(height * aspect), _even(height)
        else:
            crop_width, crop_height = _even(width), _even(width / aspect)
        rect = CropRect(crop_width, crop_height,
                        _even((width - crop_width) / 2), _even((height - crop_height) / 2))
    else:
        return None
    if (rect.width, rect.height) == (width, height):
        return None
    return rect


def scaled_size(scale, width, height):
    """Return the picture size after scaling"""
    if scale.relative:
        factor = scale.value / 100
    else:
        factor = scale.value / min(width, height)
    return max(2, _even(round(width * factor))), max(2, _even(round(height * factor)))


def clip_range(options, duration):
    """Return start and end of the part to convert in seconds"""
    start = options.start or 0.0
    end = duration if options.end is None else min(options.end, duration)
    if start >= end:
        raise OptionsError("The start time {}s is not before the end of the "
                           "clip at {}s".format(_seconds(start), _seconds(end)))
    return start, end


def fade_filters(options, clip_duration):
    """
    Construct fade filter:v and filter:a. The fade is shortened if the clip
    is too short and omitted if no time is left for it.
    """
    black = options.fade_black
    fade = min(options.fade, clip_duration / 2 - black)
    if options.fade <= 0 or fade <= 0:
        return [], []
    st_in, st_out, d = (_seconds(black), _seconds(clip_duration - black - fade),
                        _seconds(fade))
    return (["{0}=t=in:st={1}:d={3},{0}=t=out:st={2}:d={3}".format(name, st_in, st_out, d)]
            for name in ("fade", "afade"))


def plan_filters(options, info, scale=None):
    """Compose the filter chains for one output file"""
    width, height = info.display_size
    video = transpose_filters(options)
    if options.rotate in (90, -90):
        width, height = height, width

    rect = crop_rect(options, width, height)
    if rect is not None:
        video.append("crop={}:{}:{}:{}".format(rect.width, rect.height, rect.x, rect.y))
        width, height = rect.width, rect.height

    if scale is not None:
        width, height = scaled_size(scale, width, height)
        video.append("scale={}:{}".format(width, height))

    start, end = clip_range(options, info.duration)
    fade_v, fade_a = fade_filters(options, end - start)
    audio = fade_a if info.has_audio else []
    return FilterPlan(tuple(video + fade_v), tuple(audio), width, height, start, end - start)


def build_command(source, target, options, info, scale=None, ffmpeg="ffmpeg", tags=None):
    """
    Return the complete ffmpeg command for one output file. tags are metadata
    to write in addition to those copied from the source.
    """
    plan = plan_filters(options, info, scale)
    preset = PRESETS[options.preset]
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]

    # seeking in front of -i lets the timestamps seen by the filters start at zero
    if options.start:
        command += ["-ss", _seconds(plan.start)]
    if options.cuts:
        command += ["-t", _seconds(plan.duration)]
    command += ["-i", str(source), "-map_metadata", "0", "-movflags",
                "use_metadata_tags" + ("+faststart" if preset.faststart else "")]
    for key, value in (tags or {}).items():
        command += ["-metadata", "{}={}".format(key, value)]

    if plan.video:
        command += ["-filter:v", ",".join(plan.video)]
    if plan.audio:
        command += ["-filter:a", ",".join(plan.audio)]

    crf = preset.crf if options.crf is None else options.crf
    command += ["-c:v", "libx264", "-crf", str(crf), "-c:a", "aac"]
    if preset.audio_bitrate:
        command += ["-b:a", preset.audio_bitrate]
    return command + [str(target)]
