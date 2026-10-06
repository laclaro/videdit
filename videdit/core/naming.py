"""Rules for the names of the converted files."""

from __future__ import annotations

from pathlib import Path


def suffix(options, scale=None):
    """Construct the part of the file name which tells what was done to the video"""
    parts = []
    if options.cuts:
        parts.append("cut")
    if options.crops:
        parts.append("crop")
    if options.rotate is not None:
        parts.append("rot{}".format(options.rotate))
    if options.flip is not None:
        parts.append("flip{}".format(options.flip))
    if options.preset != "default":
        parts.append(options.preset)
    if scale is not None:
        parts.append(scale.label)
    return "".join("_" + part for part in parts)


def output_path(source, options, scale=None, photo=None):
    """
    Return the path of the converted file. With the rename option and a
    related photo the video is placed next to the photo and carries its name
    as prefix, otherwise it goes to the output directory or next to the source.
    """
    source = Path(source)
    name = source.stem + suffix(options, scale)
    if options.rename and photo is not None:
        photo = Path(photo)
        directory = photo.parent
        name = photo.stem + "_" + name
    elif options.output_dir:
        directory = Path(options.output_dir)
    else:
        directory = source.parent

    target = directory / (name + ".mp4")
    # never write onto the source, not even on case-insensitive file systems
    if str(target.resolve()).casefold() == str(source.resolve()).casefold():
        target = directory / (name + "_conv.mp4")
    return target
