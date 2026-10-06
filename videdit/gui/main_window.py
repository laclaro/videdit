"""The main window: queue of videos, their options, preview of the result and conversion."""

from __future__ import annotations

import dataclasses
import logging
import os
import shlex
import time

from PySide6.QtCore import QItemSelectionModel, QSize, Qt, QTimer
from PySide6.QtGui import QImageReader, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
                               QSplitter, QVBoxLayout, QWidget)

from ..core import dependencies, job, settings
from ..core.errors import VideditError
from ..core.options import ConversionOptions, format_time
from ..core.probe import probe
from .crop_dialog import CropDialog
from .options_panel import OptionsPanel
from .worker import ConversionWorker, LogRelay, ScanWorker

VIDEO_FILTER = "Videos (*.mp4 *.MP4 *.mts *.MTS *.m2ts *.mov *.MOV *.avi *.mkv);;All files (*)"
THUMBNAIL = 160
# pressing Escape twice within this time in seconds closes the window
ESCAPE_INTERVAL = 0.5


class MainWindow(QMainWindow):
    def __init__(self, settings_path=None):
        super().__init__()
        self.setWindowTitle("videdit")
        self.setAcceptDrops(True)
        self.settings_path = settings_path
        self.settings = settings.load(settings_path)
        # every video of the queue has its own options, settings.options holds
        # the ones edited last as template for videos added later
        self.file_options = {}
        self.problems = dependencies.check(self.settings.tools)
        # scanned photo directories, None while the scan is running
        self.indexes = {}
        self.scanners = []
        self.worker = None
        self.ready = False
        # the last note about a value which could not be set, to tell it only once
        self._note = None

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.add_button = QPushButton("Add videos…")
        self.remove_button = QPushButton("Remove")
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.photo_label = QLabel()
        self.photo_label.setFixedSize(THUMBNAIL, THUMBNAIL)
        self.photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.panel = OptionsPanel()
        self.warning_label = QLabel("\n".join(problem.message for problem in self.problems))
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("background: #fff3cd; color: #5c4400; padding: 6px;")
        self.warning_label.setVisible(bool(self.problems))
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.command_button = QPushButton("Show command…")
        self.convert_button = QPushButton("Convert")
        self.convert_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setFixedHeight(110)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        left_layout.addLayout(buttons)
        left_layout.addWidget(self.file_list, 1)
        preview = QHBoxLayout()
        preview.addWidget(self.preview_label, 1)
        preview.addWidget(self.photo_label)
        left_layout.addLayout(preview)
        scroll = QScrollArea()
        scroll.setWidget(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.command_button)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.convert_button)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.warning_label)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)
        layout.addWidget(self.log)
        self.setCentralWidget(central)
        self.resize(1100, 840)

        # the preview follows the options with a short delay
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(250)
        self.preview_timer.timeout.connect(self.update_preview)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1000)
        self.save_timer.timeout.connect(self.save_settings)
        self.log_relay = LogRelay(self)
        self.log_relay.message.connect(self.log.appendPlainText)
        logging.getLogger("videdit").addHandler(self.log_relay.handler)

        self._escape_time = None
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.activated.connect(self.escape_pressed)

        self.add_button.clicked.connect(self.browse_videos)
        self.remove_button.clicked.connect(self.remove_selected)
        self.file_list.currentItemChanged.connect(self._current_changed)
        self.file_list.itemSelectionChanged.connect(self.preview_timer.start)
        self.panel.changed.connect(self._options_changed)
        self.panel.crop_requested.connect(self.select_crop)
        self.command_button.clicked.connect(self.show_command)
        self.convert_button.clicked.connect(self.convert)
        self.cancel_button.clicked.connect(self.cancel)

        for problem in self.problems:
            self.log.appendPlainText("{}: {}".format("Error" if problem.fatal else "Warning",
                                                     problem.message))
        self._current_changed(None, None)

    # queue of videos

    def paths(self):
        return [self.file_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(self.file_list.count())]

    def selected_paths(self):
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.file_list.selectedItems()]

    def current_path(self):
        item = self.file_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def template(self):
        """Return the options for a new video: the ones edited last, without cut and crop area"""
        return ConversionOptions.from_dict(self.settings.options.to_dict(sticky_only=True))

    def add_videos(self, paths):
        """Append video files to the queue and select the first new one"""
        known = set(self.paths())
        first = None
        for path in paths:
            path = os.path.abspath(path)
            if path in known or not os.path.isfile(path):
                continue
            known.add(path)
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.file_list.addItem(item)
            self.file_options[path] = self.template()
            first = first or item
        if first is not None:
            self.file_list.setCurrentItem(first, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def browse_videos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add videos", "", VIDEO_FILTER)
        self.add_videos(paths)

    def remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_options.pop(item.data(Qt.ItemDataRole.UserRole), None)
            self.file_list.takeItem(self.file_list.row(item))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_videos([url.toLocalFile() for url in event.mimeData().urls()])

    def _item(self, path):
        for row in range(self.file_list.count()):
            if self.file_list.item(row).data(Qt.ItemDataRole.UserRole) == path:
                return self.file_list.item(row)
        return None

    def _current_changed(self, current, previous):
        """Show the options of the selected video"""
        path = self.current_path()
        self.panel.set_options(self.file_options[path] if path else self.template())
        self._update_enabled()
        self.update_preview()

    def _options_changed(self):
        """
        Keep the edited options for the video shown in the panel and as
        template for new ones. The changed values are also set for all other
        selected videos.
        """
        path = self.current_path()
        try:
            options = self.panel.options()
        except VideditError:
            options = None
        if path is not None and options is not None:
            previous = self.file_options[path]
            changed = {field.name: getattr(options, field.name)
                       for field in dataclasses.fields(options)
                       if getattr(options, field.name) != getattr(previous, field.name)}
            self.file_options[path] = options
            for other in self.selected_paths():
                if other != path and changed:
                    self._apply(other, changed)
            self.settings.options = options
            self.save_timer.start()
        self.preview_timer.start()

    def _apply(self, path, changed):
        """Set values for a video unless they do not fit its other options"""
        try:
            options = dataclasses.replace(self.file_options[path], **changed)
            options.validate()
        except VideditError as error:
            note = "Not changed for {}: {}".format(os.path.basename(path), error)
            if note != self._note:
                self.log.appendPlainText(note)
            self._note = note
            return
        self.file_options[path] = options

    # preview

    def index_for(self, options):
        """Return the PhotoIndex of the photo directory, None if it is not scanned yet"""
        directory = options.photo_dir
        if not directory or not os.path.isdir(directory):
            return None
        if directory not in self.indexes:
            self.indexes[directory] = None
            scanner = ScanWorker(directory, self)
            scanner.scanned.connect(self._scanned)
            self.scanners.append(scanner)
            scanner.start()
        return self.indexes[directory]

    def _scanned(self, directory, index):
        self.indexes[directory] = index
        self.scanners = [scanner for scanner in self.scanners if scanner.directory != directory]
        self.log.appendPlainText("{} photos with capture time found in {}".format(
            len(index.photos), directory))
        self.update_preview()

    def update_preview(self):
        """Tell what the conversion of the selected video will yield"""
        self.photo_label.clear()
        path = self.current_path()
        ready = False
        try:
            options = self.panel.options()
            if path is None:
                text = "Add videos to convert, e.g. by dropping them here."
            else:
                index = self.index_for(options)
                prepared = job.prepare(path, options, self.settings.tools, index)
                text = self._describe(prepared, options, index)
                others = len(set(self.selected_paths()) - {path})
                if others:
                    text += "<br><i>Changes are also set for the {} other selected " \
                            "video{}.</i>".format(others, "s" if others > 1 else "")
                ready = True
        except VideditError as error:
            text = '<span style="color: #c0392b">{}</span>'.format(error)
        self.preview_label.setText(text)
        self.ready = ready
        self._update_enabled()

    def _describe(self, prepared, options, index):
        info, capture = prepared.info, prepared.capture
        lines = ["{} × {}, {}, recorded {} (UTC{})".format(
            info.width, info.height, format_time(info.duration),
            capture.wall.strftime("%Y-%m-%d %H:%M:%S"), capture.offset)]
        for planned in prepared.jobs:
            exists = planned.target.exists() and not options.force
            lines.append("→ {}{}".format(planned.target, " <b>(exists)</b>" if exists else ""))
        if options.photo_dir:
            if not os.path.isdir(options.photo_dir):
                lines.append("The photo directory does not exist.")
            elif index is None:
                lines.append("Scanning the photos…")
            elif prepared.match is not None:
                lines.append("Related photo: {} ({:.0f} s apart)".format(
                    prepared.match.photo.path.name, prepared.match.distance))
                self._show_photo(prepared.match.photo.path)
            elif prepared.closest is not None:
                lines.append("No related photo. The closest is {} ({:.0f} s apart)".format(
                    prepared.closest.photo.path.name, prepared.closest.distance))
            else:
                lines.append("No photos with capture time in the photo directory.")
        return "<br>".join(lines)

    def _show_photo(self, path):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(QSize(THUMBNAIL, THUMBNAIL),
                                             Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if not image.isNull():
            self.photo_label.setPixmap(QPixmap.fromImage(image))
            self.photo_label.setToolTip(str(path))

    # actions

    def select_crop(self):
        """Let the user select the crop area of the current video on a snapshot"""
        path = self.current_path()
        try:
            options = self.panel.options()
            info = probe(path, self.settings.tools.ffprobe)
        except VideditError as error:
            QMessageBox.warning(self, "Crop", str(error))
            return
        dialog = CropDialog(path, info, options, self.settings.tools, self)
        if not dialog.load_snapshot():
            QMessageBox.warning(self, "Crop", "No snapshot of the video could be taken.")
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.aspect():
                self.panel.set_crop_aspect(dialog.aspect())
            self.panel.set_crop(dialog.crop())

    def show_command(self):
        """Show the ffmpeg commands for the current video"""
        try:
            path = self.current_path()
            prepared = job.prepare(path, self.panel.options(), self.settings.tools)
        except VideditError as error:
            QMessageBox.warning(self, "Command", str(error))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("ffmpeg command")
        text = QPlainTextEdit("\n\n".join(shlex.join(planned.command)
                                          for planned in prepared.jobs))
        text.setReadOnly(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(text)
        layout.addWidget(buttons)
        dialog.resize(700, 300)
        dialog.exec()

    def save_settings(self):
        """Remember the options edited last for the next video and the next start"""
        try:
            settings.save(self.settings, self.settings_path)
        except OSError as error:
            self.log.appendPlainText("Warning: the options could not be saved: {}".format(error))

    def convert(self):
        """Convert all videos of the queue, each with its own options"""
        tasks = [(path, self.file_options[path]) for path in self.paths()]
        for path in self.paths():
            self._item(path).setText(os.path.basename(path))
        self.save_settings()
        indexes = {directory: index for directory, index in self.indexes.items()
                   if index is not None}
        self.worker = ConversionWorker(tasks, self.settings.tools, indexes, self)
        self.worker.job_started.connect(self._job_started)
        self.worker.progress.connect(self._show_progress)
        self.worker.file_finished.connect(self._file_finished)
        self.worker.finished.connect(self._conversion_finished)
        self.progress.setValue(0)
        self._update_enabled()
        self.worker.start()

    def cancel(self):
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)

    def _job_started(self, path, target):
        self.log.appendPlainText("Converting {} → {}".format(os.path.basename(path), target))

    def _show_progress(self, done):
        self.progress.setValue(int(done * 1000))

    def _file_finished(self, path, error):
        item = self._item(path)
        name = os.path.basename(path)
        if error:
            self.log.appendPlainText("Failed: {}: {}".format(name, error))
        if item is not None:
            item.setText(("✗ " if error else "✓ ") + name)
            item.setToolTip("{}\n{}".format(path, error) if error else path)

    def _conversion_finished(self):
        self.worker = None
        self.log.appendPlainText("Finished.")
        self.update_preview()

    def _update_enabled(self):
        """Enable what can be used in the current state"""
        idle = self.worker is None
        selected = self.current_path() is not None
        fatal = any(problem.fatal for problem in self.problems)
        self.cancel_button.setEnabled(not idle)
        self.add_button.setEnabled(idle)
        self.remove_button.setEnabled(idle)
        self.panel.setEnabled(idle and selected)
        # invalid input for the selected video must be corrected first
        self.convert_button.setEnabled(idle and not fatal and self.file_list.count() > 0
                                       and (self.ready or not selected))
        self.command_button.setEnabled(self.ready and selected and not fatal)

    def escape_pressed(self):
        """Close the window if Escape is pressed twice in a short time"""
        now = time.monotonic()
        if self._escape_time is not None and now - self._escape_time <= ESCAPE_INTERVAL:
            self.close()
        self._escape_time = now

    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait()
        for scanner in self.scanners:
            scanner.wait()
        logging.getLogger("videdit").removeHandler(self.log_relay.handler)
        self.save_timer.stop()
        self.save_settings()
        super().closeEvent(event)
