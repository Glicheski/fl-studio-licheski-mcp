"""Command bridge to the FL controller script: cmd.json + note 127 on MIDI channel 16, answer in res.json."""
import itertools
import json
import threading
import time

import mido

from .paths import script_dir

_lock = threading.Lock()
_ids = itertools.count(1)
_port = None


def port():
    global _port
    if _port is None:
        names = mido.get_output_names()
        name = next((n for n in names if "loopmidi" in n.lower()), None)
        if not name:
            raise RuntimeError(f"loopMIDI port not found (outputs: {names}). Open loopMIDI and create a port.")
        _port = mido.open_output(name)
    return _port


def call(action: str, params: dict | None = None, timeout: float = 5.0) -> dict:
    d = script_dir()
    cmd, res = d / "cmd.json", d / "res.json"
    with _lock:
        rid = next(_ids)
        if res.exists():
            res.unlink()
        cmd.write_text(json.dumps({"id": rid, "action": action, "params": params or {}}))
        port().send(mido.Message("note_on", channel=15, note=127, velocity=127))
        end = time.time() + timeout
        while time.time() < end:
            if res.exists():
                try:
                    out = json.loads(res.read_text())
                except (json.JSONDecodeError, PermissionError):
                    time.sleep(0.01); continue
                res.unlink(missing_ok=True)
                if not out.get("ok"):
                    raise RuntimeError(out.get("error", "FL error"))
                return out
            time.sleep(0.005)
    raise TimeoutError("FL Studio did not answer: is FL open, loopMIDI running and the input set to 'FL Studio Licheski MCP'?")
