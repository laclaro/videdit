"""Run ffmpeg with progress reporting and cancellation."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .errors import Cancelled, ConversionError, ToolError


def parse_progress_line(line):
    """
    Get the position in seconds from a line of the ffmpeg -progress output,
    None if the line does not carry a position.
    """
    key, _, value = line.strip().partition("=")
    # out_time_ms is in microseconds, too (a long standing ffmpeg quirk)
    if key in ("out_time_us", "out_time_ms"):
        try:
            return max(0.0, int(value) / 1e6)
        except ValueError:
            return None
    return None


def run_ffmpeg(command, target, duration, on_progress=None, cancel_event=None):
    """
    Execute an ffmpeg command built by filters.build_command. on_progress is
    called with a fraction between 0 and 1. Setting the threading.Event
    cancel_event stops ffmpeg. An incomplete target file is removed.
    """
    command = [str(part) for part in command]
    command[1:1] = ["-progress", "pipe:1", "-nostats"]
    with tempfile.TemporaryFile(mode="w+") as errors:
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                    stdin=subprocess.DEVNULL, text=True)
        except FileNotFoundError:
            raise ToolError("'{}' was not found. Is it installed?".format(command[0])) from None

        cancelled = False
        try:
            for line in proc.stdout:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                position = parse_progress_line(line)
                if position is not None and on_progress is not None and duration > 0:
                    on_progress(min(1.0, position / duration))
        except BaseException:
            proc.kill()
            proc.wait()
            Path(target).unlink(missing_ok=True)
            raise
        finally:
            proc.stdout.close()
        if cancelled:
            proc.terminate()
        returncode = proc.wait()

        if cancelled:
            Path(target).unlink(missing_ok=True)
            raise Cancelled("Conversion of {} cancelled".format(target))
        if returncode != 0:
            Path(target).unlink(missing_ok=True)
            errors.seek(0)
            raise ConversionError("ffmpeg failed: {}".format(errors.read().strip()))
    if on_progress is not None:
        on_progress(1.0)
