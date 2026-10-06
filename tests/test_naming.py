from pathlib import Path

from videdit.core.naming import output_path, suffix
from videdit.core.options import ConversionOptions, CropRect, Scale


def test_suffix_of_plain_conversion():
    assert suffix(ConversionOptions()) == ""


def test_suffix_of_all_actions():
    options = ConversionOptions(start=1.0, crop=CropRect(10, 10), rotate=-90, flip="h",
                                preset="quick")
    assert suffix(options, Scale.parse("720")) == "_cut_crop_rot-90_fliph_quick_720p"
    assert suffix(ConversionOptions(crop_aspect="1:1"), Scale.parse("50%")) == "_crop_50pct"


def test_next_to_the_source():
    assert output_path("/videos/C0001.MTS", ConversionOptions()) == Path("/videos/C0001.mp4")
    assert output_path("/videos/C0001.MP4", ConversionOptions(end=3.0), Scale.parse("720")) \
        == Path("/videos/C0001_cut_720p.mp4")


def test_output_directory():
    assert output_path("/videos/C0001.MP4", ConversionOptions(output_dir="/out")) \
        == Path("/out/C0001.mp4")


def test_source_is_never_the_target(tmp_path):
    assert output_path("/videos/C0001.mp4", ConversionOptions()) \
        == Path("/videos/C0001_conv.mp4")
    assert output_path("/videos/C0001.MP4", ConversionOptions()) \
        == Path("/videos/C0001_conv.mp4")
    assert output_path(tmp_path / "a.mp4", ConversionOptions()) == tmp_path / "a_conv.mp4"


def test_rename_places_the_video_next_to_the_photo():
    options = ConversionOptions(photo_dir="/photos", rename=True, output_dir="/out")
    assert output_path("/videos/C0001.MP4", options, photo="/photos/a/DSC0042.JPG") \
        == Path("/photos/a/DSC0042_C0001.mp4")


def test_rename_without_related_photo():
    options = ConversionOptions(photo_dir="/photos", rename=True)
    assert output_path("/videos/C0001.MTS", options) == Path("/videos/C0001.mp4")


def test_photo_is_only_a_suggestion_without_rename():
    options = ConversionOptions(photo_dir="/photos")
    assert output_path("/videos/C0001.MTS", options, photo="/photos/DSC0042.JPG") \
        == Path("/videos/C0001.mp4")
