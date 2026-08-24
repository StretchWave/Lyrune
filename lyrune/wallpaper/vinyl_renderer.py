"""
vinyl_renderer.py — Procedural vinyl record renderer with album art and metadata.

Renders a realistic vinyl record using QPainter graphics primitives:
  - Dark record surface with radial gradient
  - Concentric groove lines
  - Circular album art label in the center
  - Center spindle dot
  - Subtle specular highlight
  - Soft drop shadow
  - Song title and artist text below the record
  - Smooth album art crossfade on track changes
"""

import math
from typing import Optional, Tuple
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QRadialGradient, QLinearGradient, QConicalGradient,
    QBrush, QPen, QPainterPath, QPixmap, QFont, QFontMetrics, QImage
)

from lyrune.wallpaper.model import WallpaperConfig, MediaSnapshot


class VinylRenderer:
    """
    Procedurally renders a vinyl record with album artwork and metadata text.

    All rendering is done via QPainter — no external assets required.
    The renderer is stateless; call render() with current state each frame.
    Album art crossfade is managed via opacity interpolation.
    """

    def __init__(self):
        # Crossfade state
        self._current_art: Optional[QPixmap] = None
        self._previous_art: Optional[QPixmap] = None
        self._crossfade_progress: float = 1.0  # 0.0 = showing old art, 1.0 = showing new art
        self._crossfade_duration: float = 0.5  # seconds

        # Cached circular album art masks
        self._art_cache: dict = {}

    def set_album_art(self, new_art: Optional[QPixmap]) -> None:
        """
        Updates the album art with crossfade transition.
        Call this when track identity changes.
        """
        if new_art is self._current_art:
            return

        # Start crossfade: current becomes previous
        if self._current_art is not None:
            self._previous_art = self._current_art
            self._crossfade_progress = 0.0
        else:
            self._previous_art = None
            self._crossfade_progress = 1.0

        self._current_art = new_art

    def advance_crossfade(self, dt: float) -> None:
        """Advances the crossfade animation by dt seconds."""
        if self._crossfade_progress < 1.0:
            self._crossfade_progress = min(
                1.0,
                self._crossfade_progress + dt / self._crossfade_duration
            )

    @property
    def is_crossfading(self) -> bool:
        return self._crossfade_progress < 1.0

    def render(self, painter: QPainter, center_x: float, center_y: float,
               diameter: float, angle: float, opacity: int,
               config: WallpaperConfig, media: MediaSnapshot) -> None:
        """
        Renders the complete vinyl record with metadata text.

        Args:
            painter: Active QPainter (already begun on the target surface).
            center_x: Center X in pixel coordinates.
            center_y: Center Y in pixel coordinates.
            diameter: Record diameter in pixels.
            angle: Current rotation angle in degrees.
            opacity: Overall opacity (0-100).
            config: Wallpaper configuration.
            media: Current media snapshot (title, artist, album art).
        """
        if diameter < 20:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Apply overall opacity
        alpha = max(0, min(255, int(opacity * 2.55)))
        painter.setOpacity(alpha / 255.0)

        radius = diameter / 2.0
        label_radius = radius * 0.38  # Album art label is ~38% of record radius

        # === Drop Shadow ===
        self._draw_shadow(painter, center_x, center_y, radius)

        # === Rotate around center ===
        painter.translate(center_x, center_y)
        painter.rotate(angle)

        # === Record Surface ===
        self._draw_record_surface(painter, radius)

        # === Grooves ===
        self._draw_grooves(painter, radius, label_radius)

        # === Album Art Label ===
        self._draw_album_art_label(painter, label_radius, media)

        # === Center Spindle ===
        self._draw_spindle(painter)

        # === Specular Highlight ===
        self._draw_highlight(painter, radius)

        # Un-rotate for text (text should not rotate)
        painter.rotate(-angle)

        # === Song Metadata Text (below the record) ===
        if config.show_title or config.show_artist:
            self._draw_metadata(painter, radius, config, media)

        painter.translate(-center_x, -center_y)
        painter.restore()

    def _draw_shadow(self, painter: QPainter, cx: float, cy: float,
                     radius: float) -> None:
        """Draws a soft drop shadow beneath the record."""
        shadow_offset = radius * 0.03
        shadow_radius = radius * 1.04

        gradient = QRadialGradient(
            QPointF(cx + shadow_offset, cy + shadow_offset * 2),
            shadow_radius
        )
        gradient.setColorAt(0.0, QColor(0, 0, 0, 60))
        gradient.setColorAt(0.7, QColor(0, 0, 0, 25))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(
            QPointF(cx + shadow_offset, cy + shadow_offset * 2),
            shadow_radius, shadow_radius
        )

    def _draw_record_surface(self, painter: QPainter, radius: float) -> None:
        """Draws the dark vinyl record surface with a subtle radial gradient."""
        gradient = QRadialGradient(QPointF(0, 0), radius)
        gradient.setColorAt(0.0, QColor(35, 35, 40))
        gradient.setColorAt(0.35, QColor(25, 25, 30))
        gradient.setColorAt(0.85, QColor(18, 18, 22))
        gradient.setColorAt(1.0, QColor(12, 12, 15))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QPointF(0, 0), radius, radius)

        # Subtle edge ring
        edge_pen = QPen(QColor(50, 50, 55, 80), 1.5)
        painter.setPen(edge_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), radius - 1, radius - 1)

    def _draw_grooves(self, painter: QPainter, radius: float,
                      label_radius: float) -> None:
        """Draws concentric groove rings on the record surface."""
        groove_start = label_radius + radius * 0.05
        groove_end = radius * 0.92
        groove_count = int((groove_end - groove_start) / (radius * 0.018))
        groove_count = max(8, min(groove_count, 50))

        groove_pen = QPen(QColor(255, 255, 255, 8), 0.5)
        painter.setPen(groove_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for i in range(groove_count):
            t = i / max(1, groove_count - 1)
            r = groove_start + t * (groove_end - groove_start)
            painter.drawEllipse(QPointF(0, 0), r, r)

    def _draw_album_art_label(self, painter: QPainter, label_radius: float,
                               media: MediaSnapshot) -> None:
        """Draws the circular album art label in the center of the record."""
        # Label background (matte finish)
        label_bg = QRadialGradient(QPointF(0, 0), label_radius)
        label_bg.setColorAt(0.0, QColor(50, 50, 55))
        label_bg.setColorAt(1.0, QColor(40, 40, 45))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(label_bg))
        painter.drawEllipse(QPointF(0, 0), label_radius, label_radius)

        # Draw album art (clipped to circle)
        art_to_draw = self._current_art if self._current_art else None
        old_art = self._previous_art if self.is_crossfading else None

        if old_art or art_to_draw:
            # Create circular clip path
            clip_path = QPainterPath()
            clip_path.addEllipse(QPointF(0, 0), label_radius - 2, label_radius - 2)

            painter.save()
            painter.setClipPath(clip_path)

            art_rect = QRectF(
                -label_radius + 2, -label_radius + 2,
                (label_radius - 2) * 2, (label_radius - 2) * 2
            )

            # Draw previous art (fading out)
            if old_art and self.is_crossfading:
                painter.setOpacity(painter.opacity() * (1.0 - self._crossfade_progress))
                painter.drawPixmap(art_rect.toRect(), old_art)
                painter.setOpacity(painter.opacity() / max(0.01, 1.0 - self._crossfade_progress))

            # Draw current art (fading in)
            if art_to_draw:
                if self.is_crossfading:
                    painter.setOpacity(painter.opacity() * self._crossfade_progress)
                painter.drawPixmap(art_rect.toRect(), art_to_draw)
                if self.is_crossfading:
                    painter.setOpacity(painter.opacity() / max(0.01, self._crossfade_progress))

            painter.restore()
        else:
            # No album art — draw placeholder
            self._draw_art_placeholder(painter, label_radius, media)

        # Label border ring
        border_pen = QPen(QColor(70, 70, 75, 120), 1.0)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), label_radius, label_radius)

    def _draw_art_placeholder(self, painter: QPainter, label_radius: float,
                               media: MediaSnapshot) -> None:
        """Draws a placeholder label when no album art is available."""
        # Music note icon as placeholder
        font = QFont("Segoe UI", int(label_radius * 0.4))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(120, 120, 130)))
        painter.drawText(
            QRectF(-label_radius, -label_radius * 0.6, label_radius * 2, label_radius * 1.2),
            Qt.AlignmentFlag.AlignCenter,
            "♫"
        )

        # Show title snippet if available
        if media.title:
            small_font = QFont("Segoe UI", max(6, int(label_radius * 0.12)))
            painter.setFont(small_font)
            painter.setPen(QPen(QColor(100, 100, 110)))
            text = media.title[:20]
            painter.drawText(
                QRectF(-label_radius * 0.8, label_radius * 0.15,
                       label_radius * 1.6, label_radius * 0.4),
                Qt.AlignmentFlag.AlignCenter,
                text
            )

    def _draw_spindle(self, painter: QPainter) -> None:
        """Draws the center spindle hole/dot."""
        # Spindle hole
        painter.setPen(Qt.PenStyle.NoPen)
        spindle_gradient = QRadialGradient(QPointF(0, 0), 6)
        spindle_gradient.setColorAt(0.0, QColor(15, 15, 18))
        spindle_gradient.setColorAt(0.6, QColor(25, 25, 30))
        spindle_gradient.setColorAt(1.0, QColor(40, 40, 45))
        painter.setBrush(QBrush(spindle_gradient))
        painter.drawEllipse(QPointF(0, 0), 5, 5)

        # Spindle ring
        ring_pen = QPen(QColor(80, 80, 85, 150), 1.0)
        painter.setPen(ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), 5, 5)

    def _draw_highlight(self, painter: QPainter, radius: float) -> None:
        """Draws a subtle specular highlight on the record surface."""
        highlight_cx = -radius * 0.25
        highlight_cy = -radius * 0.3
        highlight_radius = radius * 0.6

        gradient = QRadialGradient(
            QPointF(highlight_cx, highlight_cy),
            highlight_radius
        )
        gradient.setColorAt(0.0, QColor(255, 255, 255, 12))
        gradient.setColorAt(0.4, QColor(255, 255, 255, 5))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))

        # Clip to record circle
        clip = QPainterPath()
        clip.addEllipse(QPointF(0, 0), radius, radius)
        painter.save()
        painter.setClipPath(clip)
        painter.drawEllipse(
            QPointF(highlight_cx, highlight_cy),
            highlight_radius, highlight_radius
        )
        painter.restore()

    def _draw_metadata(self, painter: QPainter, radius: float,
                       config: WallpaperConfig, media: MediaSnapshot) -> None:
        """Draws song title and artist text below the vinyl record."""
        if not media.has_track:
            return

        text_y_start = radius + radius * 0.12
        max_text_width = radius * 2.0

        # Title
        if config.show_title and media.title:
            title_font_size = max(10, int(radius * 0.09))
            title_font = QFont("Segoe UI", title_font_size)
            title_font.setBold(True)
            painter.setFont(title_font)

            # Truncate if needed
            fm = QFontMetrics(title_font)
            title_text = fm.elidedText(media.title, Qt.TextElideMode.ElideRight,
                                       int(max_text_width))

            painter.setPen(QPen(QColor(255, 255, 255, 220)))
            title_rect = QRectF(-max_text_width / 2, text_y_start,
                               max_text_width, title_font_size * 1.6)
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                           title_text)

            text_y_start += title_font_size * 1.5

        # Artist
        if config.show_artist and media.artist:
            artist_font_size = max(8, int(radius * 0.07))
            artist_font = QFont("Segoe UI", artist_font_size)
            painter.setFont(artist_font)

            fm = QFontMetrics(artist_font)
            artist_text = fm.elidedText(media.artist, Qt.TextElideMode.ElideRight,
                                        int(max_text_width))

            painter.setPen(QPen(QColor(255, 255, 255, 140)))
            artist_rect = QRectF(-max_text_width / 2, text_y_start,
                                max_text_width, artist_font_size * 1.6)
            painter.drawText(artist_rect,
                           Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                           artist_text)
