"""Loads a plugin from FL's browser (PLUGINS tab > Plugin database > <group> > <category> > <name>.fst) into a NEW
channel. Navigation uses the scripting API; only the final popup choice ('Open in new channel') needs one Enter key,
sent after verifying FL owns the foreground; focus then returns to the previous window."""
import ctypes
import time

from . import bridge, keys

GROUPS = ["Effects", "Generators", "Installed"]
GEN_CATS = ["Controller", "Drum", "MIDI", "Misc", "Patcher", "Sampler", "Synth classic", "Synth special", "Visual", "Installed"]
ST = "result = (ui.getFocusedNodeCaption(), ui.getFocusedNodeFileType())"


def _ex(code: str):
    return bridge.call("py.exec", {"code": code}, timeout=20)["result"]


def _move(d: str):
    return _ex(f"ui.navigateBrowser(midi.FPT_{d}, 0); " + ST)


def _expanded(cur: str) -> bool:
    nxt = _move("Down")
    expanded = (cur == "Plugin database" and nxt[0] in GROUPS) or (cur in GROUPS and nxt[0] in GEN_CATS + [""] and nxt[0] != cur and cur != "Installed") \
        or (cur in GEN_CATS and str(nxt[0]).endswith(".fst"))
    if nxt[0] != cur:
        _move("Up")
    return expanded


def _goto_sibling_or_child(name: str, limit: int = 300):
    c = _ex(ST)
    for _ in range(limit):
        if c[0] == name:
            return c
        c = _move("Down")
    raise RuntimeError(f"browser: '{name}' not found")


def load(category: str, plugin: str, group: str = "Generators") -> int:
    """Returns the index of the new channel."""
    before = _ex("result = channels.channelCount(True)")
    _ex("ui.showWindow(midi.widBrowser); ui.setFocused(midi.widBrowser)")
    for _ in range(8):
        if _ex("result = ui.navigateBrowserTabs(midi.FPT_Left)") == "PLUGINS":
            break
    else:
        for _ in range(8):
            if _ex("result = ui.navigateBrowserTabs(midi.FPT_Right)") == "PLUGINS":
                break
    c = _ex(ST)
    for _ in range(400):
        if c[0] == "Plugin database":
            break
        c = _move("Up")
    for node, child in (("Plugin database", group), (group, category), (category, plugin if plugin.endswith(".fst") else plugin + ".fst")):
        if not _expanded(node):
            _ex("ui.toggleBrowserNode()")
        _goto_sibling_or_child(child)
    prev = ctypes.windll.user32.GetForegroundWindow()
    try:
        if not keys.focus_fl():
            raise RuntimeError("could not bring FL Studio to the front")
        time.sleep(0.25)
        bridge.call("browser.select"); time.sleep(0.4)
        _ex("ui.navigateBrowserMenu(1, 0)"); time.sleep(0.12)
        _ex("ui.navigateBrowserMenu(1, 0)"); time.sleep(0.25)
        if not _ex("result = ui.isInPopupMenu()"):
            raise RuntimeError("browser popup did not open")
        keys.press("enter")
        time.sleep(1.5)
    finally:
        if prev:
            ctypes.windll.user32.SetForegroundWindow(prev)
    after = _ex("result = channels.channelCount(True)")
    if after <= before:
        raise RuntimeError("plugin was not loaded into a new channel")
    return after - 1


def presets(index: int, max_n: int = 400) -> list[str]:
    """Cycles once through the channel plugin's presets and returns their names (in order, starting after the current)."""
    n = min(_ex(f"result = plugins.getPresetCount({index}, -1)") or 0, max_n)
    out = []
    for _ in range(n):
        _ex(f"plugins.nextPreset({index}, -1)"); time.sleep(0.2)
        out.append(_ex(f"result = plugins.getName({index}, -1, midi.FPN_Preset)"))
    return out


def pick_preset(index: int, contains: str, max_n: int = 400) -> str:
    q = contains.lower()
    n = min(_ex(f"result = plugins.getPresetCount({index}, -1)") or 0, max_n)
    for _ in range(n):
        _ex(f"plugins.nextPreset({index}, -1)"); time.sleep(0.2)
        name = _ex(f"result = plugins.getName({index}, -1, midi.FPN_Preset)")
        if q in str(name).lower():
            return name
    raise RuntimeError(f"no preset containing '{contains}'")
