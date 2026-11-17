"""Plays MIDI parts live through FL (one MIDI channel per part, routed by the controller script) with tight timing,
and records FL's output (WASAPI loopback) to render seamless loops — no export dialog needed."""
import ctypes
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

import mido
import numpy as np

from . import bridge

SR = 48000


def _events(path: str) -> list[tuple[float, int, int]]:
    """(seconds, note, velocity) from a MIDI file, using its own tempo map; velocity 0 = note off."""
    t, out = 0.0, []
    for msg in mido.MidiFile(path):
        t += msg.time
        if msg.type == "note_on":
            out.append((t, msg.note, msg.velocity))
        elif msg.type == "note_off":
            out.append((t, msg.note, 0))
    return out


def loop_seconds(bpm: float, bars: int, beats_per_bar: int = 4) -> float:
    return bars * beats_per_bar * 60.0 / bpm


def perform(parts: dict[str, int], bpm: float, bars: int, passes: int = 1, stop: threading.Event | None = None) -> float:
    """parts: {midi file: FL channel index}. Returns the perf_counter time of the first downbeat."""
    if len(parts) > 15:
        raise ValueError("at most 15 parts")
    bridge.call("tempo.set", {"bpm": bpm})
    bridge.call("route.set", {"map": {str(i): ch for i, ch in enumerate(parts.values())}})
    L = loop_seconds(bpm, bars)
    sched = []
    for i, path in enumerate(parts):
        ev = _events(path)
        for k in range(passes):
            sched += [(k * L + t, i, n, v) for t, n, v in ev if t < L - 1e-6 or v == 0]
    sched.sort(key=lambda e: (e[0], e[3] != 0))  # note-offs first at equal times
    out = bridge.port()
    winmm = getattr(ctypes, "windll", None) and ctypes.windll.winmm
    if winmm:
        winmm.timeBeginPeriod(1)
    try:
        t0 = time.perf_counter() + 0.05
        for at, ch, n, v in sched:
            if stop is not None and stop.is_set():
                break
            target = t0 + at
            while True:
                left = target - time.perf_counter()
                if left <= 0:
                    break
                if left > 0.0025:
                    time.sleep(left - 0.0015)
            out.send(mido.Message("note_on", channel=ch, note=n, velocity=v))
        return t0
    finally:
        for i in range(len(parts)):
            out.send(mido.Message("control_change", channel=i, control=123, value=0))
        bridge.call("notes.panic")
        if winmm:
            winmm.timeEndPeriod(1)


def _record_proc(seconds: float, path: str, ready, done):
    """Runs in its own process: the note scheduler can never starve it (no shared GIL), so no audio is dropped."""
    import warnings
    import numpy as np
    import soundcard as sc
    warnings.simplefilter("ignore")
    mic = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
    n = int(seconds * SR)
    with mic.recorder(samplerate=SR, channels=2, blocksize=SR // 10) as r:
        r.record(numframes=SR // 20)  # warm-up
        ready.set()
        data = r.record(numframes=n)
    np.save(path, data.astype(np.float32))
    done.set()


def _record_start(seconds: float):
    import multiprocessing as mp
    import tempfile
    ctx = mp.get_context("spawn")
    path = tempfile.mktemp(suffix=".npy")
    ready, done = ctx.Event(), ctx.Event()
    proc = ctx.Process(target=_record_proc, args=(seconds, path, ready, done), daemon=True)
    proc.start()
    if not ready.wait(20):
        proc.terminate()
        raise RuntimeError("could not open the loopback recorder")
    return proc, path, done


def render_loop(parts: dict[str, int], bpm: float, bars: int, out_path: str, passes: int = 2, tail: float = 1.5) -> dict:
    """Plays the loop `passes` times while recording FL's output, then keeps exactly one loop from the last pass
    (it carries the reverb tails of the pass before it, so the file loops without a seam). Writes WAV (and OGG/MP3
    when out_path asks for it, via ffmpeg)."""
    L = loop_seconds(bpm, bars)
    pre = 0.6
    proc, path, done = _record_start(pre + passes * L + tail)
    time.sleep(pre)
    perform(parts, bpm, bars, passes)
    if not done.wait(passes * L + tail + 20):
        proc.terminate()
        raise RuntimeError("recorder did not finish")
    proc.join(5)
    audio = np.load(path)
    Path(path).unlink(missing_ok=True)
    if not len(audio):
        raise RuntimeError("nothing recorded")
    return _cut_and_save(audio, L, passes, out_path)


def write_parts(parts: dict[str, int], bpm: float, bars: int, quantize: bool = True, snap: int | None = None) -> dict:
    """Puts the parts into a new empty pattern with sample-tight timing: plays them live once, dumps FL's score log
    into the pattern, quantizes each channel and sets the pattern length to `bars`."""
    # a fresh empty pattern (clearing one asks for confirmation in FL)
    code = ("n = patterns.patternNumber()" + chr(10)
            + "while not patterns.isPatternDefault(n) and n < patterns.patternMax(): n += 1" + chr(10)
            + "patterns.jumpToPattern(n)" + chr(10) + "result = patterns.patternNumber()")
    pat = bridge.call("py.exec", {"code": code})["result"]
    L = loop_seconds(bpm, bars)
    perform(parts, bpm, bars, 1)
    time.sleep(0.3)
    bridge.call("py.exec", {"code": f"general.dumpScoreLog({int(L + 1.6)}, 1)"}, timeout=15)
    if quantize:
        # snap decides the quantize grid: None keeps FL's (16ths here); 11 = Snap_ThirdBeat for swing/triplets
        prev = bridge.call("py.exec", {"code": "result = ui.getSnapMode()"})["result"]
        if snap is not None:
            bridge.call("py.exec", {"code": f"ui.setSnapMode({int(snap)})"})
        try:
            bridge.call("channels.quantize", {"indexes": sorted(set(parts.values())), "startOnly": 1})
        finally:
            if snap is not None:
                bridge.call("py.exec", {"code": f"ui.setSnapMode({int(prev)})"})
    return bridge.call("pattern.length", {"index": pat, "beats": bars * 4})


def render_pattern(bpm: float, bars: int, out_path: str, passes: int = 2, tail: float = 1.5, tries: int = 3) -> dict:
    """Like _render_pattern_once, retried when the measured period is off (a capture glitch dropped audio)."""
    for k in range(tries):
        r = _render_pattern_once(bpm, bars, out_path, passes, tail)
        r["tries"] = k + 1
        if abs(r.get("period_err_ms", 0)) <= 0.5:
            return r
    raise RuntimeError(f"capture kept glitching (last period error {r.get('period_err_ms')} ms): close other audio apps and retry")


def _render_pattern_once(bpm: float, bars: int, out_path: str, passes: int = 2, tail: float = 1.5) -> dict:
    """FL plays the current pattern itself (sample-accurate) while its output is recorded; one seamless loop is kept."""
    L = loop_seconds(bpm, bars)
    pre = 0.6
    bridge.call("tempo.set", {"bpm": bpm})
    bridge.call("transport.stop")
    bridge.call("transport.loopMode", {"mode": 0})
    bridge.call("transport.pos", {"pos": 0})
    proc, path, done = _record_start(pre + passes * L + tail)
    time.sleep(pre)
    bridge.call("transport.start")
    if not done.wait(passes * L + tail + 20):
        proc.terminate()
        raise RuntimeError("recorder did not finish")
    bridge.call("transport.stop")
    proc.join(5)
    audio = np.load(path)
    Path(path).unlink(missing_ok=True)
    return _cut_and_save(audio, L, passes, out_path)


def _cut_and_save(audio, L: float, passes: int, out_path: str) -> dict:
    mono = np.abs(audio).max(axis=1)
    peak = float(mono.max())
    if peak < 1e-3:
        raise RuntimeError("recorded silence: is FL audible on the default Windows output and not muted?")
    # first downbeat = first point above 6% of peak (searching from the pre-roll on)
    onset = int(np.argmax(mono > peak * 0.06))
    # measure the real loop period by correlating pass 1 with pass 2 (FL's clock vs ours), then cut one period from
    # the last pass and crossfade its end into the audio just before its start: the wrap is seamless
    m = audio.mean(axis=1)
    Ls = int(round(L * SR))
    a0 = onset + Ls // 3
    ref = m[a0: a0 + SR]
    best, P = -2.0, Ls
    for lag in range(Ls - int(0.03 * SR), Ls + int(0.03 * SR)):
        cand = m[a0 + lag: a0 + lag + SR]
        if len(cand) < len(ref):
            break
        c = float(np.dot(ref, cand) / (np.linalg.norm(ref) * np.linalg.norm(cand) + 1e-9))
        if c > best:
            best, P = c, lag
    start = onset + (passes - 1) * P - int(0.004 * SR)
    seg = audio[start: start + P].copy()
    if len(seg) < P - 2:
        raise RuntimeError("recording too short for the loop")
    n = int(0.008 * SR)
    pre = audio[start - n: start]
    r = np.linspace(0, 1, n)[:, None]
    seg[-n:] = seg[-n:] * (1 - r) + pre * r
    seg = seg / max(1e-6, float(np.abs(seg).max())) * 0.89  # normalise to -1 dBFS
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wav = out.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(seg, -1, 1) * 32767).astype("<i2").tobytes())
    result = {"wav": str(wav), "seconds": round(len(seg) / SR, 3), "period_err_ms": round((P - Ls) / SR * 1000, 2), "match": round(best, 4), "peak_in": round(peak, 3), "onset_s": round(onset / SR, 3)}
    if out.suffix.lower() in (".ogg", ".mp3"):
        ff = shutil.which("ffmpeg")
        if not ff:
            raise RuntimeError("ffmpeg not found for OGG/MP3 encoding (WAV was written)")
        codec = ["-c:a", "libvorbis", "-q:a", "4"] if out.suffix.lower() == ".ogg" else ["-c:a", "libmp3lame", "-b:a", "128k"]
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(wav), *codec, str(out)], check=True)
        result["file"] = str(out); result["bytes"] = out.stat().st_size
    return result


def render_once(bpm: float, beats: float, out_path: str, tail: float = 2.5) -> dict:
    """Renders the current pattern ONCE (a jingle): records it plus its tail, trims leading/trailing silence, fades out."""
    pre = 0.6
    dur = beats * 60.0 / bpm
    bridge.call("tempo.set", {"bpm": bpm})
    bridge.call("transport.stop")
    bridge.call("transport.loopMode", {"mode": 0})
    bridge.call("transport.pos", {"pos": 0})
    proc, path, done = _record_start(pre + dur + tail)
    time.sleep(pre)
    bridge.call("transport.start")
    time.sleep(dur - 0.05)
    bridge.call("transport.stop")  # no second pass; tails keep ringing into the recording
    if not done.wait(tail + 20):
        proc.terminate()
        raise RuntimeError("recorder did not finish")
    proc.join(5)
    audio = np.load(path)
    Path(path).unlink(missing_ok=True)
    mono = np.abs(audio).max(axis=1)
    peak = float(mono.max())
    if peak < 1e-3:
        raise RuntimeError("recorded silence")
    on = max(0, int(np.argmax(mono > peak * 0.03)) - int(0.005 * SR))
    above = np.flatnonzero(mono > peak * 0.001)
    end = min(len(audio), int(above[-1]) + int(0.05 * SR))
    seg = audio[on:end].copy()
    f = min(len(seg) // 4, int(0.25 * SR))
    seg[-f:] *= np.linspace(1, 0, f)[:, None] ** 2
    seg = seg / max(1e-6, float(np.abs(seg).max())) * 0.89
    out = Path(out_path); out.parent.mkdir(parents=True, exist_ok=True)
    wav = out.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(seg, -1, 1) * 32767).astype("<i2").tobytes())
    result = {"wav": str(wav), "seconds": round(len(seg) / SR, 3)}
    if out.suffix.lower() in (".ogg", ".mp3"):
        ff = shutil.which("ffmpeg")
        codec = ["-c:a", "libvorbis", "-q:a", "4"] if out.suffix.lower() == ".ogg" else ["-c:a", "libmp3lame", "-b:a", "128k"]
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(wav), *codec, str(out)], check=True)
        result["file"] = str(out); result["bytes"] = out.stat().st_size
    return result
