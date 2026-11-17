# FL Studio Licheski MCP

Private. Copyright (c) 2026 Guilherme Licheski. All rights reserved (see LICENSE).

MCP server that drives **FL Studio** as a full production rig from an AI assistant: tempo, channels, mixer, plugin
parameters and presets, loading instruments from FL's browser, writing MIDI parts into patterns with sample-tight
timing, and rendering seamless loops / one-shots from FL's own playback.

## How it works
- **Bridge:** the server writes `cmd.json` next to the controller script and sends note 127 on MIDI channel 16 through
  loopMIDI; the FL script runs the command and answers in `res.json`. FL only lets scripts write inside its REAL user data
  folder, so both sides resolve it (OneDrive first).
- **Notes:** parts are played live once (each part on its own MIDI channel, routed to an FL channel), FL's score log is
  dumped into a fresh pattern and quantized (`Snap_ThirdBeat` for swing), so playback is sample-accurate.
- **Render:** FL plays the pattern while its output is recorded (Windows WASAPI loopback, separate process); the loop
  period is measured by correlation and one period is kept with an 8 ms seam crossfade. One-shots are trimmed and faded.
- **Instruments:** browser navigation by API; the final "Open in new channel" popup is confirmed with one Enter key,
  sent only after verifying that FL owns the foreground window.

## Setup (Windows)
1. FL Studio 20.7+, loopMIDI (one port), Python 3.10+, uv, ffmpeg on PATH.
2. `uv sync` then `uv run fl-licheski-install` (copies `fl_script/device_LicheskiMCP.py` into FL's Hardware folder).
3. FL: F10 > Input "loopMIDI Port" > Controller type **FL Studio Licheski MCP** > Enable. Output to loopMIDI OFF,
   "Send master sync" OFF, External clock sync OFF (otherwise MIDI loops back into FL).
4. Claude Code: `claude mcp add fl-licheski --scope user -- uv run --directory <this folder> fl-licheski-mcp`

## Tools
`fl_ping`, `fl_api_dump`, `fl_tempo`, `fl_transport`, `fl_channels`, `fl_channel`, `fl_steps`, `fl_mixer`,
`fl_plugin_params`, `fl_plugin_set`, `fl_plugin_preset`, `fl_browser`, `fl_perform`, `fl_write_parts`,
`fl_render_pattern`, `fl_render_loop`, `fl_exec`, `fl_panic`. Python helpers: `loader.load()`, `loader.pick_preset()`,
`performer.render_once()`.

Usage examples are kept outside this repository.
