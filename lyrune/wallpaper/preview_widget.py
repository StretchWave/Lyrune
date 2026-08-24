"""
preview_widget.py — Interactive wallpaper preview and editor widget.

Uses the canonical WallpaperTransform pipeline to ensure 100% mathematical
consistency with the desktop WorkerW renderer across all scaling modes.
"""

import os
import time
import math
from typing import Optional
from PyQt6.QtCore import Qt, QRect, QRectF, QPointF, QSizeF, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPixmap, QPen, QBrush, QCursor, QMouseEvent,
    QPainterPath, QRadialGradient, QFont, QLinearGradient
)
from PyQt6.QtWidgets import QWidget

from lyrune.wallpaper.model import WallpaperConfig, MediaSnapshot
from lyrune.wallpaper.vinyl_renderer import VinylRenderer
from lyrune.wallpaper.transform import WallpaperTransform
from lyrune.logger import log_event


class WallpaperPreviewWidget(QWidget):
    """
    Interactive wallpaper preview canvas for the settings dialog.
    Directly uses WallpaperTransform for reversible coordinate mapping.
    """

    vinyl_position_changed = pyqtSignal(float, float)   # (logical_x, logical_y)
    vinyl_size_changed = pyqtSignal(float)               # logical_size

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 180)
        self.setMouseTracking(True)

        self._config = WallpaperConfig()
        self._media = MediaSnapshot()
        self._vinyl_renderer = VinylRenderer()

        self._background_pixmap: Optional[QPixmap] = None
        self._show_debug_overlay: bool = False

        # Interaction state (stored in logical coordinates)
        self._is_dragging: bool = False
        self._is_resizing: bool = False
        self._is_selected: bool = False
        self._drag_start_lx: float = 0.0
        self._drag_start_ly: float = 0.0
        self._drag_offset_vx: float = 0.0
        self._drag_offset_vy: float = 0.0
        self._resize_start_dist: float = 0.0
        self._resize_start_size: float = 0.0

        # Animation
        self._rotation_angle: float = 0.0
        self._last_tick_time: float = time.monotonic()

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)  # 60 FPS
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_timer.start()

    def get_transform(self) -> WallpaperTransform:
        """Returns the current canonical WallpaperTransform."""
        if self._background_pixmap and not self._background_pixmap.isNull():
            src_size = QSizeF(self._background_pixmap.width(), self._background_pixmap.height())
        else:
            src_size = QSizeF(16.0, 9.0)

        view_size = QSizeF(max(1, self.width()), max(1, self.height()))
        return WallpaperTransform(src_size, view_size, self._config.scaling_mode)

    def set_config(self, config: WallpaperConfig) -> None:
        self._config = config
        self.update()

    def set_media(self, media: MediaSnapshot) -> None:
        self._media = media
        if media.album_art:
            self._vinyl_renderer.set_album_art(media.album_art)
        self.update()

    def set_background(self, path: str, scaling_mode: str = "fill") -> None:
        if not path or not os.path.isfile(path):
            self._background_pixmap = None
            self.update()
            return

        try:
            from lyrune.wallpaper.static_renderer import is_supported_image
            if is_supported_image(path):
                self._background_pixmap = QPixmap(path)
            else:
                self._background_pixmap = None
            self.update()
        except Exception as e:
            log_event(f"[Preview] Failed to load background: {e}")
            self._background_pixmap = None

    def update_vinyl_position(self, x: float, y: float) -> None:
        self._config.vinyl_x = x
        self._config.vinyl_y = y
        self.update()

    def update_vinyl_size(self, size: float) -> None:
        self._config.vinyl_size = size
        self.update()

    def toggle_debug_overlay(self) -> None:
        self._show_debug_overlay = not self._show_debug_overlay
        self.update()

    # === Painting ===

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect()
        w = rect.width()
        h = rect.height()

        transform = self.get_transform()
        content_rect = transform.content_rect

        # 1. Background
        painter.save()
        # Clip background to preview window bounds
        painter.setClipRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5))

        if self._background_pixmap and not self._background_pixmap.isNull():
            # Letterbox fill around content_rect
            painter.fillRect(rect, QColor(6, 8, 14, 255))
            painter.drawPixmap(content_rect.toRect(), self._background_pixmap)
        else:
            # Celestial cosmic night landscape fallback
            bg_grad = QLinearGradient(0, 0, w, h)
            bg_grad.setColorAt(0.0, QColor(15, 12, 35))
            bg_grad.setColorAt(0.4, QColor(42, 18, 68))
            bg_grad.setColorAt(0.7, QColor(18, 38, 75))
            bg_grad.setColorAt(1.0, QColor(8, 12, 22))
            painter.fillRect(rect, QBrush(bg_grad))

            # Aurora streak
            path = QPainterPath()
            path.moveTo(0, h * 0.75)
            path.cubicTo(w * 0.35, h * 0.40, w * 0.65, h * 0.60, w, h * 0.30)
            path.lineTo(w, h)
            path.lineTo(0, h)
            path.closeSubpath()
            aurora_grad = QLinearGradient(0, h * 0.3, w, h)
            aurora_grad.setColorAt(0.0, QColor(0, 180, 255, 45))
            aurora_grad.setColorAt(0.5, QColor(140, 40, 220, 35))
            aurora_grad.setColorAt(1.0, QColor(8, 12, 22, 180))
            painter.fillPath(path, QBrush(aurora_grad))

            # Mountain silhouette
            m_path = QPainterPath()
            m_path.moveTo(0, h)
            m_path.lineTo(0, h * 0.85)
            m_path.lineTo(w * 0.25, h * 0.70)
            m_path.lineTo(w * 0.45, h * 0.80)
            m_path.lineTo(w * 0.70, h * 0.62)
            m_path.lineTo(w, h * 0.78)
            m_path.lineTo(w, h)
            m_path.closeSubpath()
            painter.fillPath(m_path, QBrush(QColor(6, 8, 14, 230)))

        # Ambient quote & sample lyrics on left
        painter.setPen(QPen(QColor(255, 255, 255, 120)))
        painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        painter.drawText(QRectF(16, 14, 30, 20), "“")

        lyrics_font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        painter.setFont(lyrics_font)
        lines = ["Can you feel it?", "The way it", "makes you move", "Can you feel it?"]
        for idx, line in enumerate(lines):
            alpha = 240 if idx == 0 or idx == 3 else 160
            painter.setPen(QColor(240, 241, 245, alpha))
            painter.drawText(QRectF(16, 38 + idx * 16, w * 0.45, 20), Qt.AlignmentFlag.AlignLeft, line)
        painter.restore()

        # 2. Vinyl Record
        vx, vy = transform.logical_to_viewport(self._config.vinyl_x, self._config.vinyl_y)
        diameter = transform.logical_to_viewport_size(self._config.vinyl_size)

        self._vinyl_renderer.render(
            painter, vx, vy, diameter,
            self._rotation_angle, self._config.vinyl_opacity,
            self._config, self._media
        )

        # 3. Selection & Resize Handle
        if self._is_selected or self._is_dragging or self._is_resizing:
            self._draw_selection_handles(painter, vx, vy, diameter / 2.0)

        # 4. Canvas Border
        painter.setPen(QPen(QColor(255, 255, 255, 24), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

        # 5. Developer Transform Debug Overlay (if active)
        if self._show_debug_overlay:
            self._draw_debug_hud(painter, transform)

    def _draw_selection_handles(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        painter.save()
        painter.setPen(QPen(QColor(46, 213, 115, 220), 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius + 3, radius + 3)

        # Resize handle at bottom-right 45°
        hx = cx + (radius + 3) * 0.707
        hy = cy + (radius + 3) * 0.707
        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.setBrush(QBrush(QColor(46, 213, 115, 240)))
        painter.drawEllipse(QPointF(hx, hy), 5, 5)
        painter.restore()

    def _draw_debug_hud(self, painter: QPainter, transform: WallpaperTransform) -> None:
        info = transform.get_debug_info(self._config.vinyl_x, self._config.vinyl_y, self._config.vinyl_size)
        painter.save()
        painter.setBrush(QBrush(QColor(10, 13, 20, 210)))
        painter.setPen(QPen(QColor(46, 213, 115, 180), 1))
        painter.drawRoundedRect(QRectF(self.width() - 190, 8, 182, 90), 6, 6)

        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Consolas", 8))
        lines = [
            f"Mode: {info['mode']}",
            f"Logical: X={info['logical'][0]} Y={info['logical'][1]}",
            f"L-Size: {info['logical'][2]}",
            f"Viewport: X={info['viewport'][0]} Y={info['viewport'][1]}",
            f"V-Size: {info['viewport'][2]}px"
        ]
        for i, l in enumerate(lines):
            painter.drawText(self.width() - 182, 22 + i * 14, l)
        painter.restore()

    # === Mouse Interaction ===

    def _vinyl_hit_test(self, pos: QPointF) -> bool:
        transform = self.get_transform()
        vx, vy = transform.logical_to_viewport(self._config.vinyl_x, self._config.vinyl_y)
        radius = transform.logical_to_viewport_size(self._config.vinyl_size) / 2.0
        dx = pos.x() - vx
        dy = pos.y() - vy
        return (dx * dx + dy * dy) <= (radius + 8) ** 2

    def _resize_handle_hit_test(self, pos: QPointF) -> bool:
        transform = self.get_transform()
        vx, vy = transform.logical_to_viewport(self._config.vinyl_x, self._config.vinyl_y)
        radius = transform.logical_to_viewport_size(self._config.vinyl_size) / 2.0
        hx = vx + (radius + 3) * 0.707
        hy = vy + (radius + 3) * 0.707
        dx = pos.x() - hx
        dy = pos.y() - hy
        return (dx * dx + dy * dy) <= 12 ** 2

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        pos = event.position()
        transform = self.get_transform()

        if self._resize_handle_hit_test(pos):
            self._is_resizing = True
            self._is_selected = True
            vx, vy = transform.logical_to_viewport(self._config.vinyl_x, self._config.vinyl_y)
            self._resize_start_dist = math.sqrt((pos.x() - vx) ** 2 + (pos.y() - vy) ** 2)
            self._resize_start_size = self._config.vinyl_size
            self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
            event.accept()

        elif self._vinyl_hit_test(pos):
            self._is_dragging = True
            self._is_selected = True
            vx, vy = transform.logical_to_viewport(self._config.vinyl_x, self._config.vinyl_y)
            self._drag_offset_vx = pos.x() - vx
            self._drag_offset_vy = pos.y() - vy
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()

        else:
            self._is_selected = False
            self.update()
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        transform = self.get_transform()

        if self._is_dragging:
            # Convert mouse viewport pos minus offset into logical coordinates
            target_vx = pos.x() - self._drag_offset_vx
            target_vy = pos.y() - self._drag_offset_vy
            lx, ly = transform.viewport_to_logical(target_vx, target_vy)

            # Clamp within visible boundaries
            lx = max(-0.2, min(1.2, lx))
            ly = max(-0.2, min(1.2, ly))

            self._config.vinyl_x = lx
            self._config.vinyl_y = ly
            self.vinyl_position_changed.emit(lx, ly)
            self.update()
            event.accept()

        elif self._is_resizing:
            vx, vy = transform.logical_to_viewport(self._config.vinyl_x, self._config.vinyl_y)
            current_dist = math.sqrt((pos.x() - vx) ** 2 + (pos.y() - vy) ** 2)
            if self._resize_start_dist > 0:
                scale_ratio = current_dist / self._resize_start_dist
                new_logical_size = max(0.05, min(0.80, self._resize_start_size * scale_ratio))
                self._config.vinyl_size = new_logical_size
                self.vinyl_size_changed.emit(new_logical_size)
                self.update()
            event.accept()

        else:
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
        if not self.isVisible():
            return
        now = time.monotonic()
        dt = now - self._last_tick_time
        self._last_tick_time = now

        if self._config.rotate_while_playing and self._config.rotation_speed > 0:
            self._rotation_angle = (
                self._rotation_angle + dt * (360.0 / self._config.rotation_speed)
            ) % 360.0

        self._vinyl_renderer.advance_crossfade(dt)
        self.update()
