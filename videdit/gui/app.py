"""Start the graphical interface."""

import gc
import sys


def main(argv=None):
    """Open the main window, video files given as arguments are added to the list"""
    argv = sys.argv if argv is None else argv
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("The graphical interface needs PySide6, e.g. from the package "
              "python3-pyside6.qtwidgets or with: pip install PySide6", file=sys.stderr)
        return 2
    from .main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName("videdit")
    window = MainWindow()
    window.add_videos(argv[1:])
    window.show()
    status = app.exec()
    # Qt crashes if widgets outlive the application, so the window goes first
    del window
    gc.collect()
    return status


if __name__ == "__main__":
    sys.exit(main())
