"""
monitor.py — Monitor discovery, geometry, and DPI management.

Handles multi-monitor enumeration, resolution, DPI scaling, and display
change detection for the wallpaper renderer.
"""

import sys
from dataclasses import dataclass
from typing import List, Optional
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication

from lyrune.logger import log_event


@dataclass
class MonitorInfo:
    """Describes a single display monitor."""
    name: str                    # e.g. "\\\\.\\DISPLAY1" or "DP-1"
    geometry: QRect              # Physical pixel geometry (may have negative coords)
    available_geometry: QRect    # Geometry minus taskbar/panels
    dpi_scale: float             # Device pixel ratio (1.0 = 100%, 1.5 = 150%, 2.0 = 200%)
    is_primary: bool
    screen: QScreen              # Reference to the Qt screen object

    @property
    def physical_width(self) -> int:
        return self.geometry.width()

    @property
    def physical_height(self) -> int:
        return self.geometry.height()

    @property
    def aspect_ratio(self) -> float:
        if self.geometry.height() == 0:
            return 16.0 / 9.0
        return self.geometry.width() / self.geometry.height()


def enumerate_monitors() -> List[MonitorInfo]:
    """
    Enumerates all connected monitors and returns their geometry,
    DPI scaling, and primary status.

    Returns an empty list if no screens are available (headless mode).
    """
    app = QApplication.instance()
    if not app:
        return []

    screens = app.screens()
    if not screens:
        return []

    primary = app.primaryScreen()
    monitors = []

    for screen in screens:
        monitors.append(MonitorInfo(
            name=screen.name(),
            geometry=screen.geometry(),
            available_geometry=screen.availableGeometry(),
            dpi_scale=screen.devicePixelRatio(),
            is_primary=(screen == primary),
            screen=screen,
        ))

    log_event(
        f"[Monitor] Enumerated {len(monitors)} monitor(s): "
        + ", ".join(
            f"{m.name} ({m.geometry.width()}x{m.geometry.height()} "
            f"@ {m.dpi_scale:.0%} DPI{' [PRIMARY]' if m.is_primary else ''})"
            for m in monitors
        )
    )
    return monitors


def get_monitor_by_name(target_name: str) -> Optional[MonitorInfo]:
    """
    Resolves a display mode name to a MonitorInfo:
    - "primary" → primary monitor
    - "all" → primary monitor (span mode deferred)
    - "Monitor 1", "Monitor 2" → by index
    - Exact screen name → by QScreen.name()
    """
    monitors = enumerate_monitors()
    if not monitors:
        return None

    lower = target_name.lower().strip()

    if lower in ("primary", "all"):
        for m in monitors:
            if m.is_primary:
                return m
        return monitors[0]

    # "Monitor X" → index-based
    if lower.startswith("monitor "):
        try:
            idx = int(lower.replace("monitor ", "").strip()) - 1
            if 0 <= idx < len(monitors):
                return monitors[idx]
        except ValueError:
            pass

    # Exact name match
    for m in monitors:
        if m.name == target_name:
            return m

    # Fallback to primary
    for m in monitors:
        if m.is_primary:
            return m
    return monitors[0] if monitors else None


def get_full_desktop_geometry() -> QRect:
    """
    Returns the bounding rectangle of the entire virtual desktop
    spanning all monitors. May have negative coordinates.
    """
    monitors = enumerate_monitors()
    if not monitors:
        return QRect(0, 0, 1920, 1080)

    left = min(m.geometry.left() for m in monitors)
    top = min(m.geometry.top() for m in monitors)
    right = max(m.geometry.right() for m in monitors)
    bottom = max(m.geometry.bottom() for m in monitors)

    return QRect(left, top, right - left + 1, bottom - top + 1)


def get_wallpaper_display_options() -> List[str]:
    """
    Returns a formatted list of display options for the wallpaper settings UI:
    ['Primary Display', 'All Displays', 'Monitor 1', 'Monitor 2', ...]
    """
    options = ["Primary Display", "All Displays"]
    monitors = enumerate_monitors()
    if len(monitors) > 1:
        for i, m in enumerate(monitors):
            label = f"Monitor {i + 1}"
            if m.is_primary:
                label += " (Primary)"
            # Append resolution for clarity
            label += f" — {m.geometry.width()}x{m.geometry.height()}"
            options.append(label)
    return options
