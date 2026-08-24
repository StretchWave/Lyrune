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

# GetDesktopWindow
user32.GetDesktopWindow.argtypes = []
user32.GetDesktopWindow.restype = wintypes.HWND

# Win32 constants
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080

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
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


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
        Executes atomic setup:
          1. Capture original wallpaper
          2. Apply neutral fallback to native Windows background
          3. Set up WorkerW desktop host
        If setup fails, automatically rolls back native wallpaper to original state.
        """
        try:
            # Step 1: Capture original wallpaper
            if not self._original_wallpaper.captured:
                self.capture_original_wallpaper()

            # Step 2: Apply neutral fallback
            if not self.apply_native_fallback():
                log_event("[Wallpaper Host] Failed to apply native fallback, aborting setup.")
                self.restore_original_wallpaper()
                return False

            # Step 3: Setup WorkerW
            if not self.setup():
                log_event("[Wallpaper Host] WorkerW setup failed, rolling back to original wallpaper.")
                self.restore_original_wallpaper()
                return False

            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] setup_with_fallback failed: {e}")
            self.restore_original_wallpaper()
            return False

    def setup(self) -> bool:
        """
        Initializes the desktop hosting environment.

        1. Finds the Progman window.
        2. Sends the spawn-WorkerW message (0x052C).
        3. Enumerates windows to find the WorkerW behind desktop icons.

        Returns True on success.
        """
        try:
            # Step 1: Find Progman
            self._progman_hwnd = user32.FindWindowW("Progman", None)
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

            log_event(f"[Wallpaper Host] Found desktop WorkerW: 0x{self._workerw_hwnd:08X}")
            self._is_setup = True
            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] Setup failed: {e}")
            return False

    def _find_desktop_workerw(self) -> int:
        """
        Enumerates top-level windows to find the WorkerW that sits
        behind the desktop icon container (SHELLDLL_DefView).
        """
        shell_parent = 0

        def _find_shell_parent(hwnd, _lparam):
            nonlocal shell_parent
            shell_view = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
            if shell_view:
                shell_parent = hwnd
                return False
            return True

        cb = WNDENUMPROC(_find_shell_parent)
        user32.EnumWindows(cb, 0)

        target_workerw = 0

        # Step 1: In standard Windows 10/11, the WorkerW behind the icons is the
        # next top-level window in Z-order of class "WorkerW" after the shell parent.
        if shell_parent:
            w = user32.FindWindowExW(0, shell_parent, "WorkerW", None)
            if w and w != shell_parent:
                target_workerw = w

        # Step 2: If not found as direct next sibling, enumerate all top-level WorkerW windows
        # and select the one that does NOT contain SHELLDLL_DefView.
        if not target_workerw:
            candidates = []

            def _enum_all_workerw(hwnd, _lparam):
                cls = _get_class_name(hwnd)
                if cls == "WorkerW":
                    has_shell = bool(user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None))
                    if not has_shell:
                        candidates.append(hwnd)
                return True

            cb2 = WNDENUMPROC(_enum_all_workerw)
            user32.EnumWindows(cb2, 0)

            # Prefer the visible WorkerW
            for c in candidates:
                if user32.IsWindowVisible(c):
                    target_workerw = c
                    break
            if not target_workerw and candidates:
                target_workerw = candidates[0]

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
            if not hwnd:
                log_event("[Wallpaper Host] Cannot embed: widget has no HWND.")
                return False

            # Save original window state for potential restoration
            self._embedded_hwnd = hwnd
            self._original_parent = user32.GetParent(hwnd)
            self._original_style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            self._original_exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            # Ensure host WorkerW has WS_CLIPCHILDREN so it never paints over its children
            w_style = user32.GetWindowLongW(self._workerw_hwnd, GWL_STYLE)
            user32.SetWindowLongW(self._workerw_hwnd, GWL_STYLE, w_style | WS_CLIPCHILDREN | WS_CLIPSIBLINGS)
            user32.ShowWindow(self._workerw_hwnd, SW_SHOW)
            user32.SetWindowPos(
                self._workerw_hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
            )

            # Inform Qt's QWindow about the native reparenting so it does not stay as a floating tool window
            from PyQt6.QtGui import QWindow
            window_handle = widget.windowHandle()
            if window_handle:
                host_window = QWindow.fromWinId(self._workerw_hwnd)
                window_handle.setParent(host_window)

            # Set child window style — remove frame/border, add child flag
            new_style = WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
            user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)

            # Remove any extended styles that would interfere
            new_exstyle = 0
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_exstyle)

            # Parent into the desktop WorkerW
            user32.SetParent(hwnd, self._workerw_hwnd)

            # Position and size to cover the target geometry
            user32.MoveWindow(
                hwnd,
                geometry.x(), geometry.y(),
                geometry.width(), geometry.height(),
                True  # Repaint
            )

            user32.ShowWindow(hwnd, SW_SHOW)
            user32.UpdateWindow(hwnd)
            user32.UpdateWindow(self._workerw_hwnd)
            widget.update()
            widget.repaint()

            log_event(
                f"[Wallpaper Host] Embedded widget 0x{hwnd:08X} into WorkerW 0x{self._workerw_hwnd:08X} "
                f"at ({geometry.x()}, {geometry.y()}, {geometry.width()}x{geometry.height()})"
            )
            return True

        except Exception as e:
            log_event(f"[Wallpaper Host] Embed failed: {e}")
            return False

    def resize_widget(self, geometry: QRect) -> bool:
        """Repositions/resizes the embedded widget to match new geometry."""
        if not self._embedded_hwnd or not user32.IsWindow(self._embedded_hwnd):
            return False

        try:
            user32.MoveWindow(
                self._embedded_hwnd,
                geometry.x(), geometry.y(),
                geometry.width(), geometry.height(),
                True
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

            # Check host window class name is still a valid desktop host (WorkerW or Progman)
            cls = _get_class_name(self._workerw_hwnd)
            if cls not in ("WorkerW", "Progman"):
                log_event(f"[Wallpaper Host] Host window class changed to '{cls}' (expected WorkerW or Progman).")
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
