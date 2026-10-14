# videdit

Convert camera videos to mp4 with ffmpeg. Videos can be cut, cropped, scaled,
rotated and faded, and the result can be placed next to the photo that was
taken at the same time.

There is a command line interface and a graphical interface. Both use the
same options.

## Requirements

- Python 3.10 or newer
- `ffmpeg` and `ffprobe`
- the Python module `exifread`, only to find related photos
- the Python module `PySide6`, only for the graphical interface

## Installation

### Run from the source directory

No installation is needed to try it out:

```
bin/videdit --help
bin/videdit-gui
```

### Install for a user

Install it into its own virtual environment and link the commands into
`~/.local/bin`. Replace `/path/to/videdit` with the directory of this
repository.

```
sudo apt install ffmpeg python3-venv
python3 -m venv ~/.local/share/videdit
~/.local/share/videdit/bin/pip install "/path/to/videdit[gui]"
ln -s ~/.local/share/videdit/bin/videdit ~/.local/bin/
ln -s ~/.local/share/videdit/bin/videdit-gui ~/.local/bin/
```

`[gui]` also installs PySide6 (about 250 MB); leave it out for the command line
only. On Ubuntu, `~/.local/bin` is on the `PATH` after the next login if the
directory exists.

To get videdit into the application menu and under "Open with" for videos,
save this as `~/.local/share/applications/videdit.desktop`, with your home
directory in `Exec`:

```
[Desktop Entry]
Type=Application
Name=videdit
Comment=Convert camera videos
Exec=/home/USER/.local/bin/videdit-gui %F
Icon=video-x-generic
Terminal=false
Categories=AudioVideo;Video;
MimeType=video/mp4;video/quicktime;video/mp2t;
```

- **Update:** run the `pip install` again with `--upgrade`.
- **Remove:** delete `~/.local/share/videdit`, the two links in `~/.local/bin`
  and the `.desktop` file. The settings are in `~/.config/videdit/`.

### Other ways to install

- **pipx** creates the environment and the links in one step:
  `sudo apt install pipx`, then `pipx install "/path/to/videdit[gui]"`.
- **Ubuntu packages instead of pip downloads:** install
  `python3-pyside6.qtwidgets` and `python3-exifread` with apt, create the
  environment with `python3 -m venv --system-site-packages`, and install
  without `[gui]`. The environment must use the system `python3`, which the
  apt packages are built for.
- **For all users:** create the environment in `/opt/videdit` and put the
  links into `/usr/local/bin`.

### Development setup

An editable install runs the code of the repository directly, so changes take
effect without reinstalling:

```
python3 -m venv .venv
.venv/bin/pip install -e ".[gui,test]"
```

## Command line

```
videdit [options] FILE...
```

| Option | Meaning |
|---|---|
| `-o DIR`, `--output-dir DIR` | Directory for the results. Default: next to the input |
| `-f`, `--force` | Overwrite existing files |
| `-n`, `--dry-run` | Only print the ffmpeg commands |
| `--preset {default,quick}` | `quick` is fast and small with reduced quality |
| `--crf N` | Video quality from 0 (best) to 51, overrides the preset |
| `--start TIME`, `--end TIME` | Cut, in seconds or as `hh:mm:ss` |
| `--fade SEC`, `--fade-black SEC`, `--no-fade` | Fade in and out. Default: 0.3 s after 0.1 s of black |
| `--scale VALUE` | Size in percent (`50%`) or as short edge (`720`). Repeatable, each yields a file |
| `--rotate {90,-90,180}`, `--flip {h,v}` | Rotate clockwise, flip |
| `--crop W:H:X:Y` | Crop area in pixels of the rotated picture |
| `--crop-aspect A:B` | Crop the centre to an aspect ratio like `16:9` |
| `--photo-dir DIR` | Search this directory for the photo taken closest to the video |
| `--photo-tolerance SEC` | Time window for a related photo. Default: 300 |
| `--rename` | Place the result next to the related photo, with its name as prefix |
| `--show-photo` | Open the related photo in the image viewer |
| `--time-offset=+HH:MM` | UTC offset of the camera clock, if the stored one is wrong |
| `--defaults` | Ignore the saved options |

Options which are not given take the value last used in the graphical
interface. The tool prints which saved options it uses; `--defaults` ignores
them, and `--no-scale`, `--no-rename` and `--no-show-photo` switch a single
one off.

Examples:

```
# 720p copy next to the input
videdit --scale 720 C0031.MP4

# seconds 5 to 20 as a square, small file
videdit --start 5 --end 20 --crop-aspect 1:1 --preset quick C0031.MP4

# place the result next to the photo taken at the same time
videdit --photo-dir ~/Pictures/2026 --rename C0031.MP4
```

The results are named after the input and what was done to it, for example
`C0031_cut_crop_720p.mp4`.

## Graphical interface

```
videdit-gui [FILE...]
```

- Add videos with the button or by dropping them onto the window.
- Every video in the queue has its own options. Select a video to see and
  change them in the right panel; changes are kept immediately.
- With several videos selected, a changed value is set for all of them.
- A new video starts with the options edited last, without cut and crop area.
- "Select area…" shows a snapshot of the video to choose the crop area with
  the mouse, optionally locked to an aspect ratio.
- The preview below the queue shows the name of the result and the related
  photo.
- "Convert" converts the whole queue, "Show command…" shows the ffmpeg
  command for the selected video.
- Pressing Escape twice closes the window.

Missing requirements are reported in a banner at the top of the window.

## Related photos

A photo is related to a video if it was taken during the recording or within
the time window before or after it. Photo dates are read from the exif data
of jpg, heic, tif, png and webp files; raw files are skipped.

The video time comes from the metadata of the camera. Sony cameras store the
local time with its UTC offset, which is used directly. For other videos the
creation time is converted with the time zone of the computer, so set the
camera UTC offset if the video was shot in another time zone.

## Metadata of the results

The results carry the capture time (shifted by the cut), the UTC offset of
the camera and, for Sony videos, make and model. Their file date is set to
the capture time.

## Settings

The options edited last are stored in `~/.config/videdit/settings.json`.

## Tests

```
python3 -m pytest
```

The tests need `pytest` and `exifread`. Tests using `ffmpeg`, PySide6 or the
example files in `testdata/` are skipped if those are missing.
