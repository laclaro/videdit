import gc
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from videdit.core import dependencies, settings  # noqa: E402
from videdit.core.errors import OptionsError  # noqa: E402
from videdit.core.options import ConversionOptions, CropRect  # noqa: E402
from videdit.core.probe import probe  # noqa: E402
from videdit.core.settings import Settings, ToolPaths  # noqa: E402
from videdit.gui import main_window  # noqa: E402
from videdit.gui.crop_dialog import CropDialog  # noqa: E402
from videdit.gui.main_window import MainWindow  # noqa: E402
from videdit.gui.options_panel import OptionsPanel  # noqa: E402


# the application must outlive every widget, so it is never released
_application = None


@pytest.fixture(scope="session")
def app():
    global _application
    if _application is None:
        _application = QApplication.instance() or QApplication([])
    return _application


@pytest.fixture(autouse=True)
def widgets_are_deleted_in_time(app):
    """Qt crashes at exit if widgets are deleted after the application"""
    yield
    gc.collect()


@pytest.fixture
def window(app, tmp_path):
    window = MainWindow(tmp_path / "config" / "settings.json")
    yield window
    window.close()


def select(window, row):
    """Select a single video of the queue like a mouse click does"""
    window.file_list.setCurrentRow(row, QItemSelectionModel.SelectionFlag.ClearAndSelect)


def wait_for(app, condition, timeout=30.0):
    """Process events until the condition holds"""
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timeout"
        app.processEvents()
        time.sleep(0.01)


def test_panel_shows_and_returns_options(app):
    options = ConversionOptions(
        preset="quick", crf=23, start=5.0, end=70.5, fade=0.5, fade_black=0.2,
        scales=("720", "50%", "360"), rotate=-90, flip="h", crop=CropRect(640, 360, 2, 4),
        crop_aspect="16:9", photo_dir="/photos", photo_tolerance=60.0, rename=True,
        show_photo=True, output_dir="/out", time_offset="+02:00", force=True)
    panel = OptionsPanel()
    panel.set_options(options)
    assert panel.options() == options
    assert panel.start_edit.text() == "00:00:05"
    assert panel.crop_label.text() == "640 × 360 at 2, 4"
    panel.set_options(ConversionOptions())
    assert panel.options() == ConversionOptions()


def test_panel_details(app):
    panel = OptionsPanel()
    changes = []
    panel.changed.connect(lambda: changes.append(1))
    panel.set_options(ConversionOptions(crop_aspect="2.35:1", fade=0.0))
    assert changes == []
    assert panel.options().crop_aspect == "2.35:1"
    assert not panel.fade_spin.isEnabled()
    panel.fade_check.setChecked(True)
    assert panel.options().fade == pytest.approx(0.3)
    panel.preset_combo.setCurrentIndex(1)
    assert (panel.options().preset, panel.options().crf, panel.crf_spin.value()) \
        == ("quick", None, 30)
    panel.photo_dir.setText("/photos")
    panel.rename_check.setChecked(True)
    assert panel.options().photo_dir is None and not panel.options().rename
    panel.photo_group.setChecked(True)
    assert panel.options().photo_dir == "/photos" and panel.options().rename
    panel.start_edit.setText("soon")
    with pytest.raises(OptionsError):
        panel.options()
    panel.start_edit.setText("1")
    panel.set_crop(CropRect(10, 10))
    assert (panel.options().start, panel.options().crop) == (1.0, CropRect(10, 10))
    panel.clear_crop()
    assert panel.options().crop is None
    assert len(changes) > 5


def test_window_previews_and_converts(app, window, source, make_photo, berlin, tmp_path):
    photo = make_photo(tmp_path / "photos" / "DSC0042.JPG", original="2020:04:12 15:30:30")
    out = tmp_path / "out"
    assert not window.panel.isEnabled() and not window.convert_button.isEnabled()
    window.add_videos([str(source), str(source), str(tmp_path / "missing.mp4")])
    assert window.paths() == [str(source)]
    assert window.panel.isEnabled()
    assert "640 × 360, 00:00:04, recorded 2020-04-12 15:30:00 (UTC+02:00)" \
        in window.preview_label.text()

    window.panel.output_dir.setText(str(out))
    window.panel.scale_edit.setText("180")
    window.panel.fade_check.setChecked(False)
    window.panel.photo_group.setChecked(True)
    window.panel.photo_dir.setText(str(tmp_path / "photos"))
    window.panel.end_edit.setText("1")
    window.update_preview()
    wait_for(app, lambda: "Related photo" in window.preview_label.text())
    assert "DSC0042.JPG (26 s apart)" in window.preview_label.text()
    assert str(out / "my source_cut_180p.mp4") in window.preview_label.text()
    assert window.convert_button.isEnabled()

    window.convert()
    assert not window.convert_button.isEnabled() and window.cancel_button.isEnabled()
    assert not window.panel.isEnabled()
    wait_for(app, lambda: window.worker is None)
    result = probe(out / "my source_cut_180p.mp4")
    assert (result.width, result.height) == (320, 180)
    assert result.duration == pytest.approx(1.0, abs=0.15)
    assert window.file_list.item(0).text() == "✓ my source.mp4"
    assert window.progress.value() == 1000
    assert window.panel.isEnabled()
    assert "(exists)" in window.preview_label.text()

    # the options were saved without the cut of this video
    saved = settings.load(window.settings_path).options
    assert (saved.scales, saved.output_dir, saved.fade, saved.end) \
        == (("180",), str(out), 0.0, None)

    # the existing file is not overwritten
    window.convert()
    wait_for(app, lambda: window.worker is None)
    assert window.file_list.item(0).text() == "✗ my source.mp4"
    assert "exists already" in window.log.toPlainText()
    assert photo.exists()


def test_every_video_has_its_own_options(app, window, source, tmp_path):
    first, second, third = (str(tmp_path / name) for name in ("1.mp4", "2.mp4", "3.mp4"))
    for path in (first, second, third):
        with open(path, "wb") as file:
            file.write(source.read_bytes())

    window.add_videos([first])
    window.panel.rotate_combo.setCurrentIndex(1)
    window.panel.scale_checks["720"].setChecked(True)
    window.panel.start_edit.setText("1")
    window.panel.set_crop(CropRect(100, 100, 0, 0))
    window.panel.force_check.setChecked(True)
    assert window.file_options[first] == ConversionOptions(
        rotate=90, scales=("720",), start=1.0, crop=CropRect(100, 100, 0, 0), force=True)

    # a new video starts with the options edited last, but uncut and uncropped
    window.add_videos([second])
    assert window.current_path() == second
    assert window.file_options[second] == ConversionOptions(rotate=90, scales=("720",))
    assert window.panel.options() == window.file_options[second]
    window.panel.rotate_combo.setCurrentIndex(0)
    window.panel.end_edit.setText("2")
    assert window.file_options[second] == ConversionOptions(scales=("720",), end=2.0)
    assert window.file_options[first].rotate == 90

    # selecting a video shows its options again
    select(window, 0)
    assert window.panel.options() == window.file_options[first]
    assert (window.panel.start_edit.text(), window.panel.rotate_combo.currentData()) \
        == ("00:00:01", 90)
    select(window, 1)
    assert (window.panel.end_edit.text(), window.panel.rotate_combo.currentData()) \
        == ("00:00:02", None)

    # looking at a video does not make its options the template for new ones
    select(window, 0)
    window.add_videos([third])
    assert window.file_options[third] == ConversionOptions(scales=("720",))

    window.file_list.clearSelection()
    window.file_list.item(1).setSelected(True)
    window.remove_selected()
    assert window.paths() == [first, third]
    assert set(window.file_options) == {first, third}


def test_changes_are_set_for_all_selected_videos(app, window, source, tmp_path):
    paths = [str(tmp_path / name) for name in ("1.mp4", "2.mp4", "3.mp4")]
    for path in paths:
        with open(path, "wb") as file:
            file.write(source.read_bytes())
    first, second, third = paths
    window.add_videos(paths)
    select(window, 1)
    window.panel.start_edit.setText("3")
    window.panel.flip_combo.setCurrentIndex(1)
    assert window.file_options[second] == ConversionOptions(start=3.0, flip="h")

    # the first video is shown in the panel, the second is selected as well
    select(window, 0)
    window.file_list.item(1).setSelected(True)
    assert window.selected_paths() == [first, second]
    window.update_preview()
    assert "also set for the 1 other selected video." in window.preview_label.text()
    window.panel.rotate_combo.setCurrentIndex(1)
    window.panel.scale_checks["720"].setChecked(True)
    window.panel.set_crop(CropRect(100, 100, 20, 0))
    assert window.file_options[first] == ConversionOptions(
        rotate=90, scales=("720",), crop=CropRect(100, 100, 20, 0))
    # only the changed values are set, the others stay as they were
    assert window.file_options[second] == ConversionOptions(
        rotate=90, scales=("720",), crop=CropRect(100, 100, 20, 0), start=3.0, flip="h")
    assert window.file_options[third] == ConversionOptions()

    # a value which does not fit the options of another video is not set for it
    window.panel.end_edit.setText("2")
    assert window.file_options[first].end == 2.0
    assert window.file_options[second].end is None
    assert window.log.toPlainText().count("Not changed for 2.mp4: start must be before end") == 1

    select(window, 2)
    window.panel.rotate_combo.setCurrentIndex(2)
    assert [window.file_options[path].rotate for path in paths] == [90, 90, -90]


def test_queue_is_converted_with_the_options_of_each_video(app, window, source, tmp_path):
    first, second = str(tmp_path / "1.mp4"), str(tmp_path / "2.mp4")
    for path in (first, second):
        with open(path, "wb") as file:
            file.write(source.read_bytes())
    window.add_videos([first])
    window.panel.fade_check.setChecked(False)
    window.panel.end_edit.setText("0.5")
    window.panel.scale_edit.setText("180")
    window.add_videos([second])
    window.panel.scale_edit.setText("90")
    window.panel.rotate_combo.setCurrentIndex(1)
    window.panel.end_edit.setText("0.5")
    window.convert()
    wait_for(app, lambda: window.worker is None)
    assert [window.file_list.item(row).text() for row in (0, 1)] == ["✓ 1.mp4", "✓ 2.mp4"]
    results = [probe(tmp_path / name) for name in ("1_cut_180p.mp4", "2_cut_rot90_90p.mp4")]
    assert [(r.width, r.height) for r in results] == [(320, 180), (90, 160)]


def test_dependency_warnings(app, tmp_path, source, monkeypatch):
    window = MainWindow(tmp_path / "settings.json")
    assert window.warning_label.isHidden()
    window.close()

    path = tmp_path / "broken" / "settings.json"
    settings.save(Settings(tools=ToolPaths(ffmpeg="surely-not-installed")), path)
    monkeypatch.setattr(dependencies.importlib.util, "find_spec", lambda name: None)
    window = MainWindow(path)
    assert not window.warning_label.isHidden()
    assert "surely-not-installed was not found" in window.warning_label.text()
    assert "exifread" in window.warning_label.text()
    assert "Error: surely-not-installed" in window.log.toPlainText()
    window.add_videos([str(source)])
    assert not window.convert_button.isEnabled()
    window.close()


def test_window_reports_invalid_options(app, window, source):
    window.add_videos([str(source)])
    window.panel.start_edit.setText("soon")
    window.update_preview()
    assert "Invalid time" in window.preview_label.text()
    assert not window.convert_button.isEnabled()
    window.panel.start_edit.setText("99")
    window.update_preview()
    assert "not before the end" in window.preview_label.text()


def test_escape_twice_closes_the_window(app, window, monkeypatch):
    window.show()
    window.activateWindow()
    wait_for(app, window.isActiveWindow)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    app.processEvents()
    assert window.isVisible()

    # a second press after a while does not count
    monkeypatch.setattr(main_window, "ESCAPE_INTERVAL", 0.05)
    time.sleep(0.1)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    app.processEvents()
    assert window.isVisible()

    monkeypatch.setattr(main_window, "ESCAPE_INTERVAL", 0.5)
    QTest.keyClick(window.panel.start_edit, Qt.Key.Key_Escape)
    app.processEvents()
    assert not window.isVisible()


def test_cancel(app, window, source, tmp_path):
    window.add_videos([str(source)])
    window.panel.output_dir.setText(str(tmp_path / "out"))
    window.panel.scale_edit.setText("2160")
    window.panel.crf_check.setChecked(True)
    window.panel.crf_spin.setValue(0)
    window.convert()
    window.worker.job_started.connect(lambda path, target: window.cancel())
    wait_for(app, lambda: window.worker is None)
    assert window.file_list.item(0).text() == "✗ my source.mp4"
    assert "Cancelled" in window.log.toPlainText()
    assert not list((tmp_path / "out").glob("*.mp4"))


def test_settings_are_restored(app, tmp_path, source):
    path = tmp_path / "settings.json"
    settings.save(Settings(ConversionOptions(rotate=90, scales=("720",)), ToolPaths()), path)
    window = MainWindow(path)
    assert window.panel.options().rotate == 90
    window.add_videos([str(source)])
    assert window.file_options[str(source)] == ConversionOptions(rotate=90, scales=("720",))
    window.panel.flip_combo.setCurrentIndex(1)
    window.panel.start_edit.setText("1")
    window.close()
    assert settings.load(path).options == ConversionOptions(rotate=90, scales=("720",),
                                                            flip="h")


def test_crop_dialog(app, source, info):
    dialog = CropDialog(source, info, ConversionOptions(crop_aspect="1:1"), ToolPaths())
    assert dialog.load_snapshot()
    assert dialog.view.pixmap.size().toTuple() == (640, 360)
    assert dialog.crop() == CropRect(360, 360, 140, 0)
    assert dialog.aspect() == "1:1"
    assert dialog.size_label.text() == "360 × 360 at 140, 0"

    dialog.aspect_combo.setCurrentIndex(dialog.aspect_combo.findText("Free"))
    assert dialog.aspect() is None
    dialog._reset()
    assert dialog.crop() is None

    # drag the bottom right corner of the selection to the centre of the picture
    dialog.view.resize(640, 360)
    QTest.mousePress(dialog.view, Qt.MouseButton.LeftButton, pos=QPoint(639, 359))
    QTest.mouseMove(dialog.view, QPoint(400, 200))
    QTest.mouseMove(dialog.view, QPoint(320, 180))
    QTest.mouseRelease(dialog.view, Qt.MouseButton.LeftButton, pos=QPoint(320, 180))
    assert dialog.crop() == CropRect(320, 180, 0, 0)
    assert dialog.size_label.text() == "320 × 180 at 0, 0"
    dialog.close()


def test_crop_dialog_shows_the_rotated_picture(app, source, info):
    options = ConversionOptions(rotate=90, crop=CropRect(200, 400, 80, 120))
    dialog = CropDialog(source, info, options, ToolPaths())
    assert dialog.load_snapshot()
    assert dialog.view.pixmap.size().toTuple() == (360, 640)
    assert dialog.crop() == options.crop
    dialog.close()
