import pytest

from videdit.core.errors import OptionsError
from videdit.core.filters import (build_command, clip_range, crop_rect, fade_filters,
                                  plan_filters, scaled_size, transpose_filters)
from videdit.core.options import ConversionOptions, CropRect, Scale
from videdit.core.probe import VideoInfo

HD = VideoInfo(width=1920, height=1080, duration=20.0)


def option_value(command, name):
    return command[command.index(name) + 1]


@pytest.mark.parametrize("values, filters", [
    (dict(), []),
    (dict(rotate=90), ["transpose=1"]),
    (dict(rotate=-90), ["transpose=2"]),
    (dict(rotate=180), ["hflip", "vflip"]),
    (dict(rotate=90, flip="v"), ["transpose=1", "vflip"])])
def test_transpose(values, filters):
    assert transpose_filters(ConversionOptions(**values)) == filters


def test_no_crop():
    assert crop_rect(ConversionOptions(), 1920, 1080) is None


def test_crop_aspect_is_centred():
    assert crop_rect(ConversionOptions(crop_aspect="1:1"), 1920, 1080) \
        == CropRect(1080, 1080, 420, 0)
    assert crop_rect(ConversionOptions(crop_aspect="16:9"), 1080, 1920) \
        == CropRect(1080, 606, 0, 656)


def test_crop_aspect_of_the_picture_needs_no_crop():
    assert crop_rect(ConversionOptions(crop_aspect="16:9"), 1920, 1080) is None


def test_crop_rectangle_is_rounded_to_even_pixels():
    options = ConversionOptions(crop=CropRect(641, 361, 11, 21))
    assert crop_rect(options, 1920, 1080) == CropRect(640, 360, 10, 20)


def test_crop_rectangle_wins_over_aspect():
    options = ConversionOptions(crop=CropRect(640, 360, 0, 0), crop_aspect="1:1")
    assert crop_rect(options, 1920, 1080) == CropRect(640, 360, 0, 0)


def test_crop_rectangle_outside_of_the_picture():
    with pytest.raises(OptionsError):
        crop_rect(ConversionOptions(crop=CropRect(1000, 1000, 1000, 0)), 1920, 1080)


@pytest.mark.parametrize("scale, size, result", [
    ("50%", (1920, 1080), (960, 540)),
    ("720", (1920, 1080), (1280, 720)),
    ("720", (3840, 2160), (1280, 720)),
    ("720", (1080, 1920), (720, 1280)),
    ("33%", (1920, 1080), (634, 356))])
def test_scaled_size(scale, size, result):
    assert scaled_size(Scale.parse(scale), *size) == result


def test_clip_range():
    assert clip_range(ConversionOptions(), 20.0) == (0.0, 20.0)
    assert clip_range(ConversionOptions(start=2.0, end=8.0), 20.0) == (2.0, 8.0)
    assert clip_range(ConversionOptions(end=99.0), 20.0) == (0.0, 20.0)
    with pytest.raises(OptionsError):
        clip_range(ConversionOptions(start=25.0), 20.0)


def test_fade():
    video, audio = fade_filters(ConversionOptions(), 20.0)
    assert video == ["fade=t=in:st=0.1:d=0.3,fade=t=out:st=19.6:d=0.3"]
    assert audio == ["afade=t=in:st=0.1:d=0.3,afade=t=out:st=19.6:d=0.3"]


def test_fade_disabled():
    assert tuple(fade_filters(ConversionOptions(fade=0.0), 20.0)) == ([], [])


def test_fade_is_shortened_for_short_clips():
    video, _ = fade_filters(ConversionOptions(), 0.6)
    assert video == ["fade=t=in:st=0.1:d=0.2,fade=t=out:st=0.3:d=0.2"]


def test_no_fade_if_the_clip_is_too_short():
    assert tuple(fade_filters(ConversionOptions(), 0.2)) == ([], [])


def test_filter_order():
    options = ConversionOptions(rotate=90, crop_aspect="1:1")
    plan = plan_filters(options, HD, Scale.parse("50%"))
    assert plan.video == ("transpose=1", "crop=1080:1080:0:420", "scale=540:540",
                          "fade=t=in:st=0.1:d=0.3,fade=t=out:st=19.6:d=0.3")
    assert (plan.width, plan.height) == (540, 540)


def test_rotation_flag_swaps_the_picture_size():
    portrait = VideoInfo(width=1920, height=1080, duration=20.0, rotation=90)
    plan = plan_filters(ConversionOptions(fade=0.0), portrait, Scale.parse("720"))
    assert plan.video == ("scale=720:1280",)


def test_no_audio_filter_without_audio():
    silent = VideoInfo(width=1920, height=1080, duration=20.0, has_audio=False)
    assert plan_filters(ConversionOptions(), silent).audio == ()


def test_fade_refers_to_the_cut_clip():
    plan = plan_filters(ConversionOptions(start=5.0, end=15.0), HD)
    assert (plan.start, plan.duration) == (5.0, 10.0)
    assert plan.video == ("fade=t=in:st=0.1:d=0.3,fade=t=out:st=9.6:d=0.3",)


def test_plans_do_not_influence_each_other():
    options = ConversionOptions()
    assert plan_filters(options, HD, Scale.parse("720")) \
        == plan_filters(options, HD, Scale.parse("720"))


def test_command_of_plain_conversion():
    command = build_command("in file.MP4", "out.mp4", ConversionOptions(fade=0.0), HD)
    assert command == ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-i", "in file.MP4", "-map_metadata", "0",
                       "-movflags", "use_metadata_tags", "-c:v", "libx264",
                       "-crf", "19", "-c:a", "aac", "out.mp4"]


def test_command_of_quick_preset():
    command = build_command("in.mp4", "out.mp4", ConversionOptions(preset="quick"), HD)
    assert option_value(command, "-crf") == "30"
    assert option_value(command, "-b:a") == "96k"
    assert option_value(command, "-movflags") == "use_metadata_tags+faststart"


def test_crf_overrides_the_preset():
    command = build_command("in.mp4", "out.mp4", ConversionOptions(crf=23), HD)
    assert option_value(command, "-crf") == "23"


def test_cut_seeks_in_front_of_the_input():
    command = build_command("in.mp4", "out.mp4", ConversionOptions(start=5.0, end=15.5), HD)
    assert option_value(command, "-ss") == "5"
    assert option_value(command, "-t") == "10.5"
    assert command.index("-t") < command.index("-i")


def test_cut_without_end_reaches_the_end_of_the_video():
    command = build_command("in.mp4", "out.mp4", ConversionOptions(start=5.0), HD)
    assert option_value(command, "-t") == "15"


def test_cut_without_start():
    command = build_command("in.mp4", "out.mp4", ConversionOptions(end=4.0), HD)
    assert "-ss" not in command
    assert option_value(command, "-t") == "4"


def test_command_with_filters():
    command = build_command("in.mp4", "out.mp4", ConversionOptions(flip="h"), HD,
                            Scale.parse("720"), ffmpeg="/opt/ffmpeg")
    assert command[0] == "/opt/ffmpeg"
    assert option_value(command, "-filter:v") \
        == "hflip,scale=1280:720,fade=t=in:st=0.1:d=0.3,fade=t=out:st=19.6:d=0.3"
    assert option_value(command, "-filter:a") \
        == "afade=t=in:st=0.1:d=0.3,afade=t=out:st=19.6:d=0.3"


def test_command_with_tags():
    command = build_command("in.mp4", "out.mp4", ConversionOptions(), HD,
                            tags={"creation_time": "2020-04-12T13:30:00.000000Z", "a": "b c"})
    position = command.index("-metadata")
    assert command[position:position + 4] == ["-metadata",
                                              "creation_time=2020-04-12T13:30:00.000000Z",
                                              "-metadata", "a=b c"]
    assert command.index("-i") < position < command.index("-c:v")
