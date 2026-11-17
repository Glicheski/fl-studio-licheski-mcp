# name=FL Studio Licheski MCP
# supportedDevices=FL Studio Licheski MCP
# FL Studio Licheski MCP - controller script. Copyright (c) 2026 Guilherme Licheski. All rights reserved.
#
# Bridge: the server writes cmd.json next to this script and sends note 127 on MIDI channel 16; the script runs the
# command and writes res.json. FL only lets scripts write inside its REAL user data folder (not through a junction),
# so the folder is resolved from OneDrive first.
# Live notes: MIDI channels 1-15 are routed to FL channels by the `route.set` command (FL becomes a sound module).
import json
import os
from pathlib import Path

import channels
import general
import midi
import mixer
import patterns
import plugins
import transport
import ui


def _base():
    roots = []
    od = os.environ.get("OneDrive")
    if od:
        roots += [Path(od) / "Documentos", Path(od) / "Documents"]
    roots.append(Path(os.environ.get("USERPROFILE", "~")) / "Documents")
    for r in roots:
        il = r / "Image-Line"
        try:
            if (il / "FL Studio" / "Settings").is_dir() and not il.is_junction():
                return il / "FL Studio" / "Settings" / "Hardware" / "LicheskiMCP"
        except Exception:
            pass
    return roots[-1] / "Image-Line" / "FL Studio" / "Settings" / "Hardware" / "LicheskiMCP"


DIR = _base()
CMD = DIR / "cmd.json"
RES = DIR / "res.json"
ROUTE = {}  # midi channel (0-14) -> FL global channel index
HELD = {}  # (fl channel, note) -> True, for panic


def OnInit():
    print("FL Studio Licheski MCP ready - " + str(DIR))


def OnMidiMsg(event):
    st = event.status & 0xF0
    ch = event.status & 0x0F
    if ch == 15:
        if st == 0x90 and event.data1 == 127 and event.data2 > 0:
            _run()
        event.handled = True
        return
    if ch in ROUTE and st in (0x80, 0x90):
        vel = event.data2 if st == 0x90 else 0
        idx = ROUTE[ch]
        channels.midiNoteOn(idx, event.data1, vel)
        if vel:
            HELD[(idx, event.data1)] = True
        else:
            HELD.pop((idx, event.data1), None)
        event.handled = True


def _run():
    out = {"ok": False}
    try:
        req = json.loads(CMD.read_text())
        out = {"ok": True, "id": req.get("id")}
        out.update(_do(req.get("action", ""), req.get("params") or {}) or {})
    except Exception as e:  # report every failure to the server
        out = {"ok": False, "error": type(e).__name__ + ": " + str(e)}
    try:
        RES.write_text(json.dumps(out))
    except Exception as e:
        print("Licheski MCP: cannot write response: " + str(e))


def _names(mod):
    return sorted(n for n in dir(mod) if not n.startswith("_"))


def _channel(i):
    return {
        "index": i, "name": channels.getChannelName(i), "muted": bool(channels.isChannelMuted(i)),
        "volume": round(channels.getChannelVolume(i), 3), "pan": round(channels.getChannelPan(i), 3),
        "mixer": channels.getTargetFxTrack(i), "selected": bool(channels.isChannelSelected(i)),
        "plugin": _plugin_name(i),
    }


def _plugin_name(i):
    try:
        return plugins.getPluginName(i, -1) if plugins.isValid(i, -1) else ""
    except Exception:
        return ""


def _do(a, p):
    if a == "ping":
        return {"version": general.getVersion(), "dir": str(DIR)}
    if a == "api.dump":
        mods = {"channels": channels, "mixer": mixer, "transport": transport, "ui": ui, "general": general,
                "plugins": plugins, "patterns": patterns}
        return {"api": {k: _names(m) for k, m in mods.items() if not p.get("only") or k in p["only"]}}
    if a == "midi.consts":
        pre = p.get("prefix", "")
        return {"consts": {n: getattr(midi, n) for n in dir(midi) if n.startswith(pre) and isinstance(getattr(midi, n), int)}}

    # tempo (FL stores it as BPM * 1000)
    if a == "tempo.get":
        return {"bpm": mixer.getCurrentTempo() / 1000}
    if a == "tempo.set":
        general.processRECEvent(midi.REC_Tempo, int(round(float(p["bpm"]) * 1000)), midi.REC_Control | midi.REC_UpdateControl)
        return {"bpm": mixer.getCurrentTempo() / 1000}

    # transport
    if a == "transport.start":
        if not transport.isPlaying():
            transport.start()
        return {"playing": bool(transport.isPlaying())}
    if a == "transport.stop":
        transport.stop()
        return {"playing": False}
    if a == "transport.status":
        return {"playing": bool(transport.isPlaying()), "recording": bool(transport.isRecording()),
                "pos": transport.getSongPosHint(), "loopMode": transport.getLoopMode()}
    if a == "transport.global":
        return {"result": transport.globalTransport(int(p["command"]), int(p.get("value", 1)), int(p.get("flags", midi.PME_System)))}

    # channels
    if a == "channels.list":
        return {"channels": [_channel(i) for i in range(channels.channelCount(True))]}
    if a == "channels.select":
        channels.selectOneChannel(int(p["index"]))
        return _channel(int(p["index"]))
    if a == "channels.set":
        i = int(p["index"])
        if "name" in p: channels.setChannelName(i, str(p["name"]))
        if "volume" in p: channels.setChannelVolume(i, float(p["volume"]))
        if "pan" in p: channels.setChannelPan(i, float(p["pan"]))
        if "muted" in p and bool(p["muted"]) != bool(channels.isChannelMuted(i)): channels.muteChannel(i)
        if "mixer" in p: channels.setTargetFxTrack(i, int(p["mixer"]))
        if "color" in p: channels.setChannelColor(i, int(p["color"]))
        return _channel(i)
    if a == "channels.steps":
        i, steps, n = int(p["index"]), set(p.get("on", [])), int(p.get("length", 16))
        pat = patterns.patternNumber()
        for s in range(n):
            channels.setGridBit(i, s, 1 if s in steps else 0)
        return {"pattern": pat}
    if a == "channels.note":
        channels.midiNoteOn(int(p["index"]), int(p.get("note", 60)), int(p.get("velocity", 100)))
        return {}

    # live routing
    if a == "route.set":
        ROUTE.clear()
        for k, v in (p.get("map") or {}).items():
            ROUTE[int(k)] = int(v)
        return {"route": {str(k): v for k, v in ROUTE.items()}}
    if a == "notes.panic":
        for (idx, note) in list(HELD):
            channels.midiNoteOn(idx, note, 0)
        n = len(HELD); HELD.clear()
        return {"released": n}

    # mixer
    if a == "mixer.set":
        t = int(p["track"])
        if "volume" in p: mixer.setTrackVolume(t, float(p["volume"]))
        if "pan" in p: mixer.setTrackPan(t, float(p["pan"]))
        if "name" in p: mixer.setTrackName(t, str(p["name"]))
        return {"track": t, "name": mixer.getTrackName(t), "volume": round(mixer.getTrackVolume(t), 3)}
    if a == "mixer.get":
        t = int(p["track"])
        slots = []
        for s in range(10):
            try:
                if plugins.isValid(t, s):
                    slots.append({"slot": s, "plugin": plugins.getPluginName(t, s)})
            except Exception:
                pass
        return {"track": t, "name": mixer.getTrackName(t), "volume": round(mixer.getTrackVolume(t), 3), "fx": slots}

    # plugins (slot -1 = channel generator)
    if a == "plugin.params":
        i, s = int(p["index"]), int(p.get("slot", -1))
        n = plugins.getParamCount(i, s)
        lim = int(p.get("limit", 400))
        out = []
        for k in range(min(n, lim)):
            name = plugins.getParamName(k, i, s)
            if name:
                out.append({"id": k, "name": name, "value": round(plugins.getParamValue(k, i, s), 4), "text": plugins.getParamValueString(k, i, s)})
        return {"plugin": plugins.getPluginName(i, s), "count": n, "params": out}
    if a == "plugin.set":
        i, s = int(p["index"]), int(p.get("slot", -1))
        plugins.setParamValue(float(p["value"]), int(p["id"]), i, s)
        k = int(p["id"])
        return {"name": plugins.getParamName(k, i, s), "text": plugins.getParamValueString(k, i, s)}
    if a == "plugin.preset":
        i, s = int(p["index"]), int(p.get("slot", -1))
        step = int(p.get("step", 1))
        for _ in range(abs(step)):
            (plugins.nextPreset if step > 0 else plugins.prevPreset)(i, s)
        try:
            name = plugins.getName(i, s, midi.FPN_Preset)
        except Exception:
            name = ""
        return {"preset": name}

    # browser (load instruments/presets/samples like hardware controllers do)
    if a == "browser.state":
        return {"caption": ui.getFocusedNodeCaption(), "type": ui.getFocusedNodeFileType()}
    if a == "browser.show":
        ui.showWindow(midi.widBrowser); ui.setFocused(midi.widBrowser)
        return {"caption": ui.getFocusedNodeCaption()}
    if a == "browser.nav":
        d = {"up": midi.FPT_Up, "down": midi.FPT_Down, "left": midi.FPT_Left, "right": midi.FPT_Right}[p.get("dir", "down")]
        out = []
        for _ in range(int(p.get("times", 1))):
            ui.navigateBrowser(d, int(p.get("shift", 0)))
            if p.get("trace"):
                out.append(ui.getFocusedNodeCaption())
        return {"caption": ui.getFocusedNodeCaption(), "type": ui.getFocusedNodeFileType(), "trace": out}
    if a == "browser.find":
        # walks the browser list downward (opening folders on the way) until a caption contains the query
        q = str(p["query"]).lower()
        limit = int(p.get("max", 3000))
        last = None
        for n in range(limit):
            cap = ui.getFocusedNodeCaption() or ""
            if q in cap.lower() and n > 0 or (n == 0 and q in cap.lower() and p.get("here")):
                return {"found": True, "caption": cap, "type": ui.getFocusedNodeFileType(), "steps": n}
            if ui.getFocusedNodeFileType() <= -100 and p.get("open", True) and any(f.lower() in cap.lower() for f in p.get("folders", [cap])):
                ui.navigateBrowser(midi.FPT_Right, 0)
            ui.navigateBrowser(midi.FPT_Down, 0)
            cur = ui.getFocusedNodeCaption()
            if cur == last and cur == cap:
                break
            last = cap
        return {"found": False, "caption": ui.getFocusedNodeCaption(), "steps": limit}
    if a == "browser.select":
        ui.selectBrowserMenuItem()
        return {"caption": ui.getFocusedNodeCaption(), "popup": bool(ui.isInPopupMenu())}
    if a == "browser.enter":
        transport.globalTransport(midi.FPT_Enter, 1, midi.PME_System | midi.PME_FromMIDI)
        return {"caption": ui.getFocusedNodeCaption(), "popup": bool(ui.isInPopupMenu())}
    if a == "ui.escape":
        if ui.isInPopupMenu():
            ui.closeActivePopupMenu()
        return {}
    if a == "ui.hint":
        return {"hint": ui.getHintMsg()}

    # score: what was just played lands in the pattern (FL's "Dump score log"), then quantize for sample-tight timing
    if a == "score.dump":
        general.dumpScoreLog(int(-(-float(p.get("seconds", 30)) // 1)), int(p.get("silent", 1)))
        return {"pattern": patterns.patternNumber()}
    if a == "channels.quantize":
        for i in p.get("indexes", []):
            channels.quickQuantize(int(i), int(p.get("startOnly", 1)))
        return {}
    if a == "pattern.clear":
        patterns.clearPattern(int(p.get("index", patterns.patternNumber())))
        return {"pattern": patterns.patternNumber()}
    if a == "pattern.length":
        i = int(p.get("index", patterns.patternNumber()))
        if "beats" in p:
            patterns.setPatternLength(i, int(p["beats"]))
        return {"pattern": i, "length": patterns.getPatternLength(i)}
    if a == "pattern.jump":
        patterns.jumpToPattern(int(p["index"]))
        return {"pattern": patterns.patternNumber()}
    if a == "transport.pos":
        transport.setSongPos(float(p.get("pos", 0)))
        return {"pos": transport.getSongPosHint()}
    if a == "transport.loopMode":
        if "mode" in p and int(p["mode"]) != transport.getLoopMode():
            transport.setLoopMode()
        return {"loopMode": transport.getLoopMode()}

    # escape hatch: run Python inside FL (local file + local MIDI port only). `result` is returned.
    if a == "py.exec":
        env = {"channels": channels, "general": general, "midi": midi, "mixer": mixer, "patterns": patterns,
               "plugins": plugins, "transport": transport, "ui": ui, "result": None}
        exec(str(p["code"]), env)
        r = env.get("result")
        try:
            json.dumps(r)
        except Exception:
            r = repr(r)
        return {"result": r}

    raise ValueError("unknown action " + a)
