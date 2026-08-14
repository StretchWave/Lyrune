"""
bar_visualizer.py — Minimal rounded vertical-bar visualizer implementation for Lyrune.

Aesthetic & Customization Features:
  - Multi-shape support: Pill (100% rounded), Rounded Bar (custom radius), and Square Bar (crisp rectangles).
  - Dynamic vs Exact Bar Count: Automatic length-filling density or custom user-defined count.
  - Multi-stop Linear Gradients: Rich color transitions with orientation-aware direction mapping.
  - Separate transient attack (fast punch) and exponential release (smooth drop) physics.
  - Per-bar transient peak preservation.
  - Multi-orientation support (BOTTOM, TOP, LEFT, RIGHT, FREE).
"""

from typing import List, Dict, Any
from PyQt6.QtCore import QRect, QRectF, QPointF, Qt
from PyQt6.QtGui import QPainter, QColor, QBrush, QLinearGradient

from lyrune.visualizer.base import BaseVisualizer, AudioData


class BarVisualizer(BaseVisualizer):
    """
    High-fidelity customizable bar visualizer renderer.
    """

    def __init__(self):
        self._orientation: str = "BOTTOM"  # "BOTTOM", "TOP", "LEFT", "RIGHT"
        self._width: int = 320
        self._height: int = 64

        # Shape & Sizing
        self._shape: str = "Pill"  # "Pill", "Rounded Bar", "Square Bar"
        self._corner_radius: int = 4
        self._bar_width: int = 4
        self._bar_spacing: int = 3
        self._auto_bar_count: bool = True
        self._manual_bar_count: int = 32
        self._max_height_ratio: float = 1.0

        # Colors & Gradients
        self._color_mode: str = "Solid"  # "Solid", "Gradient", "Active Lyric Color"
        self._color: QColor = QColor("#FFFFFF")
        self._gradient_stops: List[Dict[str, Any]] = [
            {"pos": 0.0, "color": "#FF4D8D"},
            {"pos": 0.5, "color": "#8B5CF6"},
            {"pos": 1.0, "color": "#3B82F6"}
        ]
        self._gradient_direction: str = "Follow Visualizer"  # "Follow Visualizer", "Fixed Horizontal", "Fixed Vertical", "Reverse"
        self._opacity: float = 1.0

        # Dynamics
        self._sensitivity: float = 1.0
        self._smoothing: float = 0.75

        # Bar state arrays
        self._bar_count: int = 32
        self._current_heights: List[float] = [0.0] * 32
        self._target_heights: List[float] = [0.0] * 32
        self._peak_heights: List[float] = [0.0] * 32

        self._media_status: str = "Paused"
        self._media_is_running: bool = False

        self._recalculate_bar_count()

    def set_orientation(self, orientation: str) -> None:
        """Sets edge orientation ('BOTTOM', 'TOP', 'LEFT', 'RIGHT')."""
        self._orientation = orientation.upper()
        self._recalculate_bar_count()

    def resize(self, width: int, height: int) -> None:
        """Notifies renderer of window geometry change."""
        self._width = max(20, width)
        self._height = max(20, height)
        self._recalculate_bar_count()

    def get_bar_count(self) -> int:
        return self._bar_count

    def _recalculate_bar_count(self) -> None:
        """
        Calculates bar count based on automatic density calculation or manual override.
        """
        step = max(2, self._bar_width + self._bar_spacing)

        if self._auto_bar_count:
            if self._orientation in ("BOTTOM", "TOP"):
                available_len = self._width
            else:  # LEFT, RIGHT
                available_len = self._height
            count = max(4, int(available_len / step))
        else:
            count = max(4, min(128, self._manual_bar_count))

        if count != self._bar_count:
            self._bar_count = count
            old_len = len(self._current_heights)
            if count > old_len:
                self._current_heights.extend([0.0] * (count - old_len))
                self._target_heights.extend([0.0] * (count - old_len))
                self._peak_heights.extend([0.0] * (count - old_len))
            else:
                self._current_heights = self._current_heights[:count]
                self._target_heights = self._target_heights[:count]
                self._peak_heights = self._peak_heights[:count]

    def set_style(self, s: Dict[str, Any]) -> None:
        """Updates rendering parameters from settings dictionary."""
        self._shape = s.get("visualizer_shape", "Pill")
        self._corner_radius = max(0, min(30, s.get("visualizer_corner_radius", 4)))
        self._bar_width = max(1, min(30, s.get("visualizer_bar_width", 4)))
        self._bar_spacing = max(0, min(20, s.get("visualizer_bar_spacing", 3)))
        self._auto_bar_count = s.get("visualizer_auto_bar_count", True)
        self._manual_bar_count = max(4, min(128, s.get("visualizer_bar_count", 32)))
        self._opacity = max(0.1, min(1.0, s.get("visualizer_opacity", 100) / 100.0))

        color_hex = s.get("visualizer_color", "#FFFFFF")
        self._color_mode = s.get("visualizer_color_mode", "Solid")
        if self._color_mode == "Active Lyric Color":
            color_hex = s.get("text_color", "#FFFFFF")
        self._color = QColor(color_hex)

        stops = s.get("visualizer_gradient_stops")
        if isinstance(stops, list) and len(stops) >= 2:
            self._gradient_stops = stops
        self._gradient_direction = s.get("visualizer_gradient_direction", "Follow Visualizer")

        self._max_height_ratio = max(0.2, min(1.0, s.get("visualizer_max_height", 100) / 100.0))
        self._sensitivity = max(0.1, min(2.0, s.get("visualizer_sensitivity", 100) / 100.0))
        self._smoothing = max(0.1, min(0.95, s.get("visualizer_smoothing", 75) / 100.0))

        self._recalculate_bar_count()

    def update_audio(self, audio_data: AudioData) -> None:
        """Maps incoming real-time FFT frequency bands to target bar heights."""
        if not audio_data or not audio_data.amplitudes:
            return

        raw_amps = audio_data.amplitudes
        raw_count = len(raw_amps)

        if raw_count == self._bar_count:
            for i in range(self._bar_count):
                self._target_heights[i] = min(1.0, raw_amps[i] * self._sensitivity)
        else:
            # Resample across frequency bands using smooth linear interpolation
            for i in range(self._bar_count):
                norm_idx = (i / float(max(1, self._bar_count - 1))) * (raw_count - 1)
                idx_low = int(norm_idx)
                idx_high = min(raw_count - 1, idx_low + 1)
                frac = norm_idx - idx_low

                val = raw_amps[idx_low] * (1.0 - frac) + raw_amps[idx_high] * frac
                self._target_heights[i] = min(1.0, val * self._sensitivity)

    def update_media_state(self, status: str, is_running: bool, track_id: str) -> None:
        """Handles song play/pause/stop lifecycle changes."""
        self._media_status = status
        self._media_is_running = is_running

        if status != "Playing" or not is_running:
            for i in range(self._bar_count):
                self._target_heights[i] = 0.0

    def reset(self) -> None:
        """Immediately resets all bar heights to zero."""
        for i in range(len(self._current_heights)):
            self._current_heights[i] = 0.0
            self._target_heights[i] = 0.0
            self._peak_heights[i] = 0.0

    def _update_physics(self) -> None:
        """Calculates separate transient attack and exponential release physics."""
        attack_rate = 0.70
        decay_rate = max(0.08, (1.0 - self._smoothing) * 0.45)

        for i in range(self._bar_count):
            target = self._target_heights[i]
            curr = self._current_heights[i]

            if target > curr:
                self._current_heights[i] = curr + (target - curr) * attack_rate
            else:
                self._current_heights[i] = max(0.0, curr - (curr - target) * decay_rate)

            if self._current_heights[i] > self._peak_heights[i]:
                self._peak_heights[i] = self._current_heights[i]
            else:
                self._peak_heights[i] = max(0.0, self._peak_heights[i] - 0.03)

    def _create_brush(self, rect: QRect) -> QBrush:
        """Builds solid or multi-stop linear gradient brush for the current frame."""
        alpha = int(self._opacity * 255)

        if self._color_mode in ("Solid", "Active Lyric Color"):
            col = QColor(self._color.red(), self._color.green(), self._color.blue(), alpha)
            return QBrush(col)

        # Multi-stop linear gradient
        dir_mode = self._gradient_direction

        if dir_mode == "Follow Visualizer":
            if self._orientation in ("BOTTOM", "TOP"):
                start_p = QPointF(rect.left(), rect.top())
                end_p = QPointF(rect.right(), rect.top())
            else:  # LEFT, RIGHT
                start_p = QPointF(rect.left(), rect.bottom())
                end_p = QPointF(rect.left(), rect.top())
        elif dir_mode == "Reverse":
            if self._orientation in ("BOTTOM", "TOP"):
                start_p = QPointF(rect.right(), rect.top())
                end_p = QPointF(rect.left(), rect.top())
            else:
                start_p = QPointF(rect.left(), rect.top())
                end_p = QPointF(rect.left(), rect.bottom())
        elif dir_mode == "Fixed Vertical":
            start_p = QPointF(rect.left(), rect.bottom())
            end_p = QPointF(rect.left(), rect.top())
        else:  # Fixed Horizontal
            start_p = QPointF(rect.left(), rect.top())
            end_p = QPointF(rect.right(), rect.top())

        grad = QLinearGradient(start_p, end_p)
        for s in self._gradient_stops:
            pos = max(0.0, min(1.0, float(s.get("pos", 0.0))))
            c = QColor(s.get("color", "#FFFFFF"))
            c.setAlpha(alpha)
            grad.setColorAt(pos, c)

        return QBrush(grad)

    def paint(self, painter: QPainter, rect: QRect) -> None:
        """Draws visualizer bars according to orientation, shape, and gradient settings."""
        self._update_physics()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        brush = self._create_brush(rect)
        painter.setBrush(brush)
        painter.setPen(Qt.PenStyle.NoPen)

        step = self._bar_width + self._bar_spacing

        # Determine corner radius
        if self._shape == "Pill":
            rx = self._bar_width / 2.0
            ry = self._bar_width / 2.0
        elif self._shape == "Rounded Bar":
            r_val = min(float(self._corner_radius), self._bar_width / 2.0)
            rx = r_val
            ry = r_val
        else:  # Square Bar
            rx = 0.0
            ry = 0.0

        if self._orientation in ("BOTTOM", "TOP"):
            max_bar_h = rect.height() * self._max_height_ratio
            total_bars_width = self._bar_count * step - self._bar_spacing
            start_x = rect.left() + (rect.width() - total_bars_width) / 2.0

            for i in range(self._bar_count):
                bar_x = start_x + i * step
                min_h = self._bar_width if self._shape == "Pill" else 2
                bar_h = max(min_h, self._current_heights[i] * max_bar_h)

                if self._orientation == "BOTTOM":
                    bar_y = rect.bottom() - bar_h + 1
                else:  # TOP
                    bar_y = rect.top()

                painter.drawRoundedRect(QRectF(bar_x, bar_y, self._bar_width, bar_h), rx, ry)

        else:  # LEFT, RIGHT
            max_bar_w = rect.width() * self._max_height_ratio
            total_bars_height = self._bar_count * step - self._bar_spacing
            start_y = rect.top() + (rect.height() - total_bars_height) / 2.0

            for i in range(self._bar_count):
                bar_y = start_y + i * step
                min_w = self._bar_width if self._shape == "Pill" else 2
                bar_w = max(min_w, self._current_heights[i] * max_bar_w)

                if self._orientation == "LEFT":
                    bar_x = rect.left()
                else:  # RIGHT
                    bar_x = rect.right() - bar_w + 1

                painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, self._bar_width), rx, ry)

        painter.restore()
