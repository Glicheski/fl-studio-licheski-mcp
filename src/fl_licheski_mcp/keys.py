"""Keystrokes to FL Studio for the few UI actions the scripting API cannot do (confirming a browser popup menu).
Safety: a key is sent ONLY after verifying that FL Studio owns the foreground window; otherwise nothing is typed."""
import ctypes
import time
from ctypes import wintypes

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
VK = {"enter": 0x0D, "esc": 0x1B, "down": 0x28, "up": 0x26, "alt": 0x12}


def _pid_of(h) -> int:
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value


def _exe(pid: int) -> str:
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(520); n = wintypes.DWORD(520)
    k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)); k32.CloseHandle(h)
    return buf.value.lower()


def fl_is_foreground() -> bool:
    return _exe(_pid_of(u32.GetForegroundWindow())).endswith(("fl64.exe", "fl.exe"))


def _fl_main_window():
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if u32.IsWindowVisible(h) and _exe(_pid_of(h)).endswith(("fl64.exe", "fl.exe")) and u32.GetWindowTextLengthW(h) > 0:
            found.append(h)
        return True
    u32.EnumWindows(cb, 0)
    return found[0] if found else None


def focus_fl(timeout: float = 2.0) -> bool:
    if fl_is_foreground():
        return True
    h = _fl_main_window()
    if not h:
        return False
    # Windows only lets the foreground app hand focus over; a synthetic Alt tap unlocks SetForegroundWindow
    u32.keybd_event(VK["alt"], 0, 0, 0); u32.keybd_event(VK["alt"], 0, 2, 0)
    u32.SetForegroundWindow(h)
    end = time.time() + timeout
    while time.time() < end:
        if fl_is_foreground():
            return True
        time.sleep(0.05)
    return False


def press(key: str) -> None:
    if not fl_is_foreground():
        raise RuntimeError("FL Studio is not the foreground window: key not sent")
    vk = VK[key]
    u32.keybd_event(vk, 0, 0, 0); time.sleep(0.02); u32.keybd_event(vk, 0, 2, 0)
