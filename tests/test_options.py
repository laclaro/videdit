import pytest

from videdit.core.errors import OptionsError
from videdit.core.options import (ConversionOptions, CropRect, Scale, parse_aspect,
                                  parse_time)


@pytest.mark.parametrize("value, seconds", [("12.5", 12.5), (7, 7.0), ("01:30", 90.0),
                                            ("01:02:03.5", 3723.5)])
def test_parse_time(value, seconds):
    assert parse_time(value) == seconds


@pytest.mark.parametrize("text", ["end", "", "1:2:3:4", "-5", "1:-5", "nan", "inf"])
def test_parse_time_invalid(text):
    with pytest.raises(OptionsError):
        parse_time(text)


def test_parse_aspect():
    assert parse_aspect("16:9") == pytest.approx(16 / 9)
    assert parse_aspect("2.35:1") == pytest.approx(2.35)


@pytest.mark.parametrize("text", ["16", "16:0", "a:b", "16:9:1"])
def test_parse_aspect_invalid(text):
    with pytest.raises(OptionsError):
        parse_aspect(text)


def test_parse_crop():
    assert CropRect.parse("640:360:10:20") == CropRect(640, 360, 10, 20)


@pytest.mark.parametrize("text", ["640:360", "0:360:0:0", "640:360:-2:0", "a:b:c:d"])
def test_parse_crop_invalid(text):
    with pytest.raises(OptionsError):
        CropRect.parse(text)


def test_parse_scale():
    assert Scale.parse("50%") == Scale(50.0, True)
    assert Scale.parse("720") == Scale(720.0, False)
    assert Scale.parse("50%").label == "50pct"
    assert Scale.parse("720").label == "720p"


@pytest.mark.parametrize("text", ["0", "-50%", "big", ""])
def test_parse_scale_invalid(text):
    with pytest.raises(OptionsError):
        Scale.parse(text)


def test_defaults_are_valid():
    options = ConversionOptions()
    options.validate()
    assert options.parsed_scales() == [None]
    assert not options.cuts
    assert not options.crops


@pytest.mark.parametrize("values", [
    dict(preset="fast"), dict(crf=52), dict(start=-1.0), dict(start=5.0, end=5.0),
    dict(fade=-0.1), dict(rotate=45), dict(flip="x"), dict(crop_aspect="wide"),
    dict(photo_tolerance=-1), dict(rename=True), dict(time_offset="2h"),
    dict(scales=("huge",))])
def test_invalid_options(values):
    with pytest.raises(OptionsError):
        ConversionOptions(**values).validate()


def test_scales_drop_duplicates_and_keep_order():
    options = ConversionOptions(scales=("720", "50%", "720"))
    assert options.parsed_scales() == [Scale(720.0, False), Scale(50.0, True)]


def test_dict_round_trip():
    options = ConversionOptions(preset="quick", start=1.0, end=9.0, scales=("720",),
                                rotate=-90, crop=CropRect(100, 50, 2, 4),
                                photo_dir="/photos", rename=True, time_offset="+02:00")
    assert ConversionOptions.from_dict(options.to_dict()) == options


def test_sticky_dict_omits_per_file_options():
    data = ConversionOptions(start=1.0, end=9.0, crop=CropRect(100, 50), force=True,
                             crop_aspect="1:1").to_dict(sticky_only=True)
    assert not {"start", "end", "crop", "force"} & set(data)
    assert data["crop_aspect"] == "1:1"


def test_from_dict_ignores_unknown_keys():
    assert ConversionOptions.from_dict({"fade": 0.5, "obsolete": 1}).fade == 0.5


@pytest.mark.parametrize("data", [{"preset": "fast"}, {"crop": {"w": 1}}])
def test_from_dict_rejects_invalid(data):
    with pytest.raises(OptionsError):
        ConversionOptions.from_dict(data)
