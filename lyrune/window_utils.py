"""
window_utils.py — Shared window geometry, multi-monitor detection, and edge-snapping utilities.

Provides centralized, screen-aware geometry calculations for frameless desktop widgets
(e.g., LyricsWidget, VisualizerWindow) without coupling the widgets together.
"""

from typing import Optional, Tuple
from PyQt6.QtCore import QPoint, QRect, QSize
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication


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
    screen: Optional[QScreen] = None
) -> Tuple[str, QPoint, int, int]:
    """
    Calculates the exact (orientation, top_left_point, physical_width, physical_height)
    for a given position preset: 'FREE', 'TOP', 'BOTTOM', 'LEFT', 'RIGHT'.
    """
    if screen is None:
        screen = QApplication.primaryScreen()

    geo = screen.availableGeometry()
    preset_upper = preset.upper()

    if preset_upper == "TOP":
        w = logical_length
        h = logical_thickness
        x = geo.left() + (geo.width() - w) // 2
        y = geo.top()
        return "TOP", QPoint(int(x), int(y)), w, h
    elif preset_upper == "BOTTOM":
        w = logical_length
        h = logical_thickness
        x = geo.left() + (geo.width() - w) // 2
        y = geo.top() + geo.height() - h
        return "BOTTOM", QPoint(int(x), int(y)), w, h
    elif preset_upper == "LEFT":
        w = logical_thickness
        h = logical_length
        x = geo.left()
        y = geo.top() + (geo.height() - h) // 2
        return "LEFT", QPoint(int(x), int(y)), w, h
    elif preset_upper == "RIGHT":
        w = logical_thickness
        h = logical_length
        x = geo.left() + geo.width() - w
        y = geo.top() + (geo.height() - h) // 2
        return "RIGHT", QPoint(int(x), int(y)), w, h
    else:  # FREE / center
        w = logical_length
        h = logical_thickness
        x = geo.left() + (geo.width() - w) // 2
        y = geo.top() + (geo.height() - h) // 2
        return "BOTTOM", QPoint(int(x), int(y)), w, h
