"""Exceptions raised by the core package."""


class VideditError(Exception):
    """Base class of all errors the front ends are expected to report."""


class OptionsError(VideditError):
    """The conversion options are invalid or do not fit the video."""


class ToolError(VideditError):
    """An external tool (ffmpeg, ffprobe) is missing or failed."""


class ConversionError(VideditError):
    """ffmpeg failed or the output file could not be written."""


class Cancelled(VideditError):
    """The conversion was cancelled by the user."""
