"""Check that the programs and modules videdit relies on are installed."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass


@dataclass(frozen=True)
class Problem:
    """A missing dependency, fatal ones prevent any conversion."""
    message: str
    fatal: bool


def check(tools):
    """Return the problems with the dependencies, an empty list if all are met"""
    problems = []
    for name in tools.missing():
        problems.append(Problem(
            "{} was not found, videos cannot be converted. It is part of the package "
            "ffmpeg.".format(getattr(tools, name)), fatal=True))
    if importlib.util.find_spec("exifread") is None:
        problems.append(Problem(
            "The Python module exifread was not found, related photos cannot be searched. "
            "It is part of the package python3-exifread.", fatal=False))
    return problems
