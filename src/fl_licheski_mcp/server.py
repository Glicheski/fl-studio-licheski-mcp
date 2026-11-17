"""FL Studio Licheski MCP server. Copyright (c) 2026 Guilherme Licheski. All rights reserved.

Drives FL Studio as a production rig: tempo, channels, mixer, plugin params/presets, browser (load instruments),
live playback of MIDI arrangements through FL's instruments, and seamless loop rendering from FL's audio output.
"""
from fastmcp import FastMCP

from . import bridge, performer

mcp = FastMCP("FL Studio Licheski MCP")


@mcp.tool()
def fl_ping() -> dict:
    """Checks the link to FL Studio (version and script folder)."""
    return bridge.call("ping")


@mcp.tool()
def fl_api_dump(only: list[str] | None = None) -> dict:
    """Lists FL's scripting API functions per module (channels, mixer, transport, ui, general, plugins, patterns)."""
    return bridge.call("api.dump", {"only": only or []}, timeout=10)


@mcp.tool()
def fl_tempo(bpm: float | None = None) -> dict:
    """Gets the tempo, or sets it when bpm is given."""
    return bridge.call("tempo.set", {"bpm": bpm}) if bpm else bridge.call("tempo.get")


@mcp.tool()
def fl_transport(action: str = "status") -> dict:
    """Transport: 'start', 'stop' or 'status'."""
    return bridge.call(f"transport.{action}")


@mcp.tool()
def fl_channels() -> dict:
    """Lists channel rack channels with name, plugin, volume, pan, mute and mixer track."""
    return bridge.call("channels.list")


@mcp.tool()
def fl_channel(index: int, select: bool = False, name: str | None = None, volume: float | None = None, pan: float | None = None,
               muted: bool | None = None, mixer: int | None = None, color: int | None = None) -> dict:
    """Edits one channel (volume 0..1, pan -1..1, mixer track, color as 0xRRGGBB); `select` makes it the only selected one
    (the browser loads into the selected channel)."""
    if select:
        bridge.call("channels.select", {"index": index})
    p = {k: v for k, v in dict(name=name, volume=volume, pan=pan, muted=muted, mixer=mixer, color=color).items() if v is not None}
    return bridge.call("channels.set", {"index": index, **p})


@mcp.tool()
def fl_steps(index: int, on: list[int], length: int = 16) -> dict:
    """Sets a channel's step sequencer row (steps listed in `on` are lit) in the current pattern."""
    return bridge.call("channels.steps", {"index": index, "on": on, "length": length})


@mcp.tool()
def fl_mixer(track: int, volume: float | None = None, pan: float | None = None, name: str | None = None) -> dict:
    """Edits a mixer track (volume 0..1, pan -1..1) and reports its effects."""
    p = {k: v for k, v in dict(volume=volume, pan=pan, name=name).items() if v is not None}
    if p:
        bridge.call("mixer.set", {"track": track, **p})
    return bridge.call("mixer.get", {"track": track})


@mcp.tool()
def fl_plugin_params(index: int, slot: int = -1, limit: int = 400) -> dict:
    """Parameters of a plugin: channel generator (slot -1, index = channel) or mixer effect (index = track, slot 0-9)."""
    return bridge.call("plugin.params", {"index": index, "slot": slot, "limit": limit}, timeout=15)


@mcp.tool()
def fl_plugin_set(index: int, param: int, value: float, slot: int = -1) -> dict:
    """Sets a plugin parameter (value 0..1)."""
    return bridge.call("plugin.set", {"index": index, "slot": slot, "id": param, "value": value})


@mcp.tool()
def fl_plugin_preset(index: int, step: int = 1, slot: int = -1) -> dict:
    """Moves a plugin to the next (step>0) or previous preset and returns its name."""
    return bridge.call("plugin.preset", {"index": index, "slot": slot, "step": step})


@mcp.tool()
def fl_browser(action: str = "state", direction: str = "down", times: int = 1, query: str | None = None, max_steps: int = 3000,
               folders: list[str] | None = None) -> dict:
    """FL browser: 'show', 'state', 'nav' (direction up/down/left/right, times), 'find' (query; walks down opening
    folders whose name is in `folders`, or all when omitted), 'select' (loads the focused item into the selected
    channel), 'enter' (open/close folder), 'escape' (close popup)."""
    if action == "nav":
        return bridge.call("browser.nav", {"dir": direction, "times": times, "trace": times <= 40})
    if action == "find":
        p = {"query": query or "", "max": max_steps}
        if folders:
            p["folders"] = folders
        return bridge.call("browser.find", p, timeout=60)
    if action == "escape":
        return bridge.call("ui.escape")
    return bridge.call(f"browser.{action}")


@mcp.tool()
def fl_perform(parts: dict[str, int], bpm: float, bars: int = 8, passes: int = 1) -> dict:
    """Plays MIDI files live through FL instruments: parts = {path to .mid: FL channel index}. Each part gets its own
    MIDI channel, so chords and several instruments play together, in time."""
    t0 = performer.perform(parts, bpm, bars, passes)
    return {"ok": True, "seconds": round(performer.loop_seconds(bpm, bars) * passes, 2), "t0": t0}


@mcp.tool()
def fl_render_loop(parts: dict[str, int], bpm: float, out_path: str, bars: int = 8, passes: int = 2) -> dict:
    """Renders a seamless loop: plays the parts `passes` times while recording FL's output (Windows loopback) and keeps
    the last pass (it carries the previous pass' reverb tails). Writes WAV, plus OGG/MP3 when out_path ends so.
    Keep other sounds quiet while it records."""
    return performer.render_loop(parts, bpm, bars, out_path, passes)


@mcp.tool()
def fl_write_parts(parts: dict[str, int], bpm: float, bars: int = 8, quantize: bool = True) -> dict:
    """Writes MIDI files into the CURRENT pattern (cleared first), one per channel: parts = {path to .mid: FL channel
    index}. Plays them once, dumps FL's score log into the pattern and quantizes, so playback is sample-tight."""
    return performer.write_parts(parts, bpm, bars, quantize)


@mcp.tool()
def fl_render_pattern(bpm: float, out_path: str, bars: int = 8, passes: int = 2) -> dict:
    """Renders the current pattern as a seamless loop: FL plays it (sample-accurate) while its output is recorded;
    the last pass is kept. Writes WAV, plus OGG/MP3 when out_path ends so. Keep other sounds quiet meanwhile."""
    return performer.render_pattern(bpm, bars, out_path, passes)


@mcp.tool()
def fl_exec(code: str) -> dict:
    """Runs Python inside FL Studio (modules channels, mixer, patterns, plugins, transport, ui, general, midi);
    assign `result` to return a value."""
    return bridge.call("py.exec", {"code": code}, timeout=30)


@mcp.tool()
def fl_panic() -> dict:
    """Releases every held note."""
    return bridge.call("notes.panic")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
