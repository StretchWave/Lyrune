"""
window_utils.py — Shared window geometry, multi-monitor detection, and edge-snapping utilities.

Provides centralized, screen-aware geometry calculations for frameless desktop widgets
(e.g., LyricsWidget, VisualizerWindow) without coupling the widgets together.
"""

import os
import sys
import json
import subprocess
from typing import Optional, Tuple, List, Dict, Any
from PyQt6.QtCore import QPoint, QRect, QSize
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    # Set proper 64-bit ctypes prototypes to prevent pointer truncation
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint
    ]
    user32.SetWindowPos.restype = wintypes.BOOL

    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long

    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long

    user32.GetTopWindow.argtypes = [wintypes.HWND]
    user32.GetTopWindow.restype = wintypes.HWND

    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindow.restype = wintypes.HWND

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    # Win32 Extended Window Style Flags
    GWL_EXSTYLE = -20
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_LAYERED = 0x00080000
    WS_EX_NOACTIVATE = 0x08000000

    # Win32 SetWindowPos Flags
    HWND_TOPMOST = ctypes.c_void_p(-1).value
    HWND_NOTOPMOST = ctypes.c_void_p(-2).value
    HWND_BOTTOM = ctypes.c_void_p(1).value
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040

    GW_HWNDNEXT = 2



def get_screen_for_point(point: QPoint) -> QScreen:
    """Returns the QScreen containing the given point, or primaryScreen as fallback."""
    screen = QApplication.screenAt(point)
    if not screen:
        screen = QApplication.primaryScreen()
    return screen


def get_screen_for_rect(rect: QRect) -> QScreen:
    """
    Returns the QScreen containing the center / majority area of the rectangle.
    Handles negative coordinates and multi-monitor setups gracefully.
    """
    center = rect.center()
    screen = QApplication.screenAt(center)
    if screen:
        return screen

    # Check topLeft and other corners if center wasn't on a valid screen
    for pt in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
        screen = QApplication.screenAt(pt)
        if screen:
            return screen

    # Fallback to screen with maximum intersection area
    max_area = 0
    best_screen = None
    for s in QApplication.screens():
        intersect = s.geometry().intersected(rect)
        area = intersect.width() * intersect.height()
        if area > max_area:
            max_area = area
            best_screen = s

    return best_screen or QApplication.primaryScreen()


def constrain_to_work_area(pos: QPoint, size: QSize, screen: Optional[QScreen] = None) -> QPoint:
    """
    Ensures a window's bounds fit entirely within the available geometry (work area)
    of the target screen, accounting for OS taskbars, docks, and desktop panels.
    """
    rect = QRect(pos, size)
    if screen is None:
        screen = get_screen_for_rect(rect)

    work_geo = screen.availableGeometry()

    x = pos.x()
    y = pos.y()
    w = size.width()
    h = size.height()

    # Clamp X
    if w <= work_geo.width():
        if x < work_geo.left():
            x = work_geo.left()
        elif x + w > work_geo.right() + 1:
            x = work_geo.right() + 1 - w
    else:
        x = work_geo.left()

    # Clamp Y
    if h <= work_geo.height():
        if y < work_geo.top():
            y = work_geo.top()
        elif y + h > work_geo.bottom() + 1:
            y = work_geo.bottom() + 1 - h
    else:
        y = work_geo.top()

    return QPoint(x, y)


def calculate_edge_snap(
    window_rect: QRect,
    threshold: int = 50,
    screen: Optional[QScreen] = None
) -> Tuple[Optional[str], QPoint]:
    """
    Checks proximity to screen work-area edges (BOTTOM, TOP, LEFT, RIGHT).
    Returns (detected_snap_edge, snapped_top_left_point).

    If not within threshold of any edge, returns (None, current_top_left).
    If near a corner, returns the dominant edge while aligning flush to the corner.
    """
    if screen is None:
        screen = get_screen_for_rect(window_rect)

    geo = screen.availableGeometry()
    x = window_rect.x()
    y = window_rect.y()
    w = window_rect.width()
    h = window_rect.height()

    dist_left = abs(x - geo.left())
    dist_right = abs((geo.left() + geo.width()) - (x + w))
    dist_top = abs(y - geo.top())
    dist_bottom = abs((geo.top() + geo.height()) - (y + h))

    near_left = x <= geo.left() + threshold or dist_left < threshold
    near_right = (x + w) >= (geo.left() + geo.width() - threshold) or dist_right < threshold
    near_top = y <= geo.top() + threshold or dist_top < threshold
    near_bottom = (y + h) >= (geo.top() + geo.height() - threshold) or dist_bottom < threshold

    if not (near_left or near_right or near_top or near_bottom):
        return None, window_rect.topLeft()

    # Determine horizontal snap coordinate
    if near_left:
        snap_x = geo.left()
    elif near_right:
        snap_x = geo.left() + geo.width() - w
    else:
        snap_x = x

    # Determine vertical snap coordinate
    if near_top:
        snap_y = geo.top()
    elif near_bottom:
        snap_y = geo.top() + geo.height() - h
    else:
        snap_y = y

    # Determine primary edge name
    edge_candidates = []
    if near_bottom:
        edge_candidates.append(("BOTTOM", dist_bottom))
    if near_top:
        edge_candidates.append(("TOP", dist_top))
    if near_left:
        edge_candidates.append(("LEFT", dist_left))
    if near_right:
        edge_candidates.append(("RIGHT", dist_right))

    edge_candidates.sort(key=lambda item: item[1])
    dominant_edge = edge_candidates[0][0] if edge_candidates else None

    # Clamp coordinates into available work area
    clamped_x = max(geo.left(), min(snap_x, geo.left() + geo.width() - w))
    clamped_y = max(geo.top(), min(snap_y, geo.top() + geo.height() - h))

    return dominant_edge, QPoint(int(clamped_x), int(clamped_y))


def calculate_visualizer_snap(
    current_pos: QPoint,
    current_size: QSize,
    logical_length: int,
    logical_thickness: int,
    current_orientation: str = "BOTTOM",
    threshold: int = 60,
    screen: Optional[QScreen] = None
) -> Tuple[str, str, QPoint, int, int]:
    """
    Calculates border snapping, dynamic orientation rotation, and physical dimensions
    for the visualizer window.

    Returns:
      (snap_edge, orientation, top_left_point, physical_width, physical_height)

    - Snapping to LEFT or RIGHT rotates the visualizer to vertical:
        physical_width = logical_thickness, physical_height = logical_length
    - Snapping to TOP or BOTTOM rotates the visualizer to horizontal:
        physical_width = logical_length, physical_height = logical_thickness
    - In FREE mode: retains current orientation and dimensions, constrained to screen.
    """
    if screen is None:
        screen = get_screen_for_rect(QRect(current_pos, current_size))

    geo = screen.availableGeometry()
    x = current_pos.x()
    y = current_pos.y()
    w = current_size.width()
    h = current_size.height()

    # Calculate distances from window bounds to screen edges
    dist_left = abs(x - geo.left())
    dist_right = abs((geo.left() + geo.width()) - (x + w))
    dist_top = abs(y - geo.top())
    dist_bottom = abs((geo.top() + geo.height()) - (y + h))

    # Also detect if dragged beyond screen bounds
    is_left = x <= geo.left() + threshold or dist_left < threshold
    is_right = (x + w) >= (geo.left() + geo.width() - threshold) or dist_right < threshold
    is_top = y <= geo.top() + threshold or dist_top < threshold
    is_bottom = (y + h) >= (geo.top() + geo.height() - threshold) or dist_bottom < threshold

    candidates = []
    if is_left:
        candidates.append(("LEFT", dist_left))
    if is_right:
        candidates.append(("RIGHT", dist_right))
    if is_top:
        candidates.append(("TOP", dist_top))
    if is_bottom:
        candidates.append(("BOTTOM", dist_bottom))

    if not candidates:
        # FREE mode: retain current orientation
        if current_orientation in ("LEFT", "RIGHT"):
            phys_w = logical_thickness
            phys_h = logical_length
        else:
            phys_w = logical_length
            phys_h = logical_thickness

        clamped_x = max(geo.left(), min(x, geo.left() + geo.width() - phys_w))
        clamped_y = max(geo.top(), min(y, geo.top() + geo.height() - phys_h))
        return "NONE", current_orientation, QPoint(int(clamped_x), int(clamped_y)), phys_w, phys_h

    # Sort candidates by distance to find primary edge
    candidates.sort(key=lambda item: item[1])
    snap_edge = candidates[0][0]

    if snap_edge in ("LEFT", "RIGHT"):
        phys_w = logical_thickness
        phys_h = logical_length
        snap_x = geo.left() if snap_edge == "LEFT" else (geo.left() + geo.width() - phys_w)
        snap_y = max(geo.top(), min(y, geo.top() + geo.height() - phys_h))
        return snap_edge, snap_edge, QPoint(int(snap_x), int(snap_y)), phys_w, phys_h

    else:  # TOP, BOTTOM
        phys_w = logical_length
        phys_h = logical_thickness
        snap_y = geo.top() if snap_edge == "TOP" else (geo.top() + geo.height() - phys_h)
        snap_x = max(geo.left(), min(x, geo.left() + geo.width() - phys_w))
        return snap_edge, snap_edge, QPoint(int(snap_x), int(snap_y)), phys_w, phys_h


def calculate_preset_position(
    preset: str,
    logical_length: int,
    logical_thickness: int,
    screen: Optional[QScreen] = None,
    margin: int = 0,
    use_full_screen: bool = False
) -> Tuple[str, QPoint, int, int]:
    """
    Calculates the exact (orientation, top_left_point, physical_width, physical_height)
    for a given position preset: 'FREE', 'TOP', 'BOTTOM', 'LEFT', 'RIGHT'.

    Supports custom margins and full-screen bounding geometries for Game Overlay Mode.
    """
    if screen is None:
        screen = QApplication.primaryScreen()

    geo = screen.geometry() if use_full_screen else screen.availableGeometry()
    preset_upper = preset.upper()
    m = max(0, margin)

    if preset_upper == "TOP":
        w = logical_length
        h = logical_thickness
        x = geo.left() + (geo.width() - w) // 2
        y = geo.top() + m
        return "TOP", QPoint(int(x), int(y)), w, h
    elif preset_upper == "BOTTOM":
        w = logical_length
        h = logical_thickness
        x = geo.left() + (geo.width() - w) // 2
        y = geo.top() + geo.height() - h - m
        return "BOTTOM", QPoint(int(x), int(y)), w, h
    elif preset_upper == "LEFT":
        w = logical_thickness
        h = logical_length
        x = geo.left() + m
        y = geo.top() + (geo.height() - h) // 2
        return "LEFT", QPoint(int(x), int(y)), w, h
    elif preset_upper == "RIGHT":
        w = logical_thickness
        h = logical_length
        x = geo.left() + geo.width() - w - m
        y = geo.top() + (geo.height() - h) // 2
        return "RIGHT", QPoint(int(x), int(y)), w, h
    else:  # FREE / center
        w = logical_length
        h = logical_thickness
        x = geo.left() + (geo.width() - w) // 2
        y = geo.top() + (geo.height() - h) // 2
        return "BOTTOM", QPoint(int(x), int(y)), w, h


def get_foreground_window_rect() -> Optional[QRect]:
    """
    Retrieves the bounding rectangle of the current active foreground window on Windows.
    Returns None if on non-Windows platforms or if no valid window is foreground.
    """
    if sys.platform != "win32":
        return None

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return None

        # Exclude shell desktop / taskbar if foreground
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        cls_name = class_buf.value
        if cls_name in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return None

        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 50 and h > 50:
                return QRect(rect.left, rect.top, w, h)
    except Exception:
        pass
    return None


def is_window_fullscreen(window_rect: QRect, screen: QScreen) -> bool:
    """
    Determines if a window rectangle occupies the full screen geometry of the given monitor.
    Handles borderless fullscreen, maximized state, and DPI scaling tolerances.
    """
    if not window_rect or not screen:
        return False

    geo = screen.geometry()
    # Check if window covers screen within 12px tolerance (handles borderless offsets / maximized borders)
    matches_w = abs(window_rect.width() - geo.width()) <= 16 or window_rect.width() >= geo.width()
    matches_h = abs(window_rect.height() - geo.height()) <= 16 or window_rect.height() >= geo.height()
    matches_x = abs(window_rect.left() - geo.left()) <= 16
    matches_y = abs(window_rect.top() - geo.top()) <= 16

    return (matches_w and matches_h and matches_x and matches_y) or (
        window_rect.width() >= geo.width() - 8 and window_rect.height() >= geo.height() - 8
    )


def get_active_game_screen() -> QScreen:
    """
    Identifies the monitor currently hosting the active foreground application/game.
    If the active window spans multiple monitors, returns the screen with the largest intersection area.
    Falls back gracefully to primaryScreen().
    """
    win_rect = get_foreground_window_rect()
    if win_rect:
        return get_screen_for_rect(win_rect)
    return QApplication.primaryScreen()


def get_target_screen_by_name(target_name: str) -> QScreen:
    """
    Resolves a configured screen name to a QScreen:
    - 'Active Game Monitor': Dynamically queries the foreground application's screen.
    - 'Primary Monitor': Primary display.
    - 'Monitor 1', 'Monitor 2', ...: By index in QApplication.screens().
    - Custom screen name matching QScreen.name().
    """
    screens = QApplication.screens()
    if not screens:
        return QApplication.primaryScreen()

    if target_name == "Active Game Monitor":
        return get_active_game_screen()

    if target_name == "Primary Monitor":
        return QApplication.primaryScreen()

    # Match by "Monitor X" index
    if target_name.startswith("Monitor "):
        try:
            idx = int(target_name.replace("Monitor ", "").strip()) - 1
            if 0 <= idx < len(screens):
                return screens[idx]
        except ValueError:
            pass

    # Match by screen name
    for s in screens:
        if s.name() == target_name:
            return s

    return QApplication.primaryScreen()


def get_available_screen_options() -> List[str]:
    """
    Returns a formatted list of selectable target screen options for UI combo boxes:
    ['Active Game Monitor', 'Primary Monitor', 'Monitor 1', 'Monitor 2', ...]
    """
    options = ["Active Game Monitor", "Primary Monitor"]
    screens = QApplication.screens()
    if len(screens) > 1:
        for idx in range(len(screens)):
            options.append(f"Monitor {idx + 1}")
    return options


def apply_native_overlay_styles(
    hwnd: int,
    layer_mode: str = "Top",
    always_on_top: bool = True,
    click_through: bool = False,
    no_activate: bool = True
) -> bool:
    """
    Applies standard Windows Extended Window Styles to an HWND to guarantee
    flawless topmost, background, click-through, and non-activating desktop overlay behavior.
    """
    if sys.platform != "win32" or not hwnd:
        return False

    try:
        if not user32.IsWindow(hwnd):
            return False

        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

        # Base tool window & layered attributes
        ex_style |= (WS_EX_TOOLWINDOW | WS_EX_LAYERED)

        is_top = (layer_mode == "Top") or (layer_mode is None and always_on_top)
        is_bottom = (layer_mode == "Bottom")

        if is_top:
            ex_style |= WS_EX_TOPMOST
        else:
            ex_style &= ~WS_EX_TOPMOST

        if no_activate:
            ex_style |= WS_EX_NOACTIVATE
        else:
            ex_style &= ~WS_EX_NOACTIVATE

        if click_through:
            ex_style |= WS_EX_TRANSPARENT
        else:
            ex_style &= ~WS_EX_TRANSPARENT

        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)

        if is_top:
            target_z = HWND_TOPMOST
        elif is_bottom:
            target_z = HWND_BOTTOM
        else:
            target_z = HWND_NOTOPMOST

        user32.SetWindowPos(
            hwnd,
            target_z,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
        return True
    except Exception:
        return False


def reassert_window_topmost(hwnd: int) -> bool:
    """
    Reasserts HWND_TOPMOST Z-order without activating the window or stealing keyboard focus.
    """
    if sys.platform != "win32" or not hwnd:
        return False

    try:
        if not user32.IsWindow(hwnd):
            return False

        return bool(user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        ))
    except Exception:
        return False


def is_window_below_any_topmost(hwnd: int, excluded_hwnds: Optional[List[int]] = None) -> bool:
    """
    Checks if there is any visible topmost window above hwnd in the desktop Z-order.
    Excludes other friendly Lyrune overlay windows to prevent mutual reassertion fights.
    """
    if sys.platform != "win32" or not hwnd:
        return False

    try:
        if not user32.IsWindow(hwnd):
            return False

        excluded = set(excluded_hwnds or [])
        excluded.add(hwnd)

        curr = user32.GetTopWindow(None)
        while curr:
            if curr == hwnd:
                # Our overlay was found before any conflicting topmost window -> already on top!
                return False

            if user32.IsWindowVisible(curr) and curr not in excluded:
                ex = user32.GetWindowLongW(curr, GWL_EXSTYLE)
                if ex & WS_EX_TOPMOST:
                    # A foreign topmost window (e.g. borderless game) is positioned above us
                    return True

            curr = user32.GetWindow(curr, GW_HWNDNEXT)
    except Exception:
        pass
    return False


def is_window_below_foreground(hwnd: int) -> bool:
    """
    Checks if the given overlay HWND is positioned below the current foreground window in the desktop Z-order.
    Used for lightweight Z-guard reassertion without spamming SetWindowPos.
    """
    if sys.platform != "win32" or not hwnd:
        return False

    try:
        if not user32.IsWindow(hwnd):
            return False

        fg_hwnd = user32.GetForegroundWindow()
        if not fg_hwnd or fg_hwnd == hwnd:
            return False

        # If the foreground window is visible and placed higher than hwnd in Z-order
        curr = user32.GetTopWindow(None)
        while curr:
            if curr == fg_hwnd:
                # Foreground window was found first in top-to-bottom scan -> it is above hwnd
                return True
            if curr == hwnd:
                # Our overlay was found first -> overlay is already above foreground window
                return False
            curr = user32.GetWindow(curr, GW_HWNDNEXT)
    except Exception:
        pass
    return False


# ==============================================================================
# Linux / Hyprland Native Window Management Integration
# ==============================================================================
def is_hyprland() -> bool:
    """Checks if current session is running under Hyprland compositor."""
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))


def get_hyprland_clients() -> List[Dict[str, Any]]:
    """Fetches currently active Hyprland windows/clients via JSON IPC."""
    if not is_hyprland():
        return []
    try:
        out = subprocess.check_output(["hyprctl", "clients", "-j"], stderr=subprocess.DEVNULL, text=True)
        return json.loads(out)
    except Exception:
        return []


def hyprland_dispatch(command: str, args: str = "") -> bool:
    """Dispatches a window manager command to Hyprland."""
    if not is_hyprland():
        return False
    try:
        cmd = ["hyprctl", "dispatch", command]
        if args:
            cmd.append(args)
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
        return res.returncode == 0
    except Exception:
        return False


def sync_hyprland_window(
    window_title: str = "",
    layer_mode: str = "Top",
    target_pos: Optional[QPoint] = None,
    target_size: Optional[QSize] = None
) -> None:
    """
    Ensures the given Lyrune window floats, pins (Always on Top), and positions
    accurately under the Hyprland Wayland compositor.
    """
    if not is_hyprland():
        return

    clients = get_hyprland_clients()
    my_pid = os.getpid()

    for c in clients:
        if c.get("pid") == my_pid:
            # Match by title or class
            c_title = c.get("title", "")
            if window_title and window_title not in c_title and c.get("class") != "lyrune":
                continue

            addr = c.get("address")
            if not addr:
                continue

            # 1. Enforce Floating (prevent Hyprland tiling)
            if not c.get("floating", False):
                hyprland_dispatch("setfloating", f"address:{addr}")

            # 2. Pinning / Always on Top Layering
            is_pinned = c.get("pinned", False)
            if layer_mode == "Top":
                if not is_pinned:
                    hyprland_dispatch("pin", f"address:{addr}")
            elif layer_mode in ("Normal", "Bottom"):
                if is_pinned:
                    hyprland_dispatch("pin", f"address:{addr}")

            # 3. Position & Size
            if target_pos is not None and (target_pos.x() != -1 or target_pos.y() != -1):
                hyprland_dispatch("movewindowpixel", f"exact {target_pos.x()} {target_pos.y()},address:{addr}")
            if target_size is not None:
                hyprland_dispatch("resizewindowpixel", f"exact {target_size.width()} {target_size.height()},address:{addr}")



