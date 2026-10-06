"""
Geometry of the crop selection, independent of Qt. All coordinates are
pixels of the picture, handles are named by the edges they move, e.g. "tl"
for the top left corner or "r" for the right edge.
"""

from __future__ import annotations

from ..core.options import CropRect

MIN_SIZE = 16.0


def _limit(value, low, high):
    return min(max(value, low), high)


class CropSelection:
    """A rectangle inside a picture, optionally locked to an aspect ratio."""

    def __init__(self, width, height, aspect=None, crop=None):
        self.width = float(width)
        self.height = float(height)
        self.aspect = None
        self.rect = (0.0, 0.0, self.width, self.height)
        if crop is not None:
            crop_width = _limit(crop.width, MIN_SIZE, self.width)
            crop_height = _limit(crop.height, MIN_SIZE, self.height)
            self.rect = self._inside(crop.x, crop.y, crop_width, crop_height)
        self.set_aspect(aspect)

    def _inside(self, x, y, width, height):
        """Shift a rectangle so that it lies inside the picture"""
        return (_limit(x, 0.0, self.width - width), _limit(y, 0.0, self.height - height),
                width, height)

    def set_aspect(self, aspect):
        """Lock the selection to an aspect ratio width/height, None unlocks it"""
        self.aspect = aspect
        if aspect is None:
            return
        x, y, width, height = self.rect
        # nothing to do if the selection has this ratio already (within a pixel)
        if abs(width - height * aspect) <= max(1.0, aspect):
            return
        new_width = min(width, self.width, self.height * aspect)
        new_height = new_width / aspect
        self.rect = self._inside(x + (width - new_width) / 2, y + (height - new_height) / 2,
                                 new_width, new_height)

    def reset(self):
        """Select the whole picture or the largest part having the aspect ratio"""
        self.rect = (0.0, 0.0, self.width, self.height)
        self.set_aspect(self.aspect)

    def handle_at(self, x, y, margin):
        """
        Return what is to be found at a position: the name of a handle,
        "move" inside of the selection or None outside of it.
        """
        left, top, width, height = self.rect
        right, bottom = left + width, top + height
        if not (left - margin <= x <= right + margin and top - margin <= y <= bottom + margin):
            return None
        handle = ""
        if abs(y - top) <= margin:
            handle += "t"
        elif abs(y - bottom) <= margin:
            handle += "b"
        if abs(x - left) <= margin:
            handle += "l"
        elif abs(x - right) <= margin:
            handle += "r"
        return handle or "move"

    def move(self, dx, dy):
        """Shift the selection, it stops at the borders of the picture"""
        x, y, width, height = self.rect
        self.rect = self._inside(x + dx, y + dy, width, height)

    def select(self, x0, y0, x1, y1):
        """Span a new selection from the first to the second position"""
        x0, y0 = _limit(x0, 0.0, self.width), _limit(y0, 0.0, self.height)
        self.rect = (x0, y0, 0.0, 0.0)
        self.drag(("t" if y1 < y0 else "b") + ("l" if x1 < x0 else "r"), x1, y1)

    def drag(self, handle, x, y):
        """Move a handle to a position, the opposite side stays where it is"""
        x, y = _limit(x, 0.0, self.width), _limit(y, 0.0, self.height)
        left, top, width, height = self.rect
        right, bottom = left + width, top + height
        horizontal = "l" in handle or "r" in handle
        vertical = "t" in handle or "b" in handle

        if self.aspect is None:
            if "l" in handle:
                left = min(x, right - MIN_SIZE)
            if "r" in handle:
                right = max(x, left + MIN_SIZE)
            if "t" in handle:
                top = min(y, bottom - MIN_SIZE)
            if "b" in handle:
                bottom = max(y, top + MIN_SIZE)
            self.rect = self._inside(left, top, right - left, bottom - top)
            return

        aspect = self.aspect
        smallest = MIN_SIZE * max(aspect, 1.0)
        # the anchor is the point which stays, the selection grows from it
        # in the directions sign_x and sign_y
        sign_x = -1 if "l" in handle else 1
        sign_y = -1 if "t" in handle else 1
        anchor_x = right if "l" in handle else left
        anchor_y = bottom if "t" in handle else top
        room_x = anchor_x if sign_x < 0 else self.width - anchor_x
        room_y = anchor_y if sign_y < 0 else self.height - anchor_y

        if horizontal and vertical:
            wanted = max((x - anchor_x) * sign_x, (y - anchor_y) * sign_y * aspect, smallest)
            new_width = min(wanted, room_x, room_y * aspect)
            new_height = new_width / aspect
            new_left = anchor_x - new_width if sign_x < 0 else anchor_x
            new_top = anchor_y - new_height if sign_y < 0 else anchor_y
        elif horizontal:
            centre = top + height / 2
            room = 2 * min(centre, self.height - centre)
            new_width = min(max((x - anchor_x) * sign_x, smallest), room_x, room * aspect)
            new_height = new_width / aspect
            new_left = anchor_x - new_width if sign_x < 0 else anchor_x
            new_top = centre - new_height / 2
        elif vertical:
            centre = left + width / 2
            room = 2 * min(centre, self.width - centre)
            new_height = min(max((y - anchor_y) * sign_y, smallest / aspect), room_y,
                             room / aspect)
            new_width = new_height * aspect
            new_left = centre - new_width / 2
            new_top = anchor_y - new_height if sign_y < 0 else anchor_y
        else:
            return
        self.rect = (new_left, new_top, new_width, new_height)

    @property
    def is_everything(self):
        """True if the whole picture is selected"""
        return self.crop() == CropRect(int(self.width) // 2 * 2, int(self.height) // 2 * 2)

    def crop(self):
        """Return the selection as crop rectangle with even numbers of pixels"""
        x, y, width, height = self.rect
        even = [max(0, int(round(value / 2)) * 2) for value in (width, height, x, y)]
        even[0] = max(2, min(even[0], int(self.width) // 2 * 2 - even[2]))
        even[1] = max(2, min(even[1], int(self.height) // 2 * 2 - even[3]))
        return CropRect(*even)
