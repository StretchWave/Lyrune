"""
preview_widget.py — Interactive wallpaper preview and editor widget.

Provides a miniature live preview of the wallpaper inside the settings dialog.
Supports:
  - Background rendering (static image or video thumbnail)
  - Vinyl drag positioning (direct manipulation, no X/Y sliders)
  - Vinyl resize via corner handle
  - Normalized coordinate conversion
  - Selection state visual feedback
"""

import os
import time
import math
from typing import Optional
from PyQt6.QtCore import Qt, QRect, QRectF, QPointF, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPixmap, QPen, QBrush, QCursor, QMouseEvent,
    QPainterPath, QRadialGradient
)
from PyQt6.QtWidgets import QWidget

from lyrune.wallpaper.model import WallpaperConfig, MediaSnapshot
from lyrune.wallpaper.vinyl_renderer import VinylRenderer
from lyrune.wallpaper.image_cache import scale_image_to_mode
from lyrune.logger import log_event


class WallpaperPreviewWidget(QWidget):
    """
    Interactive wallpaper preview canvas for the settings dialog.

    Users can:
    - See a scaled-down preview of their wallpaper background
    - Drag the vinyl record to position it
    - Drag a corner handle to resize the vinyl
    - See current album art and metadata rendered on the vinyl
    """

    # Signals emitted when user drags/resizes the vinyl
    vinyl_position_changed = pyqtSignal(float, float)   # (normalized_x, normalized_y)
    vinyl_size_changed = pyqtSignal(float)               # normalized_size

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 225)
        self.setMouseTracking(True)

        # Configuration (local copy for preview)
        self._config = WallpaperConfig()
        self._media = MediaSnapshot()
        self._vinyl_renderer = VinylRenderer()

        # Background
        self._background_pixmap: Optional[QPixmap] = None
        self._scaled_bg: Optional[QPixmap] = None

        # Interaction state
        self._is_dragging: bool = False
        self._is_resizing: bool = False
        self._is_selected: bool = False
        self._drag_offset_x: float = 0.0
        self._drag_offset_y: float = 0.0
        self._resize_start_size: float = 0.0
        self._resize_start_dist: float = 0.0

        # Animation
        self._rotation_angle: float = 0.0
        self._last_tick_time: float = time.monotonic()

        # 30 FPS animation timer for preview
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_timer.start()

    def set_config(self, config: WallpaperConfig) -> None:
        """Updates the preview configuration."""
        self._config = config
        self.update()

    def set_media(self, media: MediaSnapshot) -> None:
        """Updates the preview media state."""
        self._media = media
        if media.album_art:
            self._vinyl_renderer.set_album_art(media.album_art)
        self.update()

    def set_background(self, path: str, scaling_mode: str = "fill") -> None:
        """Loads and displays the wallpaper background image."""
        if not path or not os.path.isfile(path):
            self._background_pixmap = None
            self._scaled_bg = None
            self.update()
            return

        try:
            from lyrune.wallpaper.static_renderer import is_supported_image
            from lyrune.wallpaper.video_renderer import is_supported_video

            if is_supported_image(path):
                self._background_pixmap = QPixmap(path)
            elif is_supported_video(path):
                # For video, show a black background (full video preview is optional)
                self._background_pixmap = None
            else:
                self._background_pixmap = None

            self._scaled_bg = None  # Force re-scale on next paint
            self.update()
        except Exception as e:
            log_event(f"[Preview] Failed to load background: {e}")
            self._background_pixmap = None

    def update_vinyl_position(self, x: float, y: float) -> None:
        """Externally updates the vinyl position (from slider or settings)."""
        self._config.vinyl_x = x
        self._config.vinyl_y = y
        self.update()

    def update_vinyl_size(self, size: float) -> None:
        """Externally updates the vinyl size."""
        self._config.vinyl_size = size
        self.update()

    # === Painting ===

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect()
        w = rect.width()
        h = rect.height()

        # Background
        if self._background_pixmap and not self._background_pixmap.isNull():
            if self._scaled_bg is None or self._scaled_bg.size() != rect.size():
                self._scaled_bg = scale_image_to_mode(
                    self._background_pixmap, w, h,
                    self._config.scaling_mode
                )
            painter.drawPixmap(0, 0, self._scaled_bg)
        else:
            # Dark gradient background placeholder
            bg_grad = QRadialGradient(QPointF(w * 0.5, h * 0.5), max(w, h) * 0.7)
            bg_grad.setColorAt(0.0, QColor(25, 25, 30))
            bg_grad.setColorAt(1.0, QColor(8, 8, 12))
            painter.fillRect(rect, QBrush(bg_grad))

        # Vinyl
        center_x = self._config.vinyl_x * w
        center_y = self._config.vinyl_y * h
        diameter = self._config.vinyl_size * w

        self._vinyl_renderer.render(
            painter, center_x, center_y, diameter,
            self._rotation_angle, self._config.vinyl_opacity,
            self._config, self._media
        )

        # Selection indicator
        if self._is_selected or self._is_dragging or self._is_resizing:
            self._draw_selection_handles(painter, center_x, center_y, diameter / 2)

        # Border for the preview container
        painter.setPen(QPen(QColor(60, 60, 65), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 6, 6)

        painter.end()

    def _draw_selection_handles(self, painter: QPainter, cx: float, cy: float,
                                 radius: float) -> None:
        """Draws selection outline and resize handle around the vinyl."""
        # Selection circle
        painter.setPen(QPen(QColor(29, 185, 84, 180), 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius + 4, radius + 4)

        # Resize handle (bottom-right of bounding box)
        handle_x = cx + radius * 0.707  # cos(45°)
        handle_y = cy + radius * 0.707  # sin(45°)
        handle_size = 8

        painter.setPen(QPen(QColor(29, 185, 84), 2))
        painter.setBrush(QBrush(QColor(29, 185, 84, 200)))
        painter.drawEllipse(QPointF(handle_x, handle_y), handle_size, handle_size)

    # === Mouse Interaction ===

    def _vinyl_hit_test(self, pos) -> bool:
        """Returns True if the mouse position is within the vinyl circle."""
        w = self.width()
        h = self.height()
        cx = self._config.vinyl_x * w
        cy = self._config.vinyl_y * h
        radius = (self._config.vinyl_size * w) / 2

        dx = pos.x() - cx
        dy = pos.y() - cy
        return (dx * dx + dy * dy) <= (radius + 10) ** 2

    def _resize_handle_hit_test(self, pos) -> bool:
        """Returns True if the mouse position is near the resize handle."""
        w = self.width()
        h = self.height()
        cx = self._config.vinyl_x * w
        cy = self._config.vinyl_y * h
        radius = (self._config.vinyl_size * w) / 2

        handle_x = cx + radius * 0.707
        handle_y = cy + radius * 0.707
        dx = pos.x() - handle_x
        dy = pos.y() - handle_y
        return (dx * dx + dy * dy) <= 15 ** 2

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        pos = event.position()

        if self._resize_handle_hit_test(pos):
            # Start resize
            self._is_resizing = True
            self._is_selected = True
            w = self.width()
            cx = self._config.vinyl_x * w
            cy = self._config.vinyl_y * self.height()
            self._resize_start_size = self._config.vinyl_size
            self._resize_start_dist = math.sqrt(
                (pos.x() - cx) ** 2 + (pos.y() - cy) ** 2
            )
            self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
            event.accept()

        elif self._vinyl_hit_test(pos):
            # Start drag
            self._is_dragging = True
            self._is_selected = True
            w = self.width()
            h = self.height()
            cx = self._config.vinyl_x * w
            cy = self._config.vinyl_y * h
            self._drag_offset_x = pos.x() - cx
            self._drag_offset_y = pos.y() - cy
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()

        else:
            self._is_selected = False
            self.update()
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        w = self.width()
        h = self.height()

        if self._is_dragging:
            # Update vinyl position (maintaining original click offset)
            new_x = (pos.x() - self._drag_offset_x) / w
            new_y = (pos.y() - self._drag_offset_y) / h

            # Keep a portion within bounds
            min_visible = 0.05
            new_x = max(-0.3, min(1.3, new_x))
            new_y = max(-0.3, min(1.3, new_y))

            self._config.vinyl_x = new_x
            self._config.vinyl_y = new_y
            self.vinyl_position_changed.emit(new_x, new_y)
            self.update()
            event.accept()

        elif self._is_resizing:
            cx = self._config.vinyl_x * w
            cy = self._config.vinyl_y * h
            current_dist = math.sqrt((pos.x() - cx) ** 2 + (pos.y() - cy) ** 2)

            if self._resize_start_dist > 0:
                scale_factor = current_dist / self._resize_start_dist
                new_size = self._resize_start_size * scale_factor
                new_size = max(0.05, min(0.6, new_size))  # Clamp size
                self._config.vinyl_size = new_size
                self.vinyl_size_changed.emit(new_size)
                self.update()
            event.accept()

        else:
            # Update cursor based on hover
            if self._resize_handle_hit_test(pos):
                self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
            elif self._vinyl_hit_test(pos):
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging:
                self._is_dragging = False
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            elif self._is_resizing:
                self._is_resizing = False
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
        super().mouseReleaseEvent(event)

    # === Animation ===

    def _on_anim_tick(self) -> None:
        """Updates rotation animation for the preview."""
        if not self.isVisible():
            return

        now = time.monotonic()
        dt = now - self._last_tick_time
        self._last_tick_time = now

        # Rotate if configured
        if self._config.rotate_while_playing and self._config.rotation_speed > 0:
            self._rotation_angle = (
                self._rotation_angle + dt * (360.0 / self._config.rotation_speed)
            ) % 360.0

        # Advance crossfade
        self._vinyl_renderer.advance_crossfade(dt)

        self.update()
