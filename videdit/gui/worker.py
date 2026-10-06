"""Background threads which keep the window responsive during long operations."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QThread, Signal

from ..core import job
from ..core.errors import Cancelled, VideditError
from ..core.matching import PhotoIndex


class ScanWorker(QThread):
    """Collect the capture times of the photos of a directory."""
    scanned = Signal(str, object)

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.directory = directory

    def run(self):
        try:
            index = PhotoIndex.scan(self.directory)
        except VideditError as error:
            logging.getLogger(__name__).error("%s", error)
            index = PhotoIndex([])
        self.scanned.emit(self.directory, index)


class ConversionWorker(QThread):
    """Convert a queue of videos, each with its own options."""
    file_started = Signal(str)
    job_started = Signal(str, str)
    # overall progress between 0 and 1
    progress = Signal(float)
    # path of the video and the error message, which is empty on success
    file_finished = Signal(str, str)

    def __init__(self, tasks, tools, indexes, parent=None):
        """tasks is a list of (path, options), indexes maps photo directories to a PhotoIndex"""
        super().__init__(parent)
        self.tasks = tasks
        self.tools = tools
        self.indexes = dict(indexes)
        self._cancel = threading.Event()

    def cancel(self):
        """Stop the running conversion and skip the remaining videos"""
        self._cancel.set()

    def _index(self, options):
        if not options.photo_dir:
            return None
        if options.photo_dir not in self.indexes:
            self.indexes[options.photo_dir] = PhotoIndex.scan(options.photo_dir)
        return self.indexes[options.photo_dir]

    def _convert(self, number, path, options):
        prepared = job.prepare(path, options, self.tools, self._index(options))
        for part, planned in enumerate(prepared.jobs):
            self.job_started.emit(path, str(planned.target))

            def on_progress(fraction, part=part):
                done = number + (part + fraction) / len(prepared.jobs)
                self.progress.emit(done / len(self.tasks))

            job.run_job(planned, options, on_progress, self._cancel)

    def run(self):
        for number, (path, options) in enumerate(self.tasks):
            if self._cancel.is_set():
                break
            self.file_started.emit(path)
            try:
                self._convert(number, path, options)
            except Cancelled:
                self.file_finished.emit(path, "Cancelled")
                break
            except VideditError as error:
                self.file_finished.emit(path, str(error))
            except Exception as error:
                logging.getLogger(__name__).exception("Conversion of %s failed", path)
                self.file_finished.emit(path, "Unexpected error: {!r}".format(error))
            else:
                self.file_finished.emit(path, "")
            self.progress.emit((number + 1) / len(self.tasks))


class LogRelay(QObject):
    """Passes the log messages of all threads on as Qt signal."""
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.handler = logging.Handler(logging.WARNING)
        self.handler.emit = self._emit

    def _emit(self, record):
        try:
            self.message.emit("{}: {}".format(record.levelname.capitalize(),
                                              record.getMessage()))
        except RuntimeError:
            # the window is gone already
            pass
