"""
win32_probe.py — Isolated, pure Win32 Native Desktop Wallpaper Probe for Lyrune.

Used strictly for diagnosing Windows 11 desktop composition and host visibility.
Does NOT modify user wallpaper settings, does NOT call SPI_SETDESKWALLPAPER,
and does NOT involve Qt or any wallpaper renderers.
"""

import sys
import os
import time
import ctypes
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple

from lyrune.logger import log_event

if sys.platform != "win32":
    raise ImportError("win32_probe.py is only available on Windows")

# ------------------------------------------------------------------
# Win32 API ctypes prototypes
# ------------------------------------------------------------------

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

# Functions
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND

SMTO_ABORTIFHUNG = 0x0002
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)
]
user32.SendMessageTimeoutW.restype = wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.restype = wintypes.BOOL

user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND

user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.SetParent.restype = wintypes.HWND

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long

user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL

user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ScreenToClient.restype = wintypes.BOOL

user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.IsWindowEnabled.argtypes = [wintypes.HWND]
user32.IsWindowEnabled.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint
]
user32.SetWindowPos.restype = wintypes.BOOL

user32.UpdateWindow.argtypes = [wintypes.HWND]
user32.UpdateWindow.restype = wintypes.BOOL

user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
user32.InvalidateRect.restype = wintypes.BOOL

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC

user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.FillRect.restype = ctypes.c_int

gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH

gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL

user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND

user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long,
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
]
user32.CreateWindowExW.restype = wintypes.HWND

user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL

user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
    ]

user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wintypes.BOOL

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]

gdi32.SetDIBitsToDevice.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT
]
gdi32.SetDIBitsToDevice.restype = ctypes.c_int

# Win32 Constants
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
WS_EX_LAYERED = 0x00080000
WS_EX_NOREDIRECTIONBITMAP = 0x00200000

LWA_ALPHA = 0x00000002
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SW_SHOW = 5
SW_HIDE = 0
GW_HWNDPREV = 3
GW_HWNDNEXT = 2

PROGMAN_SPAWN_WORKERW = 0x052C
MAGENTA_COLORREF = 0x00FF00FF  # 0x00BBGGRR -> B=255, G=0, R=255 -> Solid Magenta


def _get_class_name(hwnd: int) -> str:
    if not hwnd or not user32.IsWindow(hwnd):
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _get_window_text(hwnd: int) -> str:
    if not hwnd or not user32.IsWindow(hwnd):
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def _get_rect_str(hwnd: int) -> str:
    if not hwnd or not user32.IsWindow(hwnd):
        return "None"
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return f"({r.left},{r.top} -> {r.right},{r.bottom} [{r.right-r.left}x{r.bottom-r.top}])"


def _get_client_rect_str(hwnd: int) -> str:
    if not hwnd or not user32.IsWindow(hwnd):
        return "None"
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return f"({r.left},{r.top} -> {r.right},{r.bottom} [{r.right-r.left}x{r.bottom-r.top}])"


def _attach_default_desktop():
    """Attaches current thread to interactive Default desktop if not already attached."""
    try:
        user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user32.OpenDesktopW.restype = wintypes.HANDLE
        user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
        user32.SetThreadDesktop.restype = wintypes.BOOL

        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass


class NativeDesktopProbe:
    """
    Isolated native Win32 Desktop Wallpaper Diagnostic Probe.
    Creates exactly ONE pure Win32 solid MAGENTA (#FF00FF) window,
    parents it into candidate hosts, and evaluates the desktop composition layer.
    """

    def __init__(self):
        self._class_registered = False
        self._probe_hwnd = 0
        self._active_host_hwnd = 0
        self._wndproc_cb = None
        self._hbrush_magenta = 0

    def _ensure_class_registered(self) -> bool:
        if self._class_registered:
            return True

        hinst = kernel32.GetModuleHandleW(None)
        self._hbrush_bg = gdi32.CreateSolidBrush(0x00000000)

        def _probe_wndproc(hwnd, msg, wparam, lparam):
            if msg == 0x000F:  # WM_PAINT
                ps = PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                if hdc:
                    hb = gdi32.CreateSolidBrush(0x00000000)
                    user32.FillRect(hdc, ctypes.byref(ps.rcPaint), hb)
                    gdi32.DeleteObject(hb)
                    user32.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            elif msg == 0x0014:  # WM_ERASEBKGND
                rc = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rc))
                hdc = wintypes.HDC(wparam) if wparam else user32.GetDC(hwnd)
                if hdc:
                    hb = gdi32.CreateSolidBrush(0x00000000)
                    user32.FillRect(hdc, ctypes.byref(rc), hb)
                    gdi32.DeleteObject(hb)
                    if not wparam:
                        user32.ReleaseDC(hwnd, hdc)
                return 1
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_cb = WNDPROC(_probe_wndproc)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 3  # CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = self._wndproc_cb
        wc.hInstance = hinst
        wc.hbrBackground = self._hbrush_bg
        wc.lpszClassName = "LyruneNativeDesktopProbe"

        user32.UnregisterClassW("LyruneNativeDesktopProbe", hinst)
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        self._class_registered = bool(atom)
        return self._class_registered

    def get_surface_size(self) -> Tuple[int, int]:
        """Returns the physical screen pixel size (width, height) of the desktop host surface."""
        sm_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        sm_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        w = max(sm_w, 1920)
        h = max(sm_h, 1080)
        return w, h

    def create_probe_window(self, parent_hwnd: int, is_layered: bool = False) -> int:
        """Creates a pure Win32 window parented into parent_hwnd covering the entire screen."""
        if not self._ensure_class_registered():
            log_event("[Native Probe] Failed to register Win32 probe window class.")
            return 0

        hinst = kernel32.GetModuleHandleW(None)
        w, h = self.get_surface_size()

        exstyle = WS_EX_LAYERED if is_layered else 0
        style = WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS

        hwnd = user32.CreateWindowExW(
            exstyle,
            "LyruneNativeDesktopProbe",
            "Lyrune Native Probe Surface",
            style,
            0, 0, w, h,
            parent_hwnd, 0, hinst, None
        )

        if hwnd:
            if is_layered:
                user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
            user32.SetWindowPos(
                hwnd, 0, 0, 0, w, h,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
            )
            user32.ShowWindow(hwnd, SW_SHOW)
            user32.UpdateWindow(hwnd)

        return hwnd

    def destroy_probe_window(self, hwnd: int) -> None:
        """Safely destroys the probe window."""
        if hwnd and user32.IsWindow(hwnd):
            user32.ShowWindow(hwnd, SW_HIDE)
            user32.DestroyWindow(hwnd)

    def render_image(self, img) -> bool:
        """
        Blits a Qt QImage directly to the native desktop host surface
        using Win32 GDI SetDIBitsToDevice.
        """
        if not self._probe_hwnd or not user32.IsWindow(self._probe_hwnd) or img is None or img.isNull():
            return False

        w, h = img.width(), img.height()
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        hdc = user32.GetDC(self._probe_hwnd)
        if not hdc:
            return False

        try:
            ptr = int(img.constBits())
            lines = gdi32.SetDIBitsToDevice(
                hdc, 0, 0, w, h, 0, 0, 0, h,
                ctypes.c_void_p(ptr), ctypes.byref(bmi), 0
            )
            return lines > 0
        finally:
            user32.ReleaseDC(self._probe_hwnd, hdc)

    def _get_z_order_neighbors(self, hwnd: int) -> Tuple[List[str], List[str]]:
        """Collects surrounding windows above and below hwnd in Z-order."""
        above = []
        curr = user32.GetWindow(hwnd, GW_HWNDPREV)
        while curr and len(above) < 5:
            cls = _get_class_name(curr)
            vis = bool(user32.IsWindowVisible(curr))
            title = _get_window_text(curr)
            above.append(f"0x{curr:08X} ({cls}, vis={vis}, title='{title[:15]}')")
            curr = user32.GetWindow(curr, GW_HWNDPREV)

        below = []
        curr = user32.GetWindow(hwnd, GW_HWNDNEXT)
        while curr and len(below) < 5:
            cls = _get_class_name(curr)
            vis = bool(user32.IsWindowVisible(curr))
            title = _get_window_text(curr)
            below.append(f"0x{curr:08X} ({cls}, vis={vis}, title='{title[:15]}')")
            curr = user32.GetWindow(curr, GW_HWNDNEXT)

        return above, below

    def diagnose(self) -> Dict:
        """
        Executes complete desktop hierarchy enumeration and tests all candidate hosts.
        Returns diagnostic summary dictionary.
        """
        _attach_default_desktop()

        report = {
            "progman": 0,
            "progman_exstyle": 0,
            "has_no_redirection": False,
            "host_mode": "UNKNOWN",
            "defview": 0,
            "defview_parent": 0,
            "candidates": [],
            "selected_host": 0,
        }

        log_event("=" * 70)
        log_event("[Native Probe] ================= DESKTOP HOST DIAGNOSTIC =================")

        progman = user32.FindWindowW("Progman", None) or 0
        report["progman"] = progman
        if not progman:
            log_event("[Native Probe] ERROR: Progman window not found.")
            return report

        exstyle = user32.GetWindowLongW(progman, GWL_EXSTYLE)
        style = user32.GetWindowLongW(progman, GWL_STYLE)
        has_no_redir = bool(exstyle & WS_EX_NOREDIRECTIONBITMAP)
        report["progman_exstyle"] = exstyle
        report["has_no_redirection"] = has_no_redir
        report["host_mode"] = "RAISED_DESKTOP" if has_no_redir else "CLASSIC_WORKERW"

        log_event(
            f"[Native Probe] Progman: 0x{progman:08X} | Style: 0x{style:08X} | ExStyle: 0x{exstyle:08X} | "
            f"WS_EX_NOREDIRECTIONBITMAP: {has_no_redir} -> Host Mode: {report['host_mode']}"
        )

        # 1. Enumerate children of Progman
        progman_children = []
        def _enum_progman_children(chwnd, _lparam):
            progman_children.append(chwnd)
            return True
        user32.EnumChildWindows(progman, WNDENUMPROC(_enum_progman_children), 0)

        log_event(f"[Native Probe] Progman has {len(progman_children)} child window(s):")
        for idx, ch in enumerate(progman_children, 1):
            ccls = _get_class_name(ch)
            cvis = bool(user32.IsWindowVisible(ch))
            log_event(f"    ├── [{idx:02d}] 0x{ch:08X} | Class: {ccls:16s} | Vis: {str(cvis):5s} | Rect: {_get_rect_str(ch)}")

        # 2. Locate SHELLDLL_DefView
        shell_defview = user32.FindWindowExW(0, 0, "SHELLDLL_DefView", None)
        if not shell_defview and progman:
            shell_defview = user32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)

        defview_parent = user32.GetParent(shell_defview) if shell_defview else 0
        report["defview"] = shell_defview or 0
        report["defview_parent"] = defview_parent

        log_event(
            f"[Native Probe] SHELLDLL_DefView: 0x{shell_defview:08X} | "
            f"Parent: 0x{defview_parent:08X} ({_get_class_name(defview_parent)}) | "
            f"Vis: {bool(user32.IsWindowVisible(shell_defview)) if shell_defview else False}"
        )

        # 3. Spawn WorkerW sequence without altering user wallpaper
        res = ctypes.c_void_p(0)
        log_event("[Native Probe] Sending 0x052C spawn messages to Progman...")
        user32.SendMessageTimeoutW(progman, PROGMAN_SPAWN_WORKERW, 0x0000000D, 0x00000001, SMTO_ABORTIFHUNG, 1000, ctypes.byref(res))
        user32.SendMessageTimeoutW(progman, PROGMAN_SPAWN_WORKERW, 0x0000000D, 0x00000000, SMTO_ABORTIFHUNG, 1000, ctypes.byref(res))
        user32.SendMessageTimeoutW(progman, PROGMAN_SPAWN_WORKERW, 0, 0, SMTO_ABORTIFHUNG, 1000, ctypes.byref(res))

        # 4. Collect Candidate WorkerWs
        candidates = []

        # Candidate pool A: Child WorkerWs of Progman
        for ch in progman_children:
            if _get_class_name(ch) == "WorkerW":
                has_sv = bool(user32.FindWindowExW(ch, 0, "SHELLDLL_DefView", None))
                if not has_sv and ch not in candidates:
                    candidates.append({"hwnd": ch, "type": "Progman Child WorkerW"})

        # Candidate pool B: Top-level WorkerWs
        def _enum_top_workerw(hwnd, _lparam):
            if _get_class_name(hwnd) == "WorkerW":
                has_sv = bool(user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None))
                if not has_sv and hwnd not in [c["hwnd"] for c in candidates]:
                    candidates.append({"hwnd": hwnd, "type": "Top-Level WorkerW"})
            return True
        user32.EnumWindows(WNDENUMPROC(_enum_top_workerw), 0)

        log_event(f"[Native Probe] Discovered {len(candidates)} candidate WorkerW host(s):")
        report["candidates"] = candidates

        # 5. Evaluate and test each candidate
        for idx, cand in enumerate(candidates, 1):
            chwnd = cand["hwnd"]
            cparent = user32.GetParent(chwnd) or 0
            cvis = bool(user32.IsWindowVisible(chwnd))
            crect = _get_rect_str(chwnd)
            cclient = _get_client_rect_str(chwnd)

            log_event(f"\n[Native Probe] --- Testing Candidate #{idx}: 0x{chwnd:08X} ({cand['type']}) ---")
            log_event(f"    Parent: 0x{cparent:08X} | Vis: {cvis} | Rect: {crect} | Client: {cclient}")

            above, below = self._get_z_order_neighbors(chwnd)
            for a in above:
                log_event(f"    ↑ [ABOVE] {a}")
            log_event(f"    ★ [HOST ] 0x{chwnd:08X} ({_get_class_name(chwnd)})")
            for b in below:
                log_event(f"    ↓ [BELOW] {b}")

            # Test standard child probe
            probe1 = self.create_probe_window(chwnd, is_layered=False)
            p1_vis = bool(user32.IsWindowVisible(probe1)) if probe1 else False
            log_event(f"    -> Standard Child Probe: HWND=0x{probe1:08X}, Vis={p1_vis}, Rect={_get_rect_str(probe1)}")
            time.sleep(0.05)
            self.destroy_probe_window(probe1)

            # Test layered child probe
            probe2 = self.create_probe_window(chwnd, is_layered=True)
            p2_vis = bool(user32.IsWindowVisible(probe2)) if probe2 else False
            log_event(f"    -> Layered Child Probe:  HWND=0x{probe2:08X}, Vis={p2_vis}, Rect={_get_rect_str(probe2)}")
            time.sleep(0.05)
            self.destroy_probe_window(probe2)

        # Select primary candidate
        if candidates:
            # Prefer visible candidate
            selected = None
            for c in candidates:
                if user32.IsWindowVisible(c["hwnd"]):
                    selected = c["hwnd"]
                    break
            if not selected:
                selected = candidates[0]["hwnd"]
            report["selected_host"] = selected
            log_event(f"\n[Native Probe] Selected Primary Host: 0x{selected:08X} ({_get_class_name(selected)})")

        log_event("=" * 70)
        return report

    def start(self) -> bool:
        """
        Starts the native probe on the best host candidate.
        Paints solid bright MAGENTA (#FF00FF) directly to the desktop substrate.
        """
        diag = self.diagnose()
        host = diag.get("selected_host", 0)
        if not host:
            log_event("[Native Probe] ERROR: No valid host window to start probe.")
            return False

        self._active_host_hwnd = host
        is_layered = diag.get("host_mode") == "RAISED_DESKTOP"
        self._probe_hwnd = self.create_probe_window(host, is_layered=is_layered)

        if self._probe_hwnd:
            log_event(
                f"[Native Probe] Native MAGENTA probe window ACTIVE on HWND 0x{self._probe_hwnd:08X} "
                f"(Host: 0x{host:08X}, Layered: {is_layered}, Size: {_get_rect_str(self._probe_hwnd)})"
            )
            return True
        else:
            log_event("[Native Probe] Failed to create active probe window.")
            return False

    def stop(self) -> None:
        """Stops and cleans up the native probe."""
        if self._probe_hwnd:
            self.destroy_probe_window(self._probe_hwnd)
            self._probe_hwnd = 0
        self._active_host_hwnd = 0
        if self._hbrush_magenta:
            gdi32.DeleteObject(self._hbrush_magenta)
            self._hbrush_magenta = 0
        log_event("[Native Probe] Native probe stopped.")
