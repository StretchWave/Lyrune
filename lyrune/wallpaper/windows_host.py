"""
windows_host.py — Windows desktop wallpaper hosting via WorkerW technique.

Manages embedding a Qt rendering surface behind the Windows desktop icons
by leveraging the undocumented Progman/WorkerW shell architecture.

Approach:
  1. Send message 0x052C to Progman to spawn a WorkerW behind the desktop icons.
  2. Enumerate windows to find the WorkerW that sits between Progman and SHELLDLL_DefView.
  3. Parent our Qt widget's HWND into that WorkerW as a child window.

This is the same technique used by Wallpaper Engine, Lively Wallpaper, and similar tools.
All HWND/shell/Win32 operations are isolated in this module.
"""

import sys
import os
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple, Dict
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QRect

from lyrune.logger import log_event
from lyrune.wallpaper.model import OriginalWallpaperState, WallpaperOwnershipState

if sys.platform != "win32":
    raise ImportError("windows_host.py is only available on Windows")

# ------------------------------------------------------------------
# Win32 API setup — properly typed ctypes prototypes
# ------------------------------------------------------------------

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# FindWindowW
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

# SendMessageTimeoutW
SMTO_ABORTIFHUNG = 0x0002
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,   # hWnd
    wintypes.UINT,   # Msg
    wintypes.WPARAM, # wParam
    wintypes.LPARAM, # lParam
    wintypes.UINT,   # fuFlags
    wintypes.UINT,   # uTimeout
    ctypes.POINTER(ctypes.c_void_p),  # lpdwResult
]
user32.SendMessageTimeoutW.restype = wintypes.BOOL

# EnumWindows
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

# FindWindowExW
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND

# SetParent
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.SetParent.restype = wintypes.HWND

# GetParent
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND

# GetClassName
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

# IsWindow
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

# MoveWindow
user32.MoveWindow.argtypes = [
    wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.BOOL
]
user32.MoveWindow.restype = wintypes.BOOL

# SetWindowPos
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint
]
user32.SetWindowPos.restype = wintypes.BOOL

# ShowWindow
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

# SetWindowLongW / GetWindowLongW
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long

# SystemParametersInfoW for wallpaper capture/restore
user32.SystemParametersInfoW.argtypes = [
    wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT
]
user32.SystemParametersInfoW.restype = wintypes.BOOL

# GetWindowRect / GetClientRect
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL

# ScreenToClient
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ScreenToClient.restype = wintypes.BOOL

# IsWindowVisible / GetWindowTextW
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

# GDI32
gdi32 = ctypes.windll.gdi32

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


def _gdi_fill_magenta(hwnd: int, width: int, height: int) -> bool:
    """Fills the window client area with solid MAGENTA (0x00FF00FF) using Win32 GDI."""
    try:
        hdc = user32.GetDC(hwnd)
        if not hdc:
            return False
        hbrush = gdi32.CreateSolidBrush(0x00FF00FF)
        if not hbrush:
            user32.ReleaseDC(hwnd, hdc)
            return False
        r = wintypes.RECT(0, 0, width, height)
        user32.FillRect(hdc, ctypes.byref(r), hbrush)
        gdi32.DeleteObject(hbrush)
        user32.ReleaseDC(hwnd, hdc)
        return True
    except Exception as e:
        log_event(f"[Wallpaper Host] GDI fill failed: {e}")
        return False

# Win32 Window Registration & Creation for Native Probe
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

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL

user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL

user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
GW_HWNDPREV = 3
GW_HWNDNEXT = 2

# Win32 constants
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
WS_POPUP = 0x80000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOREDRAW = 0x0008
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080

SW_SHOW = 5
SW_HIDE = 0

SPI_GETDESKWALLPAPER = 0x0073
SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002

# Progman message to spawn WorkerW
PROGMAN_SPAWN_WORKERW = 0x052C


def _get_class_name(hwnd: int) -> str:
    """Returns the window class name for the given HWND."""
    if not hwnd or not user32.IsWindow(hwnd):
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _get_window_text(hwnd: int) -> str:
    """Returns the window title for the given HWND."""
    if not hwnd or not user32.IsWindow(hwnd):
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def _get_rect_str(hwnd: int) -> str:
    """Returns formatted window rect string."""
    if not hwnd or not user32.IsWindow(hwnd):
        return "None"
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return f"({r.left},{r.top} -> {r.right},{r.bottom} | {r.right-r.left}x{r.bottom-r.top})"


def _get_client_rect_str(hwnd: int) -> str:
    """Returns formatted client rect string."""
    if not hwnd or not user32.IsWindow(hwnd):
        return "None"
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return f"({r.left},{r.top} -> {r.right},{r.bottom} | {r.right-r.left}x{r.bottom-r.top})"


def get_or_create_fallback_wallpaper() -> str:
    """
    Returns the absolute path to a neutral fallback wallpaper image (solid black).
    Creates the image if it does not already exist.
    """
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".lyrics_cache")
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        cache_dir = os.path.expanduser("~/.lyrune")
        os.makedirs(cache_dir, exist_ok=True)

    fallback_path = os.path.join(cache_dir, "neutral_fallback.png")
    if not os.path.isfile(fallback_path) or os.path.getsize(fallback_path) == 0:
        try:
            from PyQt6.QtGui import QImage, QColor
            img = QImage(1920, 1080, QImage.Format.Format_RGB32)
            img.fill(QColor(0, 0, 0))
            img.save(fallback_path, "PNG")
        except Exception as e:
            log_event(f"[Wallpaper Host] Failed to create fallback image via QImage: {e}")
            # Minimal 1x1 black PNG fallback bytes
            raw_png = (
                b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02'
                b'\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01'
                b'\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82'
            )
            with open(fallback_path, "wb") as f:
                f.write(raw_png)

    return os.path.abspath(fallback_path)


class WindowsDesktopHost:
    """
    Manages embedding a Qt widget into the Windows desktop behind the icons.

    Usage:
        host = WindowsDesktopHost()
        host.capture_original_wallpaper()
        success = host.setup_with_fallback()
        if success:
            host.embed_widget(my_qt_widget, monitor_geometry)
        ...
        host.detach_and_restore()
    """

    def __init__(self):
        self._progman_hwnd: int = 0
        self._workerw_hwnd: int = 0
        self._embedded_hwnd: int = 0
        self._original_parent: int = 0
        self._original_style: int = 0
        self._original_exstyle: int = 0
        self._original_wallpaper = OriginalWallpaperState()
        self._state: WallpaperOwnershipState = WallpaperOwnershipState.NATIVE_ORIGINAL
        self._is_setup: bool = False

    @property
    def is_active(self) -> bool:
        """Returns True if the desktop host is set up and the embedded HWND is valid."""
        return self._is_setup and self._workerw_hwnd != 0

    @property
    def state(self) -> WallpaperOwnershipState:
        """Returns current wallpaper ownership state."""
        return self._state

    def set_state(self, new_state: WallpaperOwnershipState) -> None:
        """Updates the internal wallpaper ownership state."""
        self._state = new_state

    def capture_original_wallpaper(self) -> OriginalWallpaperState:
        """
        Captures the user's current Windows wallpaper configuration
        so it can be restored later.
        """
        try:
            # Get current wallpaper path
            buf = ctypes.create_unicode_buffer(512)
            user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, 512, buf, 0)
            wallpaper_path = buf.value

            # Get wallpaper style from registry
            import winreg
            style = 0
            tile = "0"
            per_monitor = {}
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Control Panel\Desktop"
                ) as key:
                    style, _ = winreg.QueryValueEx(key, "WallpaperStyle")
                    tile, _ = winreg.QueryValueEx(key, "TileWallpaper")
            except (OSError, FileNotFoundError):
                pass

            # Try to query explorer per-monitor history if available
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers"
                ) as key:
                    count = winreg.QueryInfoKey(key)[1]
                    for i in range(count):
                        name, val, _ = winreg.EnumValue(key, i)
                        if isinstance(val, str) and os.path.isfile(val):
                            per_monitor[name] = val
            except (OSError, FileNotFoundError):
                pass

            self._original_wallpaper = OriginalWallpaperState(
                wallpaper_path=wallpaper_path or "",
                wallpaper_style=int(style) if style else 0,
                tile_wallpaper=str(tile) if tile else "0",
                per_monitor_wallpapers=per_monitor,
                captured=True,
            )
            log_event(f"[Wallpaper Host] Captured original wallpaper: '{wallpaper_path}' (style={style}, tile={tile})")
            return self._original_wallpaper

        except Exception as e:
            log_event(f"[Wallpaper Host] Failed to capture original wallpaper: {e}")
            return self._original_wallpaper

    def apply_native_fallback(self) -> bool:
        """
        Applies a neutral fallback wallpaper to native Windows so that DWM / Win+D
        transitions expose a harmless neutral background instead of the user's old wallpaper.
        """
        if self._state == WallpaperOwnershipState.NATIVE_FALLBACK or self._state == WallpaperOwnershipState.LYRUNE_ACTIVE:
            return True

        try:
            # Capture original wallpaper first if not already captured
            if not self._original_wallpaper.captured:
                self.capture_original_wallpaper()

            fallback_path = get_or_create_fallback_wallpaper()
            if not fallback_path or not os.path.isfile(fallback_path):
                log_event("[Wallpaper Host] Could not get fallback wallpaper path.")
                return False

            # Set registry WallpaperStyle to stretch (2) so fallback covers the screen
            import winreg
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Control Panel\Desktop",
                    0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "2")
                    winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")
            except Exception as e:
                log_event(f"[Wallpaper Host] Registry style warning: {e}")

            # Apply fallback to native Windows wallpaper
            path_buf = ctypes.create_unicode_buffer(fallback_path)
            user32.SystemParametersInfoW(
                SPI_SETDESKWALLPAPER, 0, path_buf,
                SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
            )
            self._state = WallpaperOwnershipState.NATIVE_FALLBACK
            log_event(f"[Wallpaper Host] Native wallpaper fallback applied: '{fallback_path}'")
            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] Failed to apply native fallback: {e}")
            return False

    def setup_with_fallback(self) -> bool:
        """
        Diagnostic mode: Keep user's original wallpaper active and run native WorkerW setup + probe.
        (Temporarily disables black fallback per Sections 10 & 21 so original wallpaper vs MAGENTA is clear).
        """
        try:
            # Capture original wallpaper first
            if not self._original_wallpaper.captured:
                self.capture_original_wallpaper()

            # Temporarily do NOT apply black fallback
            log_event("[Wallpaper Host] Diagnostic mode: Original wallpaper retained as background.")

            # Step 2: Setup WorkerW and native probe
            if not self.setup():
                log_event("[Wallpaper Host] WorkerW setup failed.")
                return False

            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] setup_with_fallback failed: {e}")
            return False

    def _inspect_z_order_above(self, hwnd: int) -> None:
        """Walks upward in Z-order from hwnd and logs all windows sitting above it."""
        if not hwnd or not user32.IsWindow(hwnd):
            return
        z_above = []
        curr = user32.GetWindow(hwnd, GW_HWNDPREV)
        while curr:
            cls = _get_class_name(curr)
            vis = bool(user32.IsWindowVisible(curr))
            rect = _get_rect_str(curr)
            title = _get_window_text(curr)
            z_above.append(f"0x{curr:08X}:{cls}(vis={vis},rect={rect},title='{title[:20]}')")
            curr = user32.GetWindow(curr, GW_HWNDPREV)

        log_event(f"[Wallpaper Host] Z-Order: {len(z_above)} window(s) sitting ABOVE 0x{hwnd:08X}:")
        for idx, w_info in enumerate(z_above[:10], 1):
            log_event(f"    ↑ [{idx:02d}] {w_info}")

    def _run_native_probe_test(self, candidate_hwnd: int) -> int:
        """
        Creates a pure Win32 Native MAGENTA Probe window and hosts it inside candidate_hwnd.
        Returns the probe window HWND.
        """
        try:
            hinst = kernel32.GetModuleHandleW(None)
            hbrush_magenta = gdi32.CreateSolidBrush(0x00FF00FF)

            def probe_wndproc(hwnd, msg, wparam, lparam):
                if msg in (0x000F, 0x0014):  # WM_PAINT, WM_ERASEBKGND
                    rc = wintypes.RECT()
                    user32.GetClientRect(hwnd, ctypes.byref(rc))
                    hdc = user32.GetDC(hwnd)
                    if hdc:
                        hb = gdi32.CreateSolidBrush(0x00FF00FF)
                        user32.FillRect(hdc, ctypes.byref(rc), hb)
                        gdi32.DeleteObject(hb)
                        user32.ReleaseDC(hwnd, hdc)
                    return 1 if msg == 0x0014 else 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            wndproc_cb = WNDPROC(probe_wndproc)
            self._probe_wndproc_cb = wndproc_cb  # Keep callback reference alive

            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.style = 3  # CS_HREDRAW | CS_VREDRAW
            wc.lpfnWndProc = wndproc_cb
            wc.hInstance = hinst
            wc.hbrBackground = hbrush_magenta
            wc.lpszClassName = "LyruneWallpaperProbe"

            user32.UnregisterClassW("LyruneWallpaperProbe", hinst)
            atom = user32.RegisterClassExW(ctypes.byref(wc))

            rc = wintypes.RECT()
            user32.GetClientRect(candidate_hwnd, ctypes.byref(rc))
            cw = rc.right - rc.left if rc.right > rc.left else 1920
            ch = rc.bottom - rc.top if rc.bottom > rc.top else 1080

            probe_hwnd = user32.CreateWindowExW(
                0, "LyruneWallpaperProbe", "Lyrune Native Probe",
                WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS,
                0, 0, cw, ch,
                candidate_hwnd, 0, hinst, None
            )

            if probe_hwnd:
                user32.SetWindowPos(
                    probe_hwnd, 0, 0, 0, cw, ch,
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
                )
                user32.ShowWindow(probe_hwnd, SW_SHOW)
                _gdi_fill_magenta(probe_hwnd, cw, ch)
                user32.UpdateWindow(probe_hwnd)
                user32.UpdateWindow(candidate_hwnd)
                log_event(
                    f"[Native Probe] Created native Win32 MAGENTA probe 0x{probe_hwnd:08X} inside host 0x{candidate_hwnd:08X} "
                    f"(size={cw}x{ch}, vis={bool(user32.IsWindowVisible(probe_hwnd))})"
                )
                self._inspect_z_order_above(candidate_hwnd)

            return probe_hwnd
        except Exception as e:
            log_event(f"[Native Probe] Error creating probe window: {e}")
            return 0

    def _debug_dump_desktop_hierarchy(self) -> None:
        """
        Dumps comprehensive diagnostics of the Windows desktop shell hierarchy.
        Logs Progman, all WorkerW windows in Z-order, SHELLDLL_DefView, and parent-child relations.
        """
        log_event("=" * 60)
        log_event("[Wallpaper Host] === DESKTOP SHELL HIERARCHY DIAGNOSTIC ===")

        progman = user32.FindWindowW("Progman", None) or 0
        if progman:
            p_vis = bool(user32.IsWindowVisible(progman))
            p_style = user32.GetWindowLongW(progman, GWL_STYLE)
            p_exstyle = user32.GetWindowLongW(progman, GWL_EXSTYLE)
            p_parent = user32.GetParent(progman)
            log_event(
                f"[Wallpaper Host] Progman:          0x{progman:08X} | Class: {_get_class_name(progman)} | "
                f"Parent: 0x{p_parent:08X} | Vis: {p_vis} | Style: 0x{p_style:08X} | ExStyle: 0x{p_exstyle:08X} | "
                f"Rect: {_get_rect_str(progman)} | Client: {_get_client_rect_str(progman)}"
            )
        else:
            log_event("[Wallpaper Host] Progman:          NOT FOUND (0x00000000)")

        # Enumerate all top-level WorkerW and Progman windows
        top_windows = []
        shell_parent = 0
        shell_view_hwnd = 0

        def _enum_shell_windows(hwnd, _lparam):
            nonlocal shell_parent, shell_view_hwnd
            cls = _get_class_name(hwnd)
            if cls in ("Progman", "WorkerW") or "SHELLDLL" in cls:
                vis = bool(user32.IsWindowVisible(hwnd))
                parent = user32.GetParent(hwnd)
                style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                title = _get_window_text(hwnd)

                # Check for SHELLDLL_DefView child
                defview = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
                if defview:
                    shell_parent = hwnd
                    shell_view_hwnd = defview

                top_windows.append({
                    "hwnd": hwnd,
                    "class": cls,
                    "title": title,
                    "parent": parent,
                    "vis": vis,
                    "style": style,
                    "exstyle": exstyle,
                    "has_defview": bool(defview),
                    "defview_hwnd": defview or 0,
                    "rect": _get_rect_str(hwnd),
                    "client": _get_client_rect_str(hwnd),
                })
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_shell_windows), 0)

        if shell_view_hwnd:
            sv_vis = bool(user32.IsWindowVisible(shell_view_hwnd))
            log_event(
                f"[Wallpaper Host] Shell DefView:    0x{shell_view_hwnd:08X} | Parent: 0x{shell_parent:08X} "
                f"({_get_class_name(shell_parent)}) | Vis: {sv_vis} | Rect: {_get_rect_str(shell_view_hwnd)}"
            )
        else:
            log_event("[Wallpaper Host] Shell DefView:    NOT FOUND")

        log_event(f"[Wallpaper Host] Shell Parent:     0x{shell_parent:08X} ({_get_class_name(shell_parent)})")
        log_event(f"[Wallpaper Host] Enumerated {len(top_windows)} shell top-level window(s) in Z-order:")
        for idx, tw in enumerate(top_windows, 1):
            log_event(
                f"  [{idx:02d}] HWND: 0x{tw['hwnd']:08X} | Class: {tw['class']:10s} | Vis: {str(tw['vis']):5s} | "
                f"Parent: 0x{tw['parent']:08X} | Style: 0x{tw['style']:08X} | Ex: 0x{tw['exstyle']:08X} | "
                f"HasDefView: {str(tw['has_defview']):5s} | Rect: {tw['rect']} | Client: {tw['client']}"
            )
        log_event("=" * 60)

    def setup(self) -> bool:
        """
        Initializes the desktop hosting environment.

        1. Finds the Progman window.
        2. Sends the spawn-WorkerW message (0x052C).
        3. Enumerates windows to find the WorkerW behind desktop icons.
        4. Runs the native Win32 MAGENTA probe test.

        Returns True on success.
        """
        try:
            # Step 1: Find Progman
            self._progman_hwnd = user32.FindWindowW("Progman", None) or 0
            if not self._progman_hwnd:
                log_event("[Wallpaper Host] ERROR: Could not find Progman window.")
                return False
            log_event(f"[Wallpaper Host] Found Progman: 0x{self._progman_hwnd:08X}")

            # Step 2: Send 0x052C to spawn WorkerW
            result = ctypes.c_void_p(0)
            user32.SendMessageTimeoutW(
                self._progman_hwnd,
                PROGMAN_SPAWN_WORKERW,
                0, 0,
                SMTO_ABORTIFHUNG,
                1000,  # 1 second timeout
                ctypes.byref(result),
            )
            log_event("[Wallpaper Host] Sent WorkerW spawn message to Progman.")

            # Step 3: Find the correct WorkerW
            self._workerw_hwnd = self._find_desktop_workerw()
            if not self._workerw_hwnd:
                log_event("[Wallpaper Host] ERROR: Could not find desktop WorkerW.")
                return False

            log_event(f"[Wallpaper Host] Successfully established desktop WorkerW: 0x{self._workerw_hwnd:08X}")
            self._is_setup = True

            # Step 4: Run pure Win32 native MAGENTA probe test on the selected WorkerW
            self._native_probe_hwnd = self._run_native_probe_test(self._workerw_hwnd)

            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] Setup failed: {e}")
            return False

    def _find_desktop_workerw(self) -> int:
        """
        Enumerates top-level windows to locate the dedicated WorkerW that sits
        behind the desktop icons container (SHELLDLL_DefView).
        """
        self._debug_dump_desktop_hierarchy()

        shell_parent = 0
        shell_defview = 0

        def _find_shell(hwnd, _lparam):
            nonlocal shell_parent, shell_defview
            sv = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
            if sv:
                shell_parent = hwnd
                shell_defview = sv
                return False
            return True

        user32.EnumWindows(WNDENUMPROC(_find_shell), 0)

        if not shell_parent:
            log_event("[Wallpaper Host] ERROR: Could not locate SHELLDLL_DefView parent window.")
            return 0

        log_event(f"[Wallpaper Host] Icon parent found: 0x{shell_parent:08X} ({_get_class_name(shell_parent)})")

        target_workerw = 0

        # Step 1: In standard Windows 10/11 WorkerW architecture, the WorkerW behind
        # the icons is the sibling WorkerW immediately following the shell parent in Z-order.
        sibling = user32.FindWindowExW(0, shell_parent, "WorkerW", None)
        if sibling and sibling != shell_parent and user32.IsWindow(sibling):
            # Verify sibling does not host SHELLDLL_DefView itself
            if not user32.FindWindowExW(sibling, 0, "SHELLDLL_DefView", None):
                target_workerw = sibling
                log_event(
                    f"[Wallpaper Host] Located sibling WorkerW via FindWindowExW: 0x{target_workerw:08X} "
                    f"(Parent: 0x{user32.GetParent(target_workerw):08X}, Vis: {bool(user32.IsWindowVisible(target_workerw))})"
                )

        # Step 2: If FindWindowExW direct sibling search did not return a valid candidate,
        # enumerate all top-level WorkerW windows and choose the WorkerW without SHELLDLL_DefView.
        if not target_workerw:
            candidates = []

            def _enum_all_workerw(hwnd, _lparam):
                cls = _get_class_name(hwnd)
                if cls == "WorkerW" and hwnd != shell_parent:
                    has_shell = bool(user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None))
                    if not has_shell:
                        candidates.append(hwnd)
                return True

            user32.EnumWindows(WNDENUMPROC(_enum_all_workerw), 0)
            log_event(f"[Wallpaper Host] Sibling enumeration candidates ({len(candidates)}): {[f'0x{c:08X}' for c in candidates]}")

            # Prefer the visible WorkerW
            for c in candidates:
                if user32.IsWindowVisible(c):
                    target_workerw = c
                    log_event(f"[Wallpaper Host] Selected visible candidate: 0x{target_workerw:08X}")
                    break
            if not target_workerw and candidates:
                target_workerw = candidates[0]
                log_event(f"[Wallpaper Host] Selected first candidate: 0x{target_workerw:08X}")

        # Step 3: Validate selected HWND (Section 5 & 6)
        if not target_workerw or not user32.IsWindow(target_workerw):
            log_event("[Wallpaper Host] ERROR: No valid WorkerW found to host wallpaper.")
            return 0

        target_cls = _get_class_name(target_workerw)
        if target_cls != "WorkerW":
            log_event(f"[Wallpaper Host] ERROR: Selected HWND 0x{target_workerw:08X} is '{target_cls}', not 'WorkerW'. Refusing host.")
            return 0

        return target_workerw

    def embed_widget(self, widget: QWidget, geometry: QRect) -> bool:
        """
        Parents the given Qt widget's HWND into the desktop WorkerW
        and positions it to cover the specified monitor geometry.

        Args:
            widget: The Qt widget to embed (must be shown first to have a valid winId).
            geometry: The target geometry in physical screen coordinates.

        Returns True on success.
        """
        if not self._is_setup or not self._workerw_hwnd:
            log_event("[Wallpaper Host] Cannot embed: host not set up.")
            return False

        try:
            # Ensure widget is realized
            if not widget.winId():
                widget.show()

            hwnd = int(widget.winId())
            if not hwnd or not user32.IsWindow(hwnd):
                log_event("[Wallpaper Host] Cannot embed: widget has no valid HWND.")
                return False

            # Save original window state
            self._embedded_hwnd = hwnd
            self._original_parent = user32.GetParent(hwnd)
            self._original_style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            self._original_exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            # Ensure host WorkerW has WS_CLIPCHILDREN | WS_CLIPSIBLINGS and is visible
            w_style = user32.GetWindowLongW(self._workerw_hwnd, GWL_STYLE)
            user32.SetWindowLongW(self._workerw_hwnd, GWL_STYLE, w_style | WS_CLIPCHILDREN | WS_CLIPSIBLINGS)
            user32.ShowWindow(self._workerw_hwnd, SW_SHOW)
            user32.SetWindowPos(
                self._workerw_hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
            )

            # Convert screen coordinates to WorkerW client coordinates (Section 11)
            pt = wintypes.POINT(geometry.x(), geometry.y())
            user32.ScreenToClient(self._workerw_hwnd, ctypes.byref(pt))
            local_x = pt.x
            local_y = pt.y
            local_w = geometry.width()
            local_h = geometry.height()

            # Set pure child window styles (strip popup, overlapped, toolwindow)
            new_style = WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
            user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
            new_exstyle = 0
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_exstyle)

            # Parent into the desktop WorkerW
            user32.SetParent(hwnd, self._workerw_hwnd)

            # Position and size to cover the target geometry in WorkerW client coordinates
            user32.SetWindowPos(
                hwnd, 0,
                local_x, local_y,
                local_w, local_h,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
            )

            # TEST C: Direct Win32 GDI MAGENTA fill test
            gdi_success = _gdi_fill_magenta(hwnd, local_w, local_h)
            log_event(f"[Wallpaper Host] TEST C: Native Win32 GDI fill (MAGENTA) executed on HWND 0x{hwnd:08X}: {gdi_success}")

            # Post-embed HWND Stability Check (Section 19)
            current_hwnd = int(widget.winId())
            if current_hwnd != hwnd:
                log_event(f"[Wallpaper Host] WARNING: Canvas HWND changed from 0x{hwnd:08X} to 0x{current_hwnd:08X} during embedding!")
                hwnd = current_hwnd
                self._embedded_hwnd = hwnd

            # Verification (Section 7 & 32)
            actual_parent = user32.GetParent(hwnd)
            canvas_vis = bool(user32.IsWindowVisible(hwnd))
            workerw_vis = bool(user32.IsWindowVisible(self._workerw_hwnd))
            canvas_style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            canvas_exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            progman = self._progman_hwnd
            shell_defview = user32.FindWindowExW(0, 0, "SHELLDLL_DefView", None) or 0
            shell_parent = user32.GetParent(shell_defview) if shell_defview else 0

            log_event("-" * 60)
            log_event("[Wallpaper Host] === EMBEDDING VERIFICATION REPORT ===")
            log_event(f"[Wallpaper Host] Progman:              0x{progman:08X}")
            log_event(f"[Wallpaper Host] Shell DefView:        0x{shell_defview:08X}")
            log_event(f"[Wallpaper Host] Shell parent:         0x{shell_parent:08X}")
            log_event(f"[Wallpaper Host] Selected WorkerW:     0x{self._workerw_hwnd:08X}")
            log_event(f"[Wallpaper Host] WorkerW class:        {_get_class_name(self._workerw_hwnd)}")
            log_event(f"[Wallpaper Host] WorkerW parent:       0x{user32.GetParent(self._workerw_hwnd):08X}")
            log_event(f"[Wallpaper Host] WorkerW visible:      {workerw_vis}")
            log_event(f"[Wallpaper Host] Canvas HWND:          0x{hwnd:08X}")
            log_event(f"[Wallpaper Host] Canvas parent:        0x{actual_parent:08X}")
            log_event(f"[Wallpaper Host] Expected parent:      0x{self._workerw_hwnd:08X}")
            log_event(f"[Wallpaper Host] Canvas visible:       {canvas_vis}")
            log_event(f"[Wallpaper Host] Canvas style:         0x{canvas_style:08X}")
            log_event(f"[Wallpaper Host] Canvas exstyle:       0x{canvas_exstyle:08X}")
            log_event(f"[Wallpaper Host] WorkerW rect:         {_get_rect_str(self._workerw_hwnd)}")
            log_event(f"[Wallpaper Host] WorkerW client:       {_get_client_rect_str(self._workerw_hwnd)}")
            log_event(f"[Wallpaper Host] Canvas rect:          {_get_rect_str(hwnd)}")
            log_event(f"[Wallpaper Host] Canvas client:        {_get_client_rect_str(hwnd)}")
            log_event("-" * 60)

            if actual_parent != self._workerw_hwnd:
                log_event(
                    f"[Wallpaper Host] ERROR: Canvas parent (0x{actual_parent:08X}) != Expected parent (0x{self._workerw_hwnd:08X}). "
                    f"Embedding failed verification!"
                )
                return False

            # Force redraw
            user32.InvalidateRect(hwnd, None, True)
            user32.UpdateWindow(hwnd)
            user32.UpdateWindow(self._workerw_hwnd)
            widget.update()
            widget.repaint()

            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] Embed failed: {e}")
            return False

    def resize_widget(self, geometry: QRect) -> bool:
        """Repositions/resizes the embedded widget to match new geometry."""
        if not self._embedded_hwnd or not user32.IsWindow(self._embedded_hwnd):
            return False

        try:
            pt = wintypes.POINT(geometry.x(), geometry.y())
            user32.ScreenToClient(self._workerw_hwnd, ctypes.byref(pt))
            user32.SetWindowPos(
                self._embedded_hwnd, 0,
                pt.x, pt.y,
                geometry.width(), geometry.height(),
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
            )
            return True
        except Exception:
            return False

    def is_host_valid(self) -> bool:
        """
        Validates that the desktop hosting chain is still intact.

        Checks:
        - Host HWND still exists and is valid
        - Our embedded HWND is still a child of the host
        - Progman is still present

        Returns False if explorer has restarted or the shell has changed.
        """
        if not self._is_setup:
            return False

        try:
            # Check host window is still valid
            if not self._workerw_hwnd or not user32.IsWindow(self._workerw_hwnd):
                log_event("[Wallpaper Host] Host window HWND is no longer valid.")
                return False

            # Check host window class name is still a valid desktop host (WorkerW)
            cls = _get_class_name(self._workerw_hwnd)
            if cls != "WorkerW":
                log_event(f"[Wallpaper Host] Host window class changed to '{cls}' (expected WorkerW).")
                return False

            # Check Progman is still present
            progman = user32.FindWindowW("Progman", None)
            if not progman or not user32.IsWindow(progman):
                log_event("[Wallpaper Host] Progman is no longer valid.")
                return False

            # Check embedded widget is still parented to host
            if self._embedded_hwnd and user32.IsWindow(self._embedded_hwnd):
                current_parent = user32.GetParent(self._embedded_hwnd)
                if current_parent != self._workerw_hwnd:
                    log_event(
                        f"[Wallpaper Host] Embedded widget parent changed from "
                        f"0x{self._workerw_hwnd:08X} to 0x{current_parent:08X}."
                    )
                    return False

            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] Host validation error: {e}")
            return False

            # Check embedded widget is still parented correctly
            if self._embedded_hwnd and user32.IsWindow(self._embedded_hwnd):
                parent = user32.GetParent(self._embedded_hwnd)
                if parent != self._workerw_hwnd:
                    log_event("[Wallpaper Host] Embedded widget lost its parent.")
                    return False

            # Check Progman is still alive
            progman = user32.FindWindowW("Progman", None)
            if not progman:
                log_event("[Wallpaper Host] Progman is gone (explorer restart?).")
                return False

            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] Validation error: {e}")
            return False

    def detach_widget(self) -> bool:
        """
        Detaches the embedded widget from the desktop WorkerW
        without restoring the original wallpaper.
        """
        if not self._embedded_hwnd:
            return True

        try:
            if user32.IsWindow(self._embedded_hwnd):
                # Hide first to prevent visual glitch
                user32.ShowWindow(self._embedded_hwnd, SW_HIDE)

                # Restore original parent (desktop)
                desktop = user32.GetDesktopWindow()
                user32.SetParent(self._embedded_hwnd, desktop)

                # Restore original styles
                if self._original_style:
                    user32.SetWindowLongW(self._embedded_hwnd, GWL_STYLE, self._original_style)
                if self._original_exstyle:
                    user32.SetWindowLongW(self._embedded_hwnd, GWL_EXSTYLE, self._original_exstyle)

                log_event(f"[Wallpaper Host] Detached widget 0x{self._embedded_hwnd:08X}")

            self._embedded_hwnd = 0
            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] Detach failed: {e}")
            self._embedded_hwnd = 0
            return False

    def restore_original_wallpaper(self) -> bool:
        """
        Restores the user's original Windows wallpaper that was captured
        before Lyrune took over. Guaranteed to be idempotent.
        """
        if self._state == WallpaperOwnershipState.NATIVE_ORIGINAL:
            log_event("[Wallpaper Host] Original wallpaper already active (state is NATIVE_ORIGINAL).")
            return True

        if not self._original_wallpaper.captured:
            log_event("[Wallpaper Host] No original wallpaper was captured, skipping restore.")
            self._state = WallpaperOwnershipState.NATIVE_ORIGINAL
            return False

        self._state = WallpaperOwnershipState.RESTORING
        log_event("[Wallpaper Host] Original wallpaper restoration started...")

        try:
            path = self._original_wallpaper.wallpaper_path

            # Restore wallpaper style via registry
            import winreg
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Control Panel\Desktop",
                    0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ,
                                      str(self._original_wallpaper.wallpaper_style))
                    winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ,
                                      self._original_wallpaper.tile_wallpaper)
            except (OSError, PermissionError) as e:
                log_event(f"[Wallpaper Host] Registry restore warning: {e}")

            # Set the wallpaper path
            if path and os.path.isfile(path):
                path_buf = ctypes.create_unicode_buffer(path)
                user32.SystemParametersInfoW(
                    SPI_SETDESKWALLPAPER, 0, path_buf,
                    SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
                )
                log_event(f"[Wallpaper Host] Restored original wallpaper: '{path}'")
            else:
                # Empty path means no wallpaper was set (solid color desktop)
                user32.SystemParametersInfoW(
                    SPI_SETDESKWALLPAPER, 0, None,
                    SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
                )
                log_event("[Wallpaper Host] Restored original wallpaper (solid color/empty).")

            self._state = WallpaperOwnershipState.NATIVE_ORIGINAL
            log_event("[Wallpaper Host] Original wallpaper restoration completed.")
            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] Wallpaper restore failed: {e}")
            self._state = WallpaperOwnershipState.FAILED
            return False

    def detach_and_restore(self) -> None:
        """
        Complete teardown: detach the embedded widget and restore
        the user's original wallpaper.
        """
        self.detach_widget()
        self.restore_original_wallpaper()
        self._is_setup = False
        self._workerw_hwnd = 0
        self._progman_hwnd = 0
        log_event("[Wallpaper Host] Full teardown complete.")

    def get_workerw_hwnd(self) -> int:
        """Returns the WorkerW HWND for direct child embedding (e.g., mpv --wid)."""
        return self._workerw_hwnd

    def get_embedded_hwnd(self) -> int:
        """Returns the currently embedded widget HWND."""
        return self._embedded_hwnd
