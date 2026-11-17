"""Copies the controller script into FL Studio (Settings/Hardware/LicheskiMCP)."""
import shutil
from pathlib import Path

from .paths import script_dir


def main():
    src = Path(__file__).resolve().parents[2] / "fl_script" / "device_LicheskiMCP.py"
    dst = script_dir()
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst / src.name)
    print(f"installed {dst / src.name}")
    print("FL Studio: F10 > Input: loopMIDI Port > Controller type: FL Studio Licheski MCP > Enable")
