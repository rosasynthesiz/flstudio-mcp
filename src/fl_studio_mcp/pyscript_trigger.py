"""Trigger FL's "Run last script again" hotkey from the daemon.

Windows uses the existing AttachThreadInput + synthetic-Alt focus path, then
sends Ctrl+Alt+Y. macOS activates FL Studio through AppleScript, then sends
Cmd+Opt+Y through pyautogui. The Piano Roll must be FL's active panel for the
shortcut to fire because "Run last script again" is a piano-roll command.
"""

from __future__ import annotations

import subprocess
import sys
import time


def _trigger_macos(settle=0.35):
    """Focus FL Studio on macOS and send Cmd+Opt+Y."""
    try:
        subprocess.check_call(
            ["osascript", "-e", 'tell application "FL Studio" to activate'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        focused = True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return {
            "platform": "macos",
            "fl_found": False,
            "focused": False,
            "sent_hotkey": False,
            "shortcut": "Cmd+Opt+Y",
            "error": f"{type(e).__name__}: {e}",
        }

    import pyautogui

    pyautogui.FAILSAFE = False
    time.sleep(settle)
    pyautogui.hotkey("command", "option", "y")
    return {
        "platform": "macos",
        "fl_found": True,
        "focused": focused,
        "sent_hotkey": True,
        "shortcut": "Cmd+Opt+Y",
    }


def _windows_api():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.IsIconic.argtypes = [wintypes.HWND]
    return user32, kernel32


def find_fl_hwnd():
    """Return the FL Studio main-window handle on Windows."""
    if sys.platform != "win32":
        return None
    _u, _k = _windows_api()
    _FL_WINDOW_CLASS = "TFruityLoopsMainForm"   # FL Studio main window (Delphi VCL)
    return _u.FindWindowW(_FL_WINDOW_CLASS, None)


def force_focus(hwnd):
    """Force a window to the foreground, defeating Windows foreground-lock."""
    if sys.platform != "win32":
        return False
    if not hwnd:
        return False
    _u, _k = _windows_api()
    _SW_RESTORE = 9
    _VK_MENU = 0x12          # Alt
    _KEYEVENTF_KEYUP = 0x02
    if _u.IsIconic(hwnd):
        _u.ShowWindow(hwnd, _SW_RESTORE)
    fg = _u.GetForegroundWindow()
    cur_tid = _k.GetCurrentThreadId()
    fg_tid = _u.GetWindowThreadProcessId(fg, None)
    tgt_tid = _u.GetWindowThreadProcessId(hwnd, None)
    _u.AttachThreadInput(cur_tid, fg_tid, True)
    _u.AttachThreadInput(cur_tid, tgt_tid, True)
    # A synthetic Alt tap lets SetForegroundWindow succeed under foreground-lock.
    _u.keybd_event(_VK_MENU, 0, 0, 0)
    _u.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
    _u.BringWindowToTop(hwnd)
    _u.SetForegroundWindow(hwnd)
    _u.AttachThreadInput(cur_tid, fg_tid, False)
    _u.AttachThreadInput(cur_tid, tgt_tid, False)
    return _u.GetForegroundWindow() == hwnd


def _send_ctrl_alt_y():
    """Ctrl+Alt+Y by virtual-key code, independent of the keyboard layout.

    pyautogui resolves 'y' with VkKeyScanA against the current layout. Under a
    layout without a Latin 'y' (Russian, Greek, ...) that returns -1, and
    pyautogui presses VK 0xFF instead of Y, so FL never sees the shortcut."""
    import ctypes

    u = ctypes.windll.user32
    VK_CONTROL, VK_MENU, VK_Y, KEYUP = 0x11, 0x12, 0x59, 0x02
    for vk in (VK_CONTROL, VK_MENU, VK_Y):
        u.keybd_event(vk, u.MapVirtualKeyW(vk, 0), 0, 0)
        time.sleep(0.02)
    for vk in (VK_Y, VK_MENU, VK_CONTROL):
        u.keybd_event(vk, u.MapVirtualKeyW(vk, 0), KEYUP, 0)
        time.sleep(0.02)


def _trigger_windows(settle=0.35):
    """Focus FL Studio on Windows and send Ctrl+Alt+Y."""
    hwnd = find_fl_hwnd()
    focused = force_focus(hwnd) if hwnd else False
    time.sleep(settle)
    _send_ctrl_alt_y()
    return {
        "platform": "windows",
        "fl_found": bool(hwnd),
        "focused": bool(focused),
        "sent_hotkey": True,
        "shortcut": "Ctrl+Alt+Y",
    }


def trigger_run_last_script(settle=0.35):
    """Focus FL Studio and send the platform "Run last script again" shortcut."""
    if sys.platform == "win32":
        return _trigger_windows(settle)
    if sys.platform == "darwin":
        return _trigger_macos(settle)
    return {
        "platform": sys.platform,
        "fl_found": False,
        "focused": False,
        "sent_hotkey": False,
        "shortcut": "Ctrl+Alt+Y",
        "error": "Automatic pyscript triggering is only supported on Windows and macOS.",
    }
