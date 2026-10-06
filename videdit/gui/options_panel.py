"""The widgets to choose the conversion options."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from ..core.options import PRESETS, ConversionOptions, format_time, parse_time
from . import ASPECTS

SCALE_CHOICES = ("1080", "720", "540", "50%")


def _row(*widgets):
    """Put widgets next to each other"""
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


def _select(combo, data):
    """Select the entry of a combo box carrying the data"""
    combo.setCurrentIndex(max(0, combo.findData(data)))


class DirectoryEdit(QWidget):
    """A line to enter a directory with a button to browse for it."""
    changed = Signal()

    def __init__(self, title, placeholder="", parent=None):
        super().__init__(parent)
        self.title = title
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self.changed)
        button = QPushButton("Browse…")
        button.clicked.connect(self.browse)
        self.setLayout(_row(self.edit, button))

    def browse(self):
        directory = QFileDialog.getExistingDirectory(self, self.title, self.edit.text())
        if directory:
            self.edit.setText(directory)

    def text(self):
        return self.edit.text().strip()

    def setText(self, text):
        self.edit.setText(text or "")


class OptionsPanel(QWidget):
    """Shows and edits the ConversionOptions of a video."""
    changed = Signal()
    crop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._crop = None
        # options without widget keep the value they were loaded with
        self._show_photo = False
        layout = QVBoxLayout(self)
        for group in (self._video_group(), self._picture_group(), self._quality_group(),
                      self._photo_group(), self._output_group()):
            layout.addWidget(group)
        layout.addStretch()
        self.set_options(ConversionOptions())

    def _video_group(self):
        self.video_group = QGroupBox("Cut and crop area")
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("beginning")
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("end")
        for edit in (self.start_edit, self.end_edit):
            edit.setToolTip("Seconds or hh:mm:ss")
            edit.textChanged.connect(self.changed)
        self.crop_label = QLabel()
        self.crop_button = QPushButton("Select area…")
        self.crop_button.clicked.connect(self.crop_requested)
        self.crop_clear = QPushButton("Clear")
        self.crop_clear.clicked.connect(self.clear_crop)
        form = QFormLayout(self.video_group)
        form.addRow("Cut from", _row(self.start_edit, QLabel("to"), self.end_edit))
        form.addRow("Crop area", _row(self.crop_label, self.crop_button, self.crop_clear))
        return self.video_group

    def _picture_group(self):
        group = QGroupBox("Picture")
        self.aspect_combo = QComboBox()
        self.aspect_combo.addItem("No crop", None)
        for aspect in ASPECTS:
            self.aspect_combo.addItem(aspect, aspect)
        self.aspect_combo.setToolTip("Crops the centre of the picture unless an area is "
                                     "selected for the video")
        self.rotate_combo = QComboBox()
        for label, value in (("None", None), ("90° clockwise", 90),
                             ("90° counter-clockwise", -90), ("180°", 180)):
            self.rotate_combo.addItem(label, value)
        self.flip_combo = QComboBox()
        for label, value in (("None", None), ("Horizontal", "h"), ("Vertical", "v")):
            self.flip_combo.addItem(label, value)
        self.scale_checks = {}
        for value in SCALE_CHOICES:
            check = QCheckBox(value.replace("%", " %") if "%" in value else value + "p")
            check.toggled.connect(self.changed)
            self.scale_checks[value] = check
        self.scale_edit = QLineEdit()
        self.scale_edit.setPlaceholderText("more, e.g. 360, 25%")
        self.scale_edit.setToolTip("Length of the short edge in pixels or a percentage. "
                                   "Every size yields a file, none keeps the original size.")
        self.scale_edit.textChanged.connect(self.changed)
        for combo in (self.aspect_combo, self.rotate_combo, self.flip_combo):
            combo.currentIndexChanged.connect(self.changed)
        form = QFormLayout(group)
        form.addRow("Crop to", self.aspect_combo)
        form.addRow("Rotate", self.rotate_combo)
        form.addRow("Flip", self.flip_combo)
        form.addRow("Sizes", _row(*self.scale_checks.values()))
        form.addRow("", self.scale_edit)
        return group

    def _quality_group(self):
        group = QGroupBox("Quality and fade")
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Default (high quality)", "default")
        self.preset_combo.addItem("Quick (fast, small file)", "quick")
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self.crf_check = QCheckBox("Custom CRF")
        self.crf_check.setToolTip("0 is the best quality, 51 the worst")
        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(0, 51)
        self.crf_check.toggled.connect(self.crf_spin.setEnabled)
        self.crf_check.toggled.connect(self.changed)
        self.crf_spin.valueChanged.connect(self.changed)
        self.fade_check = QCheckBox("Fade in and out for")
        self.fade_spin = QDoubleSpinBox()
        self.fade_spin.setRange(0.1, 10.0)
        self.black_spin = QDoubleSpinBox()
        self.black_spin.setRange(0.0, 10.0)
        for spin in (self.fade_spin, self.black_spin):
            spin.setSingleStep(0.1)
            spin.setDecimals(1)
            spin.setSuffix(" s")
            spin.valueChanged.connect(self.changed)
            self.fade_check.toggled.connect(spin.setEnabled)
        self.fade_check.toggled.connect(self.changed)
        form = QFormLayout(group)
        form.addRow("Preset", self.preset_combo)
        form.addRow(self.crf_check, self.crf_spin)
        form.addRow(self.fade_check, self.fade_spin)
        form.addRow("Black before and after", self.black_spin)
        return group

    def _photo_group(self):
        self.photo_group = QGroupBox("Find the photo taken at the same time")
        self.photo_group.setCheckable(True)
        self.photo_group.toggled.connect(self.changed)
        self.photo_dir = DirectoryEdit("Directory with photos")
        self.photo_dir.changed.connect(self.changed)
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 86400)
        self.tolerance_spin.setSingleStep(30)
        self.tolerance_spin.setSuffix(" s")
        self.tolerance_spin.valueChanged.connect(self.changed)
        self.rename_check = QCheckBox("Place the video next to the photo, named after it")
        self.rename_check.toggled.connect(self.changed)
        self.offset_edit = QLineEdit()
        self.offset_edit.setPlaceholderText("as stored in the video")
        self.offset_edit.setToolTip("UTC offset of the camera clock like +02:00, "
                                    "only needed if the camera stored a wrong one")
        self.offset_edit.textChanged.connect(self.changed)
        form = QFormLayout(self.photo_group)
        form.addRow("Photo directory", self.photo_dir)
        form.addRow("Time window", self.tolerance_spin)
        form.addRow("Camera UTC offset", self.offset_edit)
        form.addRow(self.rename_check)
        return self.photo_group

    def _output_group(self):
        group = QGroupBox("Output")
        self.output_dir = DirectoryEdit("Output directory", "next to the video")
        self.output_dir.changed.connect(self.changed)
        self.force_check = QCheckBox("Overwrite existing files")
        self.force_check.toggled.connect(self.changed)
        form = QFormLayout(group)
        form.addRow("Directory", self.output_dir)
        form.addRow(self.force_check)
        return group

    def _preset_changed(self):
        if not self.crf_check.isChecked():
            self.crf_spin.setValue(PRESETS[self.preset_combo.currentData()].crf)
        self.changed.emit()

    def _scales(self):
        scales = [value for value, check in self.scale_checks.items() if check.isChecked()]
        return tuple(scales + self.scale_edit.text().replace(",", " ").split())

    def set_options(self, options):
        """Show the options without reporting a change"""
        self.blockSignals(True)
        self._show_photo = options.show_photo
        _select(self.preset_combo, options.preset)
        self.crf_check.setChecked(options.crf is not None)
        self.crf_spin.setEnabled(options.crf is not None)
        self.crf_spin.setValue(PRESETS[options.preset].crf if options.crf is None
                               else options.crf)
        self.fade_check.setChecked(options.fade > 0)
        self.fade_spin.setValue(options.fade if options.fade > 0 else 0.3)
        self.black_spin.setValue(options.fade_black)
        self.fade_spin.setEnabled(options.fade > 0)
        self.black_spin.setEnabled(options.fade > 0)
        if options.crop_aspect and self.aspect_combo.findData(options.crop_aspect) < 0:
            self.aspect_combo.addItem(options.crop_aspect, options.crop_aspect)
        _select(self.aspect_combo, options.crop_aspect)
        _select(self.rotate_combo, options.rotate)
        _select(self.flip_combo, options.flip)
        for value, check in self.scale_checks.items():
            check.setChecked(value in options.scales)
        self.scale_edit.setText(", ".join(scale for scale in options.scales
                                          if scale not in self.scale_checks))
        self.photo_group.setChecked(bool(options.photo_dir))
        self.photo_dir.setText(options.photo_dir)
        self.tolerance_spin.setValue(int(options.photo_tolerance))
        self.rename_check.setChecked(options.rename)
        self.offset_edit.setText(options.time_offset or "")
        self.output_dir.setText(options.output_dir)
        self.force_check.setChecked(options.force)
        self.start_edit.setText("" if options.start is None else format_time(options.start))
        self.end_edit.setText("" if options.end is None else format_time(options.end))
        self._show_crop(options.crop)
        self.blockSignals(False)

    def options(self):
        """Return the validated options, raises OptionsError for invalid input"""
        start, end = self.start_edit.text().strip(), self.end_edit.text().strip()
        searching = self.photo_group.isChecked() and bool(self.photo_dir.text())
        options = ConversionOptions(
            preset=self.preset_combo.currentData(),
            crf=self.crf_spin.value() if self.crf_check.isChecked() else None,
            start=parse_time(start) if start else None,
            end=parse_time(end) if end else None,
            fade=self.fade_spin.value() if self.fade_check.isChecked() else 0.0,
            fade_black=self.black_spin.value(),
            scales=self._scales(),
            rotate=self.rotate_combo.currentData(),
            flip=self.flip_combo.currentData(),
            crop=self._crop,
            crop_aspect=self.aspect_combo.currentData(),
            photo_dir=self.photo_dir.text() if searching else None,
            photo_tolerance=float(self.tolerance_spin.value()),
            rename=searching and self.rename_check.isChecked(),
            show_photo=self._show_photo,
            output_dir=self.output_dir.text() or None,
            time_offset=self.offset_edit.text().strip() or None,
            force=self.force_check.isChecked())
        options.validate()
        return options

    def _show_crop(self, crop):
        self._crop = crop
        if crop is None:
            self.crop_label.setText("none")
        else:
            self.crop_label.setText("{} × {} at {}, {}".format(crop.width, crop.height,
                                                               crop.x, crop.y))
        self.crop_clear.setEnabled(crop is not None)

    def set_crop(self, crop):
        """Set the crop area, None removes it"""
        self._show_crop(crop)
        self.changed.emit()

    def clear_crop(self):
        self.set_crop(None)

    def set_crop_aspect(self, aspect):
        """Select the aspect ratio of the crop, e.g. 16:9"""
        if aspect and self.aspect_combo.findData(aspect) < 0:
            self.aspect_combo.addItem(aspect, aspect)
        _select(self.aspect_combo, aspect)
