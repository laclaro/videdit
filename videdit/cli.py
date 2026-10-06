"""Command line interface of videdit."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import shlex
import subprocess
import sys

from . import __version__
from .core import dependencies, job, settings
from .core.errors import OptionsError, VideditError
from .core.matching import PhotoIndex
from .core.options import (FLIPS, PER_FILE_FIELDS, PRESETS, ROTATIONS, ConversionOptions,
                           CropRect, parse_time)
from .core.settings import Settings

# arguments which are not conversion options
RUN_ARGUMENTS = ("files", "dry_run", "verbose", "defaults")


def _checked(function):
    """Let argparse report the OptionsError of a parse function as usage error"""
    def parse(text):
        try:
            return function(text)
        except OptionsError as error:
            raise argparse.ArgumentTypeError(str(error)) from None
    parse.__name__ = function.__name__
    return parse


def build_parser():
    """Construct the argument parser, options which are not given stay unset"""
    parser = argparse.ArgumentParser(
        prog="videdit", argument_default=argparse.SUPPRESS,
        description="Convert camera videos to mp4 with ffmpeg. Videos can be cut, cropped, "
                    "scaled, rotated and placed next to the photo taken at the same time.",
        epilog="Options which are not given take the value last used in the graphical "
               "interface, see --defaults.")
    parser.add_argument("files", nargs="+", metavar="FILE", help="Input video file")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Do not convert, only print the ffmpeg commands")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Overwrite existing files")
    parser.add_argument("-o", "--output-dir", metavar="DIR",
                        help="Directory for the converted videos. Default: next to the input")
    parser.add_argument("--defaults", action="store_true",
                        help="Ignore the saved options and start from the defaults")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print more information")
    parser.add_argument("-V", "--version", action="version", version="%(prog)s " + __version__)

    group = parser.add_argument_group("Quality")
    group.add_argument("--preset", choices=sorted(PRESETS),
                       help="quick: fast and small with reduced quality. Default: default")
    group.add_argument("--crf", type=int, metavar="N",
                       help="Quality of the video from 0 (best) to 51, overrides the preset")

    group = parser.add_argument_group("Cut")
    group.add_argument("--start", type=_checked(parse_time), metavar="TIME",
                       help="Start time in seconds or as hh:mm:ss. Default: video beginning")
    group.add_argument("--end", type=_checked(parse_time), metavar="TIME",
                       help="End time in seconds or as hh:mm:ss. Default: video end")

    group = parser.add_argument_group("Fade")
    group.add_argument("--fade", type=float, metavar="SEC",
                       help="Time to fade in and fade out. Default: 0.3")
    group.add_argument("--fade-black", type=float, metavar="SEC",
                       help="Black time before the fade in and after the fade out. Default: 0.1")
    group.add_argument("--no-fade", dest="fade", action="store_const", const=0.0,
                       help="Do not fade")

    group = parser.add_argument_group("Picture")
    group.add_argument("--scale", dest="scales", action="append", metavar="VALUE",
                       help="Output size, either in percent (50%%) or as length of the short "
                            "edge (720). Can be given several times, each yields a file")
    group.add_argument("--no-scale", dest="scales", action="store_const", const=[],
                       help="Keep the size of the picture")
    group.add_argument("--rotate", type=int, choices=ROTATIONS, help="Rotate clockwise")
    group.add_argument("--flip", choices=FLIPS, help="Flip horizontally or vertically")
    group.add_argument("--crop", type=_checked(CropRect.parse), metavar="W:H:X:Y",
                       help="Crop to width W and height H with the top left corner at X, Y. "
                            "Refers to the rotated picture")
    group.add_argument("--crop-aspect", metavar="A:B",
                       help="Crop the centre of the picture to an aspect ratio like 16:9")

    group = parser.add_argument_group("Related photo")
    group.add_argument("--photo-dir", metavar="DIR",
                       help="Search this directory for the photo taken closest to the video")
    group.add_argument("--photo-tolerance", type=float, metavar="SEC",
                       help="Time window in which a photo is treated as related to the "
                            "video. Default: 300")
    group.add_argument("--rename", action=argparse.BooleanOptionalAction,
                       help="Place the video next to the related photo, with the name of "
                            "the photo as prefix")
    group.add_argument("--show-photo", action=argparse.BooleanOptionalAction,
                       help="Open the related photo in the image viewer")
    group.add_argument("--time-offset", metavar="+HH:MM",
                       help="UTC offset of the camera clock, if the one stored in the video "
                            "is wrong. Write negative offsets as --time-offset=-05:00")
    return parser


def options_from_args(given, saved):
    """Return the saved options overridden by the given command line arguments"""
    values = {name: value for name, value in given.items() if name not in RUN_ARGUMENTS}
    if "scales" in values:
        values["scales"] = tuple(values["scales"])
    options = dataclasses.replace(saved, **values)
    options.validate()
    return options


def saved_options_in_use(given, saved):
    """Describe the saved options which differ from the defaults and are not overridden"""
    defaults = ConversionOptions()
    return ["{}={}".format(field.name, getattr(saved, field.name))
            for field in dataclasses.fields(saved)
            if field.name not in given and field.name not in PER_FILE_FIELDS
            and getattr(saved, field.name) != getattr(defaults, field.name)]


def info(message):
    print(message, file=sys.stderr)


def show_progress(fraction):
    """Print the progress of a conversion if somebody is watching"""
    if sys.stderr.isatty():
        end = "\n" if fraction >= 1.0 else ""
        print("\r  {:3.0f}%".format(fraction * 100), end=end, file=sys.stderr, flush=True)


def open_file(path):
    """Show a file with the application the desktop uses for it"""
    try:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError as error:
        info("Warning: {} could not be opened: {}".format(path, error))


def report_photo(prepared, options):
    """Tell which photo is related to the video"""
    if prepared.match is not None:
        photo = prepared.match.photo.path
        info("Related photo, {:.0f}s apart: {}".format(prepared.match.distance, photo))
        if not options.rename:
            info("Tip: --rename places the video next to it.")
        if options.show_photo:
            open_file(photo)
    elif prepared.closest is not None:
        info("No related photo found. The closest one, {:.0f}s apart, is {}".format(
            prepared.closest.distance, prepared.closest.photo.path))
    else:
        info("No photos with capture time found in {}".format(options.photo_dir))


def convert_file(path, options, tools, index, dry_run):
    """Convert one video file according to the options"""
    if not os.path.isfile(path):
        raise VideditError("No such file")
    prepared = job.prepare(path, options, tools, index)
    if index is not None:
        report_photo(prepared, options)
    for planned in prepared.jobs:
        if dry_run:
            print(shlex.join(planned.command))
            continue
        info("Converting {} -> {}".format(planned.source, planned.target))
        job.run_job(planned, options, on_progress=show_progress)


def main(argv=None):
    """Run the command line interface and return the exit status"""
    parser = build_parser()
    given = vars(parser.parse_args(argv))
    verbose = given.get("verbose", False)
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")

    saved = Settings() if given.get("defaults") else settings.load()
    try:
        options = options_from_args(given, saved.options)
    except OptionsError as error:
        parser.error(str(error))
    in_use = saved_options_in_use(given, saved.options)
    if in_use:
        info("Using saved options: " + ", ".join(in_use))

    tools = saved.tools
    fatal = [problem.message for problem in dependencies.check(tools) if problem.fatal]
    if fatal:
        info("Error: " + "\nError: ".join(fatal))
        return 2

    index = None
    if options.photo_dir:
        if not os.path.isdir(options.photo_dir):
            parser.error("No such directory '{}'".format(options.photo_dir))
        try:
            index = PhotoIndex.scan(options.photo_dir)
        except VideditError as error:
            info("Error: {}".format(error))
            return 2

    dry_run = given.get("dry_run", False)
    failed = False
    for path in given["files"]:
        try:
            convert_file(path, options, tools, index, dry_run)
        except VideditError as error:
            info("Error: {}: {}".format(path, error))
            failed = True
        except KeyboardInterrupt:
            info("\nAborted.")
            return 130
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
