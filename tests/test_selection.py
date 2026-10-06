import pytest

from videdit.core.options import CropRect
from videdit.gui.selection import MIN_SIZE, CropSelection


def test_whole_picture_is_selected_at_first():
    selection = CropSelection(1920, 1080)
    assert selection.rect == (0.0, 0.0, 1920.0, 1080.0)
    assert selection.is_everything
    assert selection.crop() == CropRect(1920, 1080, 0, 0)


@pytest.mark.parametrize("aspect, rect", [(1.0, (420.0, 0.0, 1080.0, 1080.0)),
                                          (16 / 9, (0.0, 0.0, 1920.0, 1080.0)),
                                          (9 / 16, (656.25, 0.0, 607.5, 1080.0))])
def test_aspect_selects_the_centre(aspect, rect):
    assert CropSelection(1920, 1080, aspect).rect == pytest.approx(rect)


def test_existing_crop_is_kept():
    selection = CropSelection(1920, 1080, 1.0, CropRect(400, 400, 100, 200))
    assert selection.rect == (100.0, 200.0, 400.0, 400.0)
    assert not selection.is_everything
    selection.set_aspect(2.0)
    assert selection.rect == (100.0, 300.0, 400.0, 200.0)
    selection.reset()
    assert selection.rect == (0.0, 60.0, 1920.0, 960.0)


def test_crop_outside_of_the_picture_is_moved_inside():
    assert CropSelection(640, 360, None, CropRect(400, 400, 500, 200)).rect \
        == (240.0, 0.0, 400.0, 360.0)


def test_move_stops_at_the_borders():
    selection = CropSelection(1000, 500, None, CropRect(200, 100, 100, 100))
    selection.move(50, -20)
    assert selection.rect == (150.0, 80.0, 200.0, 100.0)
    selection.move(5000, 5000)
    assert selection.rect == (800.0, 400.0, 200.0, 100.0)


def test_handle_at():
    selection = CropSelection(1000, 500, None, CropRect(200, 100, 100, 100))
    assert selection.handle_at(100, 100, 5) == "tl"
    assert selection.handle_at(302, 198, 5) == "br"
    assert selection.handle_at(200, 97, 5) == "t"
    assert selection.handle_at(298, 150, 5) == "r"
    assert selection.handle_at(200, 150, 5) == "move"
    assert selection.handle_at(400, 150, 5) is None


def test_drag_free():
    selection = CropSelection(1000, 500, None, CropRect(200, 100, 100, 100))
    selection.drag("br", 500, 400)
    assert selection.rect == (100.0, 100.0, 400.0, 300.0)
    selection.drag("l", 50, 0)
    assert selection.rect == (50.0, 100.0, 450.0, 300.0)
    selection.drag("t", 0, 5000)
    assert selection.rect == (50.0, 400.0 - MIN_SIZE, 450.0, MIN_SIZE)
    selection.drag("tr", 5000, -5000)
    assert selection.rect == (50.0, 0.0, 950.0, 400.0)


def test_drag_corner_keeps_the_aspect():
    selection = CropSelection(1000, 500, 2.0, CropRect(200, 100, 100, 100))
    selection.drag("br", 400, 150)
    assert selection.rect == (100.0, 100.0, 300.0, 150.0)
    # the picture ends 400 pixels below the anchor
    selection.drag("br", 5000, 5000)
    assert selection.rect == (100.0, 100.0, 800.0, 400.0)
    selection.drag("tl", 880, 499)
    assert selection.rect == (900.0 - 2 * MIN_SIZE, 500.0 - MIN_SIZE, 2 * MIN_SIZE, MIN_SIZE)


def test_drag_edge_keeps_the_aspect_and_the_centre():
    selection = CropSelection(1000, 500, 2.0, CropRect(200, 100, 100, 100))
    selection.drag("r", 500, 0)
    assert selection.rect == (100.0, 50.0, 400.0, 200.0)
    selection.drag("b", 0, 150)
    assert selection.rect == (200.0, 50.0, 200.0, 100.0)
    selection.drag("l", -5000, 0)
    assert selection.rect == (0.0, 0.0, 400.0, 200.0)


@pytest.mark.parametrize("aspect, rect", [(None, (100.0, 50.0, 300.0, 250.0)),
                                          (1.0, (100.0, 0.0, 300.0, 300.0))])
def test_select_in_any_direction(aspect, rect):
    selection = CropSelection(1000, 500, aspect)
    selection.select(400, 300, 100, 50)
    assert selection.rect == rect


def test_crop_is_even_and_inside():
    selection = CropSelection(641, 361)
    assert selection.crop() == CropRect(640, 360, 0, 0)
    assert selection.is_everything
    selection.rect = (101.4, 33.0, 301.2, 199.0)
    assert selection.crop() == CropRect(302, 200, 102, 32)
