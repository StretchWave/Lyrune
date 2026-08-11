"""
animation_engine.py — LyricsRenderer: Spotify-style scrolling lyrics widget.

Replaces the previous AnimatedLyricLabel + AnimationEngine approach that caused
cascading QPainter "Painter not active" errors from nested QGraphicsOpacityEffects.

All text rendering is done in paintEvent using QPainter directly:
  - Active line: full opacity, bold weight
  - Context lines: smoothly fading opacity with distance
  - Scroll animation: QPropertyAnimation on a scroll-y offset
  - Track change: fade out → swap → fade in
  - Auto-sizes height based on visible line count and word wrap
"""

from typing import List, Optional, Tuple

from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve,
    QTimer, pyqtProperty, pyqtSignal, QRect, QRectF, QSize
)
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import (
    QPainter, QFont, QFontMetrics, QColor
)


class LyricsRenderer(QWidget):
    """
    Custom-painted lyrics display widget with Spotify-style vertical scrolling.

    All rendering is via QPainter — zero QGraphicsEffect instances — which
    eliminates the "Painter not active" conflicts that occur when multiple
    QGraphicsOpacityEffects compete on nested widget hierarchies.

    The active line is drawn at full opacity with bold weight; context lines
    fade smoothly with distance.  When the active line changes, a
    QPropertyAnimation smoothly scrolls the view to center it.

    Public API:
      set_lines(lines)       — set all lyric texts (once per song)
      set_active_index(idx)  — scroll to the given line (called every 50ms)
      set_status(msg)        — show a status message instead of lyrics
      fade_out_then(cb)      — fade out, call cb, then fade in
      update_style(settings) — apply visual settings
      stop_all()             — stop animations (app exit)
    """

    ideal_height_changed = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumHeight(50)

        # ── Content ──
        self._lines: List[str] = []
        self._status_message: str = "Waiting for music..."
        self._active_index: int = -1
        self._context_lines: int = 3

        # Cached layout: (y_offset, height) per line
        self._line_layouts: List[Tuple[float, float]] = []
        self._total_content_height: float = 0.0

        # ── Animated properties ──
        self._scroll_y: float = 0.0
        self._fade_opacity: float = 1.0

        # ── Style ──
        self._font_family: str = "Segoe UI"
        self._font_size: int = 24
        self._font_bold: bool = True
        self._text_color: QColor = QColor("#FFFFFF")
        self._text_align: int = int(Qt.AlignmentFlag.AlignHCenter)
        self._shadow_enabled: bool = True
        self._shadow_color: QColor = QColor("#000000")
        self._line_padding: int = 14
        self._margin: int = 20

        # ── Scroll animation ──
        self._scroll_anim = QPropertyAnimation(self, b"scroll_y_prop")
        self._scroll_anim.setDuration(400)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # ── Fade animation (track change) ──
        self._fade_anim = QPropertyAnimation(self, b"fade_opacity_prop")
        self._fade_anim.setDuration(250)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutQuad)

    # ─── Animatable properties ────────────────────────────────────────

    def _get_scroll_y(self) -> float:
        return self._scroll_y

    def _set_scroll_y(self, value: float) -> None:
        self._scroll_y = value
        self.update()

    scroll_y_prop = pyqtProperty(float, fget=_get_scroll_y, fset=_set_scroll_y)

    def _get_fade_opacity(self) -> float:
        return self._fade_opacity

    def _set_fade_opacity(self, value: float) -> None:
        self._fade_opacity = max(0.0, min(1.0, value))
        self.update()

    fade_opacity_prop = pyqtProperty(float, fget=_get_fade_opacity, fset=_set_fade_opacity)

    # ─── Public API ───────────────────────────────────────────────────

    def set_lines(self, lines: List[str]) -> None:
        """Set all lyric lines.  Called once when lyrics are fetched for a new song."""
        self._lines = lines
        self._status_message = ""
        self._active_index = -1
        self._scroll_y = 0.0
        self._fade_opacity = 1.0
        self._recalculate_layout()
        self.update()

    def set_status(self, message: str) -> None:
        """Show a centered status message (e.g. 'Waiting for music…')."""
        self._lines = []
        self._line_layouts = []
        self._status_message = message
        self._active_index = -1
        self._total_content_height = 0.0
        self.update()

    def set_active_index(self, index: int) -> None:
        """Smoothly scroll to centre the line at *index*."""
        if index == self._active_index or not self._lines:
            return
        if index < 0 or index >= len(self._lines):
            return
        self._active_index = index
        self._scroll_to_active()

    def fade_out_then(self, callback) -> None:
        """Fade out → call *callback* → fade in.  Used for track changes."""
        self._fade_anim.stop()
        try:
            self._fade_anim.finished.disconnect()
        except TypeError:
            pass

        self._fade_anim.setStartValue(self._fade_opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setDuration(200)

        def _on_faded_out():
            try:
                self._fade_anim.finished.disconnect(_on_faded_out)
            except TypeError:
                pass
            callback()
            # Fade back in
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.setDuration(350)
            self._fade_anim.start()

        self._fade_anim.finished.connect(_on_faded_out)
        self._fade_anim.start()

    def update_style(self, settings: dict) -> None:
        """Refresh visual style from settings dict."""
        need_relayout = False

        new_family = settings.get("font_family", self._font_family)
        new_size = settings.get("font_size", self._font_size)
        new_bold = settings.get("font_bold", self._font_bold)
        new_ctx = settings.get("context_lines", self._context_lines)

        if (new_family != self._font_family or new_size != self._font_size
                or new_bold != self._font_bold or new_ctx != self._context_lines):
            need_relayout = True

        self._font_family = new_family
        self._font_size = new_size
        self._font_bold = new_bold
        self._text_color = QColor(settings.get("text_color", "#FFFFFF"))
        self._shadow_enabled = settings.get("shadow_enabled", True)
        self._shadow_color = QColor(settings.get("shadow_color", "#000000"))
        self._context_lines = new_ctx

        align_str = settings.get("text_align", "Center")
        if align_str == "Left":
            self._text_align = int(Qt.AlignmentFlag.AlignLeft)
        elif align_str == "Right":
            self._text_align = int(Qt.AlignmentFlag.AlignRight)
        else:
            self._text_align = int(Qt.AlignmentFlag.AlignHCenter)

        speed = settings.get("animation_speed_ms", 400)
        self._scroll_anim.setDuration(speed)

        if need_relayout:
            self._recalculate_layout()
            if self._active_index >= 0:
                self._scroll_to_active_immediate()

        self.update()

    def stop_all(self) -> None:
        """Stop all running animations.  Call on app exit."""
        self._scroll_anim.stop()
        self._fade_anim.stop()

    # ─── Layout calculation ───────────────────────────────────────────

    def _get_font(self, bold: bool = False) -> QFont:
        weight = QFont.Weight.Bold if (self._font_bold and bold) else QFont.Weight.Normal
        return QFont(self._font_family, self._font_size, weight)

    def _recalculate_layout(self) -> None:
        """Pre-measure all lines for word-wrapped layout (variable heights)."""
        self._line_layouts = []
        if not self._lines:
            self._total_content_height = 0.0
            self._emit_ideal_height()
            return

        font = self._get_font(bold=True)          # measure with bold (worst-case width)
        fm = QFontMetrics(font)
        avail_width = max(100, self.width() - 2 * self._margin)

        y = 0.0
        for text in self._lines:
            if text.strip() == "♪":
                h = fm.height() * 0.7 + self._line_padding
            else:
                rect = fm.boundingRect(
                    QRect(0, 0, avail_width, 100000),
                    int(Qt.TextFlag.TextWordWrap),
                    text,
                )
                h = rect.height() + self._line_padding
            self._line_layouts.append((y, h))
            y += h

        self._total_content_height = y
        self._emit_ideal_height()

    def _emit_ideal_height(self) -> None:
        """Calculate and signal the ideal widget height to the parent."""
        if not self._line_layouts:
            self.ideal_height_changed.emit(80)
            return

        visible_count = min(len(self._lines), 2 * self._context_lines + 1)
        avg_h = self._total_content_height / max(1, len(self._line_layouts))
        ideal = int(avg_h * visible_count) + 30
        self.ideal_height_changed.emit(max(80, ideal))

    # ─── Scroll ───────────────────────────────────────────────────────

    def _scroll_to_active(self) -> None:
        """Animate scroll so the active line is centred vertically."""
        if self._active_index < 0 or self._active_index >= len(self._line_layouts):
            return

        y, h = self._line_layouts[self._active_index]
        target = y + h / 2 - self.height() / 2

        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(self._scroll_y)
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.start()

    def _scroll_to_active_immediate(self) -> None:
        """Jump to the active line without animation (used after resize/settings)."""
        if self._active_index < 0 or self._active_index >= len(self._line_layouts):
            return
        y, h = self._line_layouts[self._active_index]
        self._scroll_y = y + h / 2 - self.height() / 2

    # ─── Events ───────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._recalculate_layout()
        if self._active_index >= 0:
            self._scroll_to_active_immediate()

    # ─── Painting ─────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:        # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        if self._fade_opacity < 0.01:
            painter.end()
            return

        w = self.width()
        h = self.height()
        margin = self._margin
        avail = w - 2 * margin

        # ── Status-message mode (no lyrics loaded) ──
        if not self._lines:
            font = self._get_font(bold=True)
            painter.setFont(font)
            painter.setOpacity(0.55 * self._fade_opacity)
            painter.setPen(self._text_color)
            flags = (self._text_align
                     | int(Qt.AlignmentFlag.AlignVCenter)
                     | int(Qt.TextFlag.TextWordWrap))
            painter.drawText(QRectF(margin, 0, avail, h), flags,
                             self._status_message or "")
            painter.end()
            return

        # ── Lyrics rendering ──
        for i, text in enumerate(self._lines):
            if i >= len(self._line_layouts):
                break

            y_pos, line_h = self._line_layouts[i]
            screen_y = y_pos - self._scroll_y

            # Cull lines well outside the visible area
            if screen_y + line_h < -50 or screen_y > h + 50:
                continue

            # ── Opacity based on index distance from active ──
            is_active = (i == self._active_index)

            if is_active:
                opacity = 1.0
            elif self._active_index < 0:
                opacity = 0.40
            else:
                idx_dist = abs(i - self._active_index)
                if idx_dist <= self._context_lines:
                    # Smooth exponential falloff
                    opacity = max(0.10, 0.50 * (0.58 ** (idx_dist - 1)))
                else:
                    continue  # outside context window — skip entirely

            opacity *= self._fade_opacity
            if opacity < 0.01:
                continue

            # ── Font ──
            font = self._get_font(bold=is_active)
            painter.setFont(font)

            text_rect = QRectF(margin, screen_y, avail, line_h)
            flags = (self._text_align
                     | int(Qt.AlignmentFlag.AlignTop)
                     | int(Qt.TextFlag.TextWordWrap))

            # ── Shadow (active line only) ──
            if is_active and self._shadow_enabled:
                painter.setOpacity(opacity * 0.45)
                painter.setPen(self._shadow_color)
                for dx, dy in ((1, 1), (2, 2), (0, 2), (2, 0)):
                    painter.drawText(text_rect.adjusted(dx, dy, 0, 0),
                                     flags, text)

            # ── Main text ──
            painter.setOpacity(opacity)
            painter.setPen(self._text_color)
            painter.drawText(text_rect, flags, text)

        painter.end()
