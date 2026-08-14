"""
visualizer_window.py — Independent floating desktop window for the Lyrune visualizer.

Responsibilities:
  - Independent top-level QWidget (no parent/child attachment to LyricsWidget)
  - Frameless, translucent, tool window with smooth QPainter rendering
  - Multi-monitor aware free-floating and edge snapping (50px proximity threshold)
  - Automatic orientation transitions (BOTTOM, TOP, LEFT, RIGHT, FREE)
  - Logical dimension preservation across orientation axis swaps
  - Click-through mode, always-on-top, and screen-capture exclusion
  - Multi-monitor recovery ensuring the window never gets lost off-screen
"""

import sys
from typing import Optional, Dict, Any
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtGui import QPainter, QMouseEvent, QResizeEvent

from lyrune.visualizer.base import BaseVisualizer
from lyrune.window_utils import (
    get_screen_for_rect,
    constrain_to_work_area,
    calculate_edge_snap,
    calculate_visualizer_snap,
    calculate_preset_position
)
from lyrune.logger import log_event


class VisualizerWindow(QWidget):
    """
    Independent floating visualizer window.
    """
    position_changed = pyqtSignal(dict)  # Emits geometry & orientation updates for persistence

    def __init__(self, visualizer: Optional[BaseVisualizer] = None, parent: Optional[QWidget] = None):
        # Must be parent=None so it is a true independent desktop widget
        super().__init__(None)

        self.visualizer: Optional[BaseVisualizer] = visualizer

        # State
        self._snap_edge: str = "BOTTOM"       # "NONE", "BOTTOM", "TOP", "LEFT", "RIGHT"
        self._orientation: str = "BOTTOM"     # "BOTTOM", "TOP", "LEFT", "RIGHT"
        self._logical_length: int = 320       # Primary axis dimension (width in HORIZ, height in VERT)
        self._logical_thickness: int = 64     # Secondary axis dimension (height in HORIZ, width in VERT)

        self._is_dragging: bool = False
        self._drag_pos: QPoint = QPoint()
        self._drag_start_pos: QPoint = QPoint()
        self._is_hovered: bool = False
        self._always_on_top: bool = True
        self._click_through: bool = False
        self._exclude_from_capture: bool = False

        self._init_window()

    def _init_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self._apply_orientation_geometry()

        # Connect screen topology changes to ensure on-screen recovery
        app = QApplication.instance()
        if app:
            app.screenAdded.connect(self._on_screens_changed)
            app.screenRemoved.connect(self._on_screens_changed)
            app.primaryScreenChanged.connect(self._on_screens_changed)

    def set_visualizer(self, visualizer: BaseVisualizer) -> None:
        """Sets or swaps the active visualizer strategy."""
        self.visualizer = visualizer
        if self.visualizer:
            self.visualizer.set_orientation(self._orientation)
            self.visualizer.resize(self.width(), self.height())
        self.update()

    def _apply_orientation_geometry(self) -> None:
        """Calculates physical width & height from logical length and thickness."""
        if self._orientation in ("BOTTOM", "TOP"):
            w = self._logical_length
            h = self._logical_thickness
        else:  # LEFT, RIGHT
            w = self._logical_thickness
            h = self._logical_length

        self.resize(w, h)
        if self.visualizer:
            self.visualizer.set_orientation(self._orientation)
            self.visualizer.resize(w, h)

    def set_logical_dimensions(self, length: int, thickness: int) -> None:
        """Updates length/thickness and adjusts window size according to orientation."""
        self._logical_length = max(80, length)
        self._logical_thickness = max(24, thickness)
        self._apply_orientation_geometry()
        self._reposition_after_resize()

    def _reposition_after_resize(self) -> None:
        """Re-clamps position to screen work area after resizing."""
        current_pos = self.pos()
        screen = get_screen_for_rect(self.geometry())
        safe_pos = constrain_to_work_area(current_pos, self.size(), screen)
        if safe_pos != current_pos:
            self.move(safe_pos)

    def set_preset_position(self, preset: str) -> None:
        """Snaps the visualizer to a preset edge ('TOP', 'BOTTOM', 'LEFT', 'RIGHT', 'FREE')."""
        preset_upper = preset.upper()
        screen = get_screen_for_rect(self.geometry())

        if preset_upper in ("TOP", "BOTTOM", "LEFT", "RIGHT"):
            orientation, target_pos, phys_w, phys_h = calculate_preset_position(
                preset_upper, self._logical_length, self._logical_thickness, screen
            )
            self._orientation = orientation
            self._snap_edge = preset_upper

            self.resize(phys_w, phys_h)
            if self.visualizer:
                self.visualizer.set_orientation(self._orientation)
                self.visualizer.resize(phys_w, phys_h)

            self.move(target_pos)
            log_event(f"📐 [Visualizer] Snapped to preset edge: {preset_upper} ({phys_w}x{phys_h})", force=True)
        else:  # FREE
            self._snap_edge = "NONE"
            log_event("📐 [Visualizer] Set to FREE floating mode", force=True)

        self._emit_position_changed()
        self.update()

    def restore_saved_state(self, s: Dict[str, Any]) -> None:
        """Restores position, orientation, snapping state, and dimensions from settings."""
        self._logical_length = s.get("visualizer_width", 320)
        self._logical_thickness = s.get("visualizer_height", 64)
        self._orientation = s.get("visualizer_orientation", "BOTTOM")
        self._snap_edge = s.get("visualizer_snap_edge", "BOTTOM")

        self._apply_orientation_geometry()

        x = s.get("visualizer_x", -1)
        y = s.get("visualizer_y", -1)

        primary_geo = QApplication.primaryScreen().availableGeometry()

        if x >= -5000 and y >= -5000 and x != -1 and y != -1:
            test_rect = QRect(x, y, self.width(), self.height())
            screen = get_screen_for_rect(test_rect)
            safe_pos = constrain_to_work_area(QPoint(x, y), self.size(), screen)
            self.move(safe_pos)
        else:
            # Default to bottom-center
            cx = primary_geo.left() + (primary_geo.width() - self.width()) // 2
            cy = primary_geo.top() + primary_geo.height() - self.height() - 20
            self.move(cx, cy)
            self._orientation = "BOTTOM"
            self._snap_edge = "BOTTOM"
            self._apply_orientation_geometry()

        self.apply_settings(s)
        log_event(f"🔄 [Visualizer] Restored state (Orientation: {self._orientation}, Snap: {self._snap_edge}, Pos: {self.pos().x()},{self.pos().y()})")

    def apply_settings(self, s: Dict[str, Any]) -> None:
        """Applies window flags, click-through, always-on-top, and visualizer styles."""
        always_top = s.get("visualizer_always_on_top", True)
        click_through = s.get("visualizer_click_through", False)
        exclude_capture = s.get("visualizer_exclude_from_capture", False)

        was_visible = self.isVisible()
        current_flags = self.windowFlags()

        if always_top:
            current_flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            current_flags &= ~Qt.WindowType.WindowStaysOnTopHint

        if click_through:
            current_flags |= Qt.WindowType.WindowTransparentForInput
        else:
            current_flags &= ~Qt.WindowType.WindowTransparentForInput

        self.setWindowFlags(current_flags)
        if was_visible:
            self.show()

        # Display Affinity for screen capture exclusion (Windows)
        if sys.platform == "win32" and self.winId():
            try:
                import ctypes
                hwnd = int(self.winId())
                affinity = 0x00000011 if exclude_capture else 0x0
                ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, affinity)
            except Exception as e:
                log_event(f"[Visualizer DisplayAffinity Error] {e}")

        # Update dimensions if changed
        new_len = s.get("visualizer_width", self._logical_length)
        new_thick = s.get("visualizer_height", self._logical_thickness)
        if new_len != self._logical_length or new_thick != self._logical_thickness:
            self._logical_length = max(80, new_len)
            self._logical_thickness = max(24, new_thick)
            self._apply_orientation_geometry()
            self._reposition_after_resize()

        if self.visualizer:
            self.visualizer.set_style(s)
            self.visualizer.set_orientation(self._orientation)

        self.update()

    def _on_screens_changed(self) -> None:
        """Recalculates position when display topology changes to prevent off-screen loss."""
        current_pos = self.pos()
        safe_pos = constrain_to_work_area(current_pos, self.size())
        if safe_pos != current_pos:
            self.move(safe_pos)
            self._emit_position_changed()
            log_event(f"🖥️ [Visualizer] Monitor topology changed; repositioned to {safe_pos.x()},{safe_pos.y()}", force=True)

    # --- Mouse Interaction & Dragging ---
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_start_pos = self.pos()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            self.move(new_pos)

            # If currently snapped, detect if user is pulling away from the edge
            if self._snap_edge != "NONE":
                dist = (new_pos - self._drag_start_pos).manhattanLength()
                if dist > 25:
                    # Break snap to FREE mode while retaining current orientation
                    self._snap_edge = "NONE"
                    log_event("📐 [Visualizer] Dragged out of snap; entered FREE mode")

            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False

            # Determine border snapping and dynamic rotation
            snap_edge, orient, snapped_pos, phys_w, phys_h = calculate_visualizer_snap(
                current_pos=self.pos(),
                current_size=self.size(),
                logical_length=self._logical_length,
                logical_thickness=self._logical_thickness,
                current_orientation=self._orientation,
                threshold=60
            )

            self._snap_edge = snap_edge
            self._orientation = orient

            # Resize physical window and notify visualizer of orientation change
            self.resize(phys_w, phys_h)
            if self.visualizer:
                self.visualizer.set_orientation(self._orientation)
                self.visualizer.resize(phys_w, phys_h)

            self.move(snapped_pos)
            if snap_edge != "NONE":
                log_event(f"🧲 [Visualizer] Snapped & Rotated to {snap_edge} border ({phys_w}x{phys_h})", force=True)
            else:
                log_event(f"📐 [Visualizer] Floating in FREE mode ({self._orientation})", force=True)

            self._emit_position_changed()
            self.update()
            event.accept()
        super().mouseReleaseEvent(event)

    def _emit_position_changed(self) -> None:
        """Notifies manager of position updates for debounced settings persistence."""
        info = {
            "visualizer_x": self.pos().x(),
            "visualizer_y": self.pos().y(),
            "visualizer_orientation": self._orientation,
            "visualizer_snap_edge": self._snap_edge,
            "visualizer_width": self._logical_length,
            "visualizer_height": self._logical_thickness
        }
        self.position_changed.emit(info)

    def enterEvent(self, event) -> None:
        self._is_hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._is_hovered = False
        super().leaveEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.visualizer:
            self.visualizer.resize(self.width(), self.height())

    def paintEvent(self, event) -> None:
        """Paints the active visualizer onto the translucent window."""
        painter = QPainter(self)
        if self.visualizer:
            self.visualizer.paint(painter, self.rect())
        painter.end()
