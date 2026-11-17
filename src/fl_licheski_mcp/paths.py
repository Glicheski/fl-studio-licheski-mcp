"""Where FL Studio keeps its user data (often redirected to OneDrive on Windows)."""
import os
from pathlib import Path


def fl_settings() -> Path:
    roots = []
    od = os.environ.get("OneDrive")
    if od:
        roots += [Path(od) / "Documentos", Path(od) / "Documents"]
    roots.append(Path.home() / "Documents")
    for r in roots:
        il = r / "Image-Line"
        if (il / "FL Studio" / "Settings").is_dir():
            return (il / "FL Studio" / "Settings").resolve()
    return roots[-1] / "Image-Line" / "FL Studio" / "Settings"


def script_dir() -> Path:
    return fl_settings() / "Hardware" / "LicheskiMCP"
