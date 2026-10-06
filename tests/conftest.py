import shutil
import struct
import subprocess
import time
from pathlib import Path

import pytest

from videdit.core.probe import probe


@pytest.fixture(scope="session")
def ffmpeg():
    """Skip the test if the real ffmpeg and ffprobe are not installed"""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required")


@pytest.fixture(scope="session")
def source(ffmpeg, tmp_path_factory):
    """A generated test video of 4 seconds, 640x360 with sound"""
    path = tmp_path_factory.mktemp("source") / "my source.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=640x360:rate=25:duration=4", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=4", "-c:v", "libx264", "-preset",
                    "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-metadata",
                    "creation_time=2020-04-12T13:30:00Z", str(path)],
                   check=True)
    return path


@pytest.fixture(scope="session")
def info(source):
    return probe(source)


@pytest.fixture
def computer_timezone(monkeypatch):
    """Return a function setting the time zone of the computer for the test"""
    def set_zone(zone):
        monkeypatch.setenv("TZ", zone)
        time.tzset()
    yield set_zone
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def berlin(computer_timezone):
    """Let the computer be in the time zone Europe/Berlin"""
    computer_timezone("Europe/Berlin")


@pytest.fixture
def make_photo():
    """Return a function writing a minimal JPEG file with the given exif dates"""
    def make(path, original=None, digitized=None):
        dates = [(tag, text.encode() + b"\0")
                 for tag, text in ((0x9003, original), (0x9004, digitized)) if text]
        # TIFF header, IFD0 pointing to the exif IFD at offset 26
        tiff = b"II*\0" + struct.pack("<IHHHIII", 8, 1, 0x8769, 4, 1, 26, 0)
        data_offset = 26 + 2 + 12 * len(dates) + 4
        tiff += struct.pack("<H", len(dates))
        for index, (tag, value) in enumerate(dates):
            tiff += struct.pack("<HHII", tag, 2, len(value), data_offset + 20 * index)
        tiff += struct.pack("<I", 0) + b"".join(value for _, value in dates)
        exif = b"Exif\0\0" + tiff
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
                         + b"\xff\xd9")
        return path
    return make


@pytest.fixture
def make_sony_video():
    """Return a function writing the skeleton of an MP4 file with the metadata of a Sony camera"""
    def make(path, creation_date):
        xml = '<NonRealTimeMeta><CreationDate value="{}"/></NonRealTimeMeta>'.format(creation_date)
        meta = b"\0\0\0\0" + xml.encode()
        path.write_bytes(struct.pack(">I4s4s", 12, b"ftyp", b"XAVC")
                         + struct.pack(">I4sQ", 1, b"mdat", 16 + 100) + bytes(100)
                         + struct.pack(">I4s", 8 + len(meta), b"meta") + meta)
        return path
    return make


@pytest.fixture(scope="session")
def testdata():
    """Directory with a clip of a Sony camera, its XML file and a photo of the same minute"""
    directory = Path(__file__).parent.parent / "testdata"
    if not all((directory / name).exists()
               for name in ("C0031.MP4", "C0031M01.XML", "DSC02287.JPG")):
        pytest.skip("the example files in testdata are required")
    return directory
