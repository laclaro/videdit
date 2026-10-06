"""Dialog to select the crop area on a snapshot of the video."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from ..core.errors import VideditError
from ..core.options import format_time, parse_aspect
from ..core.snapshot import snapshot_time, take_snapshot
from . import ASPECTS
from .selection import CropSelection

HANDLE = 10
CURSORS = {"move": Qt.CursorShape.SizeAllCursor, None: Qt.CursorShape.CrossCursor,
           "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
           "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
           "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
           "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor}


class CropView(QWidget):
    """Shows the snapshot and lets the user drag the selection with the mouse."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap()
        self.selection = None
        self._handle = None
        self._last = None
        self.setMouseTracking(True)
        self.setMinimumSize(480, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_picture(self, pixmap, selection):
        self.pixmap = pixmap
        self.selection = selection
        self.update()

    def _geometry(self):
        """Return scale and position of the picture inside of the widget"""
        scale = min(self.width() / self.selection.width, self.height() / self.selection.height)
        return (scale, (self.width() - self.selection.width * scale) / 2,
                (self.height() - self.selection.height * scale) / 2)

    def _to_picture(self, position):
        scale, left, top = self._geometry()
        return (position.x() - left) / scale, (position.y() - top) / scale

    def selection_rect(self):
        """Return the selection in coordinates of the widget"""
        scale, left, top = self._geometry()
        x, y, width, height = self.selection.rect
        return QRectF(left + x * scale, top + y * scale, width * scale, height * scale)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if self.selection is None:
            return
        scale, left, top = self._geometry()
        picture = QRectF(left, top, self.selection.width * scale, self.selection.height * scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(picture, self.pixmap, QRectF(self.pixmap.rect()))

        selected = self.selection_rect()
        shade = QColor(0, 0, 0, 150)
        painter.fillRect(QRectF(picture.left(), picture.top(), picture.width(),
                                selected.top() - picture.top()), shade)
        painter.fillRect(QRectF(picture.left(), selected.bottom(), picture.width(),
                                picture.bottom() - selected.bottom()), shade)
        painter.fillRect(QRectF(picture.left(), selected.top(),
                                selected.left() - picture.left(), selected.height()), shade)
        painter.fillRect(QRectF(selected.right(), selected.top(),
                                picture.right() - selected.right(), selected.height()), shade)

        painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for third in (1, 2):
            x = selected.left() + selected.width() * third / 3
            y = selected.top() + selected.height() * third / 3
            painter.drawLine(QPointF(x, selected.top()), QPointF(x, selected.bottom()))
            painter.drawLine(QPointF(selected.left(), y), QPointF(selected.right(), y))
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawRect(selected)
        painter.setBrush(QColor("white"))
        for x in (selected.left(), selected.center().x(), selected.right()):
            for y in (selected.top(), selected.center().y(), selected.bottom()):
                if (x, y) != (selected.center().x(), selected.center().y()):
                    painter.drawRect(QRectF(x - HANDLE / 2, y - HANDLE / 2, HANDLE, HANDLE))

    def mousePressEvent(self, event):
        if self.selection is None or event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self._to_picture(event.position())
        self._handle = self.selection.handle_at(x, y, HANDLE / self._geometry()[0]) or "new"
        self._last = (x, y)

    def mouseMoveEvent(self, event):
        if self.selection is None:
            return
        x, y = self._to_picture(event.position())
        if self._handle is None:
            self.setCursor(CURSORS[self.selection.handle_at(x, y, HANDLE / self._geometry()[0])])
            return
        if self._handle == "move":
            self.selection.move(x - self._last[0], y - self._last[1])
            self._last = (x, y)
        elif self._handle == "new":
            self.selection.select(*self._last, x, y)
        else:
            self.selection.drag(self._handle, x, y)
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, event):
        self._handle = None


class CropDialog(QDialog):
    """Offers a snapshot of the video to select the crop area with a choice of aspect ratios."""

    def __init__(self, source, info, options, tools, parent=None):
        """options provides rotation, flip and the current crop of the video"""
        super().__init__(parent)
        self.setWindowTitle("Crop {}".format(Path(source).name))
        self.source = source
        self.info = info
        self.options = options
        self.tools = tools
        self._directory = tempfile.TemporaryDirectory(prefix="videdit-")
        self.finished.connect(self._cleanup)

        width, height = info.display_size
        if options.rotate in (90, -90):
            width, height = height, width
        self.aspect_combo = QComboBox()
        self.aspect_combo.addItem("Free", None)
        self.aspect_combo.addItem("Original", "{}:{}".format(width, height))
        aspects = list(ASPECTS)
        if options.crop_aspect and options.crop_aspect not in aspects:
            aspects.append(options.crop_aspect)
        for aspect in aspects:
            self.aspect_combo.addItem(aspect, aspect)
        self.aspect_combo.setCurrentIndex(max(0, self.aspect_combo.findData(options.crop_aspect)))

        self.view = CropView()
        self.selection = CropSelection(width, height, self._aspect(), options.crop)
        self.size_label = QLabel()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(1, int(info.duration * 10)))
        self.slider.setValue(int(snapshot_time(info.duration) * 10))
        self.time_label = QLabel()
        reset = QPushButton("Reset")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)

        top = QHBoxLayout()
        top.addWidget(QLabel("Aspect ratio"))
        top.addWidget(self.aspect_combo)
        top.addWidget(reset)
        top.addStretch()
        top.addWidget(self.size_label)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Snapshot at"))
        bottom.addWidget(self.slider, 1)
        bottom.addWidget(self.time_label)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.view, 1)
        layout.addLayout(bottom)
        layout.addWidget(buttons)

        self.aspect_combo.currentIndexChanged.connect(self._aspect_changed)
        self.view.changed.connect(self._show_size)
        self.slider.valueChanged.connect(self._show_time)
        # the snapshot follows the slider once it rests
        self.snapshot_timer = QTimer(self)
        self.snapshot_timer.setSingleShot(True)
        self.snapshot_timer.setInterval(300)
        self.snapshot_timer.timeout.connect(self.load_snapshot)
        self.slider.valueChanged.connect(self.snapshot_timer.start)
        self.finished.connect(self.snapshot_timer.stop)
        reset.clicked.connect(self._reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.resize(900, 640)
        self._show_time()
        self._show_size()

    def _cleanup(self):
        self._directory.cleanup()

    def _aspect(self):
        text = self.aspect_combo.currentData()
        return parse_aspect(text) if text else None

    def _aspect_changed(self):
        self.selection.set_aspect(self._aspect())
        self.view.update()
        self._show_size()

    def _reset(self):
        self.selection.reset()
        self.view.update()
        self._show_size()

    def _show_size(self):
        crop = self.selection.crop()
        self.size_label.setText("{} × {} at {}, {}".format(crop.width, crop.height,
                                                           crop.x, crop.y))

    def _show_time(self):
        self.time_label.setText(format_time(self.slider.value() / 10))

    def load_snapshot(self):
        """Show the frame at the position of the slider, returns False on failure"""
        target = Path(self._directory.name) / "snapshot.png"
        position = min(self.slider.value() / 10, max(0.0, self.info.duration - 0.1))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            take_snapshot(self.source, target, self.info, self.options, position,
                          self.tools.ffmpeg)
        except VideditError as error:
            self.size_label.setText(str(error))
            return False
        finally:
            QApplication.restoreOverrideCursor()
        pixmap = QPixmap(str(target))
        if pixmap.isNull():
            return False
        self.view.set_picture(pixmap, self.selection)
        return True

    def crop(self):
        """Return the selected CropRect, None if the whole picture is selected"""
        return None if self.selection.is_everything else self.selection.crop()

    def aspect(self):
        """Return the chosen aspect ratio like 16:9, None for a free selection"""
        text = self.aspect_combo.currentData()
        return text if text in ASPECTS or text == self.options.crop_aspect else None
