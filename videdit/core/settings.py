"""Remember the last used conversion options and the paths of the tools."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .errors import OptionsError
from .options import ConversionOptions

log = logging.getLogger(__name__)


@dataclass
class ToolPaths:
    """Names or paths of the external programs."""
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

    def missing(self):
        """Return the names of the tools which are not installed"""
        return [f.name for f in fields(self) if shutil.which(getattr(self, f.name)) is None]


@dataclass
class Settings:
    options: ConversionOptions = field(default_factory=ConversionOptions)
    tools: ToolPaths = field(default_factory=ToolPaths)


def default_path():
    """Return the location of the settings file following the XDG convention"""
    config = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config) / "videdit" / "settings.json"


def load(path=None):
    """Read the settings, a missing or broken file yields the defaults"""
    path = Path(path) if path else default_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tools = {key: value for key, value in data.get("tools", {}).items()
                 if key in {f.name for f in fields(ToolPaths)}}
        return Settings(ConversionOptions.from_dict(data.get("options", {})),
                        ToolPaths(**tools))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError, OptionsError) as error:
        log.warning("Ignoring settings file %s: %s", path, error)
    return Settings()


def save(settings, path=None):
    """Write the settings, options belonging to a single video are left out"""
    path = Path(path) if path else default_path()
    data = {"options": settings.options.to_dict(sticky_only=True),
            "tools": asdict(settings.tools)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
