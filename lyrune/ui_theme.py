"""
ui_theme.py — Modern Translucent Cinematic Glass Design System for Lyrune.

Implements spatial translucent glass tokens, atmospheric nebula background rendering,
and custom glass widgets matching the visual design reference.
"""

import math
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from PyQt6.QtCore import Qt, QRect, QRectF, QPointF, pyqtSignal, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QPixmap, QPainter, QBrush, QPen,
    QLinearGradient, QRadialGradient, QPainterPath, QCursor, QMouseEvent, QKeySequence, QFontMetrics
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QPushButton, QLabel, QSlider, QHBoxLayout,
    QVBoxLayout, QGraphicsDropShadowEffect, QSizePolicy, QLineEdit, QColorDialog,
    QStackedWidget, QGraphicsOpacityEffect
)


# ==============================================================================
# Design System Tokens
# ==============================================================================

@dataclass(frozen=True)
class GlassPalette:
    # Translucent Backgrounds & Surfaces (~20-30% visual translucency)
    shell_bg: str = "rgba(15, 18, 25, 0.78)"
    glass_card: str = "rgba(24, 28, 38, 0.68)"
    glass_card_elevated: str = "rgba(30, 35, 46, 0.58)"
    glass_hover: str = "rgba(255, 255, 255, 0.055)"
    glass_pressed: str = "rgba(255, 255, 255, 0.08)"
    glass_active: str = "rgba(46, 213, 115, 0.12)"

    # Borders & Specular Highlights
    border_subtle: str = "rgba(255, 255, 255, 0.09)"
    border_card: str = "rgba(255, 255, 255, 0.09)"
    border_strong: str = "rgba(255, 255, 255, 0.14)"
    highlight_top: str = "rgba(255, 255, 255, 0.035)"

    # Vibrant Brand & Status Accents
    accent_green: str = "#2ED573"
    accent_spotify: str = "#1DB954"
    accent_cyan: str = "#00D2D3"
    accent_purple: str = "#9B51E0"
    accent_pink: str = "#FF4757"
    accent_blue: str = "#38BDF8"

    # Typography
    text_primary: str = "#FFFFFF"
    text_secondary: str = "#C5C8D4"
    text_muted: str = "#8A8D9B"
    text_disabled: str = "#525666"


PALETTE = GlassPalette()

DARK_THEME_STYLESHEET = """
QWidget {
    color: #F0F1F5;
    font-family: 'Segoe UI', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 13px;
    background: transparent;
    selection-background-color: #2ED573;
    selection-color: #0A0D14;
}

QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 4px 2px 4px 0;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.18);
    min-height: 24px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 0.35);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}

QComboBox {
    background: rgba(24, 28, 38, 0.68);
    color: #F0F1F5;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    min-height: 20px;
}
QComboBox:hover {
    border-color: rgba(255, 255, 255, 0.18);
    background: rgba(30, 35, 46, 0.78);
}
QComboBox::drop-down {
    border: none;
    width: 20px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
}
QComboBox QAbstractItemView {
    background: #141724;
    color: #F0F1F5;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 4px;
    selection-background-color: rgba(46, 213, 115, 0.20);
    selection-color: #2ED573;
    outline: none;
}

QLineEdit {
    background: rgba(24, 28, 38, 0.68);
    color: #F0F1F5;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
}
QLineEdit:focus {
    border-color: #2ED573;
    background: rgba(30, 35, 46, 0.78);
}
"""

MENU_STYLESHEET = """
QMenu {
    background-color: rgba(18, 22, 34, 0.94);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    padding: 6px;
    color: #F0F1F5;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 12px;
}
QMenu::item {
    background: transparent;
    padding: 7px 24px 7px 12px;
    border-radius: 6px;
    margin: 1px 0;
}
QMenu::item:selected {
    background-color: rgba(46, 213, 115, 0.16);
    color: #FFFFFF;
}
QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 0.08);
    margin: 4px 6px;
}
"""


# ==============================================================================
# Atmospheric Nebula Background Renderer
# ==============================================================================

def paint_atmospheric_background(painter: QPainter, rect: QRectF, accent: Optional[QColor] = None):
    """
    Renders the rich vibrant cosmic nebula atmospheric background with true translucency.
    Allows the real desktop / Windows DWM acrylic backdrop to shine through the glass.
    """
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    w = rect.width()
    h = rect.height()

    # 1. Base translucent glass tint (~20-30% visual translucency, not solid black)
    painter.fillRect(rect, QColor(10, 13, 22, 135))

    # 2. Top-Right Vivid Magenta / Pink cosmic cloud
    grad_top_right = QRadialGradient(w * 0.78, h * 0.18, w * 0.65)
    grad_top_right.setColorAt(0.0, QColor(160, 32, 120, 110))
    grad_top_right.setColorAt(0.40, QColor(110, 25, 95, 65))
    grad_top_right.setColorAt(1.0, QColor(10, 13, 22, 0))
    painter.fillRect(rect, QBrush(grad_top_right))

    # 3. Top-Left / Center Deep Purple & Electric Indigo nebula
    grad_top_left = QRadialGradient(w * 0.28, h * 0.28, w * 0.58)
    grad_top_left.setColorAt(0.0, QColor(90, 38, 140, 100))
    grad_top_left.setColorAt(0.50, QColor(48, 22, 85, 55))
    grad_top_left.setColorAt(1.0, QColor(10, 13, 22, 0))
    painter.fillRect(rect, QBrush(grad_top_left))

    # 4. Bottom-Left / Left Oceanic Cyan & Azure streamer
    grad_bottom_left = QRadialGradient(w * 0.12, h * 0.72, w * 0.65)
    grad_bottom_left.setColorAt(0.0, QColor(0, 168, 255, 90))
    grad_bottom_left.setColorAt(0.45, QColor(18, 75, 140, 50))
    grad_bottom_left.setColorAt(1.0, QColor(10, 13, 22, 0))
    painter.fillRect(rect, QBrush(grad_bottom_left))

    # 5. Bottom-Right Subtle Violet / Midnight glow
    grad_bottom_right = QRadialGradient(w * 0.88, h * 0.82, w * 0.55)
    grad_bottom_right.setColorAt(0.0, QColor(120, 35, 135, 80))
    grad_bottom_right.setColorAt(0.50, QColor(60, 20, 80, 40))
    grad_bottom_right.setColorAt(1.0, QColor(10, 13, 22, 0))
    painter.fillRect(rect, QBrush(grad_bottom_right))

    # 6. Dynamic album accent highlight (if present)
    if accent and accent.isValid():
        grad_accent = QRadialGradient(w * 0.42, h * 0.40, w * 0.50)
        grad_accent.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 55))
        grad_accent.setColorAt(1.0, QColor(10, 13, 22, 0))
        painter.fillRect(rect, QBrush(grad_accent))


# ==============================================================================
# Palette Extraction
# ==============================================================================

def extract_dominant_accent(pixmap: Optional[QPixmap], default_accent: str = "#2ED573") -> QColor:
    """Extracts a vivid dominant color from the album artwork."""
    if not pixmap or pixmap.isNull():
        return QColor(default_accent)

    try:
        small = pixmap.scaled(32, 32, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        img = small.toImage()

        best_color = None
        best_score = -1.0

        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                h, s, v, _ = c.getHsvF()
                if v < 0.20 or v > 0.95 or s < 0.25:
                    continue
                score = s * 2.0 + v
                if score > best_score:
                    best_score = score
                    best_color = c

        if best_color:
            return best_color
        return QColor(default_accent)
    except Exception:
        return QColor(default_accent)


# ==============================================================================
# Vector Icons
# ==============================================================================

def get_icon(name: str, color: str = "#C5C8D4") -> QIcon:
    """Renders crisp vector line icons."""
    size = 24
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "overview" or name == "grid":
        painter.drawRoundedRect(QRectF(3.5, 3.5, 7, 7), 2, 2)
        painter.drawRoundedRect(QRectF(13.5, 3.5, 7, 7), 2, 2)
        painter.drawRoundedRect(QRectF(3.5, 13.5, 7, 7), 2, 2)
        painter.drawRoundedRect(QRectF(13.5, 13.5, 7, 7), 2, 2)

    elif name == "appearance" or name == "palette":
        painter.drawEllipse(QRectF(3.5, 3.5, 17, 17))
        painter.setBrush(QBrush(QColor(color)))
        painter.drawEllipse(QRectF(7, 7, 2, 2))
        painter.drawEllipse(QRectF(12, 6, 2, 2))
        painter.drawEllipse(QRectF(16, 10, 2, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    elif name == "typography" or name == "text":
        painter.drawLine(QPointF(4, 6), QPointF(20, 6))
        painter.drawLine(QPointF(12, 6), QPointF(12, 19))
        painter.drawLine(QPointF(8, 19), QPointF(16, 19))

    elif name == "wallpaper" or name == "image":
        painter.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 3, 3)
        path = QPainterPath()
        path.moveTo(4, 16)
        path.lineTo(9, 11)
        path.lineTo(13, 15)
        path.lineTo(17, 10)
        path.lineTo(20, 14)
        painter.drawPath(path)
        painter.drawEllipse(QRectF(14.5, 6.5, 2.5, 2.5))

    elif name == "visualizer" or name == "waveform":
        painter.drawLine(QPointF(4, 12), QPointF(4, 12))
        painter.drawLine(QPointF(8, 7), QPointF(8, 17))
        painter.drawLine(QPointF(12, 4), QPointF(12, 20))
        painter.drawLine(QPointF(16, 8), QPointF(16, 16))
        painter.drawLine(QPointF(20, 11), QPointF(20, 13))

    elif name == "behavior" or name == "sliders":
        painter.drawLine(QPointF(4, 7), QPointF(20, 7))
        painter.drawLine(QPointF(4, 17), QPointF(20, 17))
        painter.drawEllipse(QRectF(7, 5, 4, 4))
        painter.drawEllipse(QRectF(14, 15, 4, 4))

    elif name == "shortcuts" or name == "keyboard":
        painter.drawRoundedRect(QRectF(3.5, 6, 17, 12), 2, 2)
        painter.drawLine(QPointF(6, 10), QPointF(8, 10))
        painter.drawLine(QPointF(10, 10), QPointF(12, 10))
        painter.drawLine(QPointF(14, 10), QPointF(16, 10))
        painter.drawLine(QPointF(7, 14), QPointF(15, 14))

    elif name == "advanced" or name == "gear":
        painter.drawEllipse(QRectF(7, 7, 10, 10))
        for i in range(6):
            ang = i * (math.pi / 3)
            x1 = 12 + 6.5 * math.cos(ang)
            y1 = 12 + 6.5 * math.sin(ang)
            x2 = 12 + 9.0 * math.cos(ang)
            y2 = 12 + 9.0 * math.sin(ang)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    elif name == "spotify":
        painter.setBrush(QBrush(QColor("#1DB954")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.setPen(QPen(QColor("#0A0D14"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(6, 6, 12, 12), 30 * 16, 120 * 16)
        painter.drawArc(QRectF(7, 9, 10, 10), 30 * 16, 120 * 16)
        painter.drawArc(QRectF(8, 12, 8, 8), 30 * 16, 120 * 16)

    elif name == "chevron_right":
        path = QPainterPath()
        path.moveTo(9, 7)
        path.lineTo(15, 12)
        path.lineTo(9, 17)
        painter.drawPath(path)

    elif name == "refresh":
        painter.drawArc(QRectF(4, 4, 16, 16), 45 * 16, 270 * 16)
        path = QPainterPath()
        path.moveTo(17, 4)
        path.lineTo(20, 8)
        path.lineTo(15, 8)
        painter.drawPath(path)

    elif name == "play":
        painter.setBrush(QBrush(QColor(color)))
        path = QPainterPath()
        path.moveTo(8, 6)
        path.lineTo(18, 12)
        path.lineTo(8, 18)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "pause":
        painter.setBrush(QBrush(QColor(color)))
        painter.drawRoundedRect(QRectF(7, 6, 3.5, 12), 1, 1)
        painter.drawRoundedRect(QRectF(13.5, 6, 3.5, 12), 1, 1)

    elif name == "next":
        painter.setBrush(QBrush(QColor(color)))
        path = QPainterPath()
        path.moveTo(6, 6)
        path.lineTo(13, 12)
        path.lineTo(6, 18)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawRoundedRect(QRectF(15, 6, 2.5, 12), 1, 1)

    elif name == "prev":
        painter.setBrush(QBrush(QColor(color)))
        path = QPainterPath()
        path.moveTo(18, 6)
        path.lineTo(11, 12)
        path.lineTo(18, 18)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawRoundedRect(QRectF(6.5, 6, 2.5, 12), 1, 1)

    elif name == "moon":
        path = QPainterPath()
        path.moveTo(15, 4)
        path.cubicTo(8, 5, 6, 12, 11, 19)
        path.cubicTo(18, 20, 21, 15, 20, 13)
        path.cubicTo(16, 14, 13, 10, 15, 4)
        painter.drawPath(path)

    elif name == "minus":
        painter.drawLine(QPointF(5, 12), QPointF(19, 12))

    elif name == "maximize":
        painter.drawRoundedRect(QRectF(5, 5, 14, 14), 2, 2)

    elif name == "restore":
        painter.drawRoundedRect(QRectF(7, 4, 12, 12), 2, 2)
        painter.drawRoundedRect(QRectF(4, 7, 12, 12), 2, 2)

    elif name == "close":
        painter.drawLine(QPointF(6, 6), QPointF(18, 18))
        painter.drawLine(QPointF(18, 6), QPointF(6, 18))

    painter.end()
    return QIcon(pixmap)


def get_app_icon() -> QIcon:
    """App window icon."""
    return get_icon("visualizer", color="#2ED573")


# ==============================================================================
# GlassCard Component (LEVEL 2)
# ==============================================================================

class GlassCard(QFrame):
    """
    Translucent glass card container (~20-30% visual translucency).
    Features:
      - Primary glass: rgba(24, 28, 38, 0.68)
      - Secondary glass: rgba(30, 35, 46, 0.58)
      - Border: rgba(255, 255, 255, 0.09)
      - Specular top highlight line: rgba(255, 255, 255, 0.035)
      - Interactive hover sheen
    """
    def __init__(
        self,
        radius: int = 18,
        elevated: bool = False,
        interactive: bool = False,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._radius = radius
        self._elevated = elevated
        self._interactive = interactive
        self._is_hovered = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def enterEvent(self, event):
        if self._interactive:
            self._is_hovered = True
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._interactive:
            self._is_hovered = False
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if self._is_hovered:
            bg_color = QColor(36, 42, 58, 185)
            border_pen = QPen(QColor(255, 255, 255, 36), 1)
        elif self._elevated:
            bg_color = QColor(30, 35, 46, 148)
            border_pen = QPen(QColor(255, 255, 255, 24), 1)
        else:
            bg_color = QColor(24, 28, 38, 173)
            border_pen = QPen(QColor(255, 255, 255, 23), 1)

        painter.setBrush(QBrush(bg_color))
        painter.setPen(border_pen)
        painter.drawRoundedRect(rect, self._radius, self._radius)

        # Specular top highlight line
        highlight_pen = QPen(QColor(255, 255, 255, 12), 1)
        painter.setPen(highlight_pen)
        painter.drawLine(
            QPointF(rect.left() + self._radius, rect.top()),
            QPointF(rect.right() - self._radius, rect.top())
        )


# ==============================================================================
# BentoCard Component (2x2 Status Grid)
# ==============================================================================

class BentoCard(GlassCard):
    """
    Interactive Bento status card matching the reference image:
      - Title (13px bold)
      - Status line with green dot: '● Active' / '● Connected'
      - Subtext description with graceful eliding
      - Right circular icon badge + chevron '>'
    """
    clicked = pyqtSignal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        badge_type: str = "lyrics",
        active: bool = True,
        parent: Optional[QWidget] = None
    ):
        super().__init__(radius=16, elevated=False, interactive=True, parent=parent)
        self._title = title
        self._subtitle = subtitle
        self._badge_type = badge_type
        self._active = active
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(92)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)

        # Text column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.lbl_title = QLabel(self._title, self)
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        info_layout.addWidget(self.lbl_title)

        status_row = QHBoxLayout()
        status_row.setSpacing(5)

        self.dot = QLabel("●", self)
        self.dot.setStyleSheet("color: #2ED573; font-size: 8px;" if self._active else "color: #525666; font-size: 8px;")
        status_row.addWidget(self.dot)

        self.lbl_status_text = QLabel("Active" if self._active else "Disabled", self)
        self.lbl_status_text.setStyleSheet("font-size: 10px; font-weight: 600; color: #2ED573;" if self._active else "font-size: 10px; color: #8A8D9B;")
        status_row.addWidget(self.lbl_status_text)
        status_row.addStretch(1)
        info_layout.addLayout(status_row)

        self.lbl_sub = QLabel(self._subtitle, self)
        self.lbl_sub.setStyleSheet("font-size: 10px; color: #8A8D9B;")
        self.lbl_sub.setToolTip(self._subtitle)
        info_layout.addWidget(self.lbl_sub)

        layout.addLayout(info_layout, 1)

        # Right custom badge widget
        self.badge_btn = QPushButton(self)
        self.badge_btn.setFixedSize(36, 36)
        self.badge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_badge()
        layout.addWidget(self.badge_btn)

        lbl_chevron = QLabel(self)
        lbl_chevron.setPixmap(get_icon("chevron_right", color="#525666").pixmap(14, 14))
        layout.addWidget(lbl_chevron)

    def _update_badge(self):
        if self._badge_type == "lyrics":
            self.badge_btn.setText("A")
            self.badge_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(46, 213, 115, 0.12);
                    color: #2ED573;
                    font-weight: 700;
                    font-size: 14px;
                    border: 1px solid rgba(46, 213, 115, 0.40);
                    border-radius: 18px;
                }
            """)
        elif self._badge_type == "visualizer":
            self.badge_btn.setText("")
            self.badge_btn.setIcon(get_icon("visualizer", color="#FF4757"))
            self.badge_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 71, 87, 0.12);
                    border: 1px solid rgba(255, 71, 87, 0.35);
                    border-radius: 18px;
                }
            """)
        elif self._badge_type == "wallpaper":
            self.badge_btn.setText("")
            self.badge_btn.setIcon(get_icon("wallpaper", color="#38BDF8"))
            self.badge_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(56, 189, 248, 0.12);
                    border: 1px solid rgba(56, 189, 248, 0.35);
                    border-radius: 18px;
                }
            """)
        elif self._badge_type == "spotify":
            self.badge_btn.setText("")
            self.badge_btn.setIcon(get_icon("spotify", color="#1DB954"))
            self.badge_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(29, 185, 84, 0.15);
                    border: 1px solid rgba(29, 185, 84, 0.40);
                    border-radius: 18px;
                }
            """)

    def set_status(self, active: bool, subtitle: Optional[str] = None):
        self._active = active
        self.dot.setStyleSheet("color: #2ED573; font-size: 8px;" if self._active else "color: #525666; font-size: 8px;")
        self.lbl_status_text.setText("Active" if self._active else "Disabled")
        self.lbl_status_text.setStyleSheet("font-size: 10px; font-weight: 600; color: #2ED573;" if self._active else "font-size: 10px; color: #8A8D9B;")
        if subtitle:
            self.lbl_sub.setText(subtitle)
            self.lbl_sub.setToolTip(subtitle)
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ==============================================================================
# DynamicIslandBar Component (Title Bar Center)
# ==============================================================================

class DynamicIslandBar(GlassCard):
    """
    Floating dynamic island media controller in the title bar with progress and truncation.
    """
    playPauseClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    nextClicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(radius=16, elevated=True, interactive=True, parent=parent)
        self.setFixedHeight(36)
        self.setFixedWidth(320)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 10, 4)
        layout.setSpacing(8)

        self.lbl_art = QLabel(self)
        self.lbl_art.setFixedSize(28, 28)
        self.lbl_art.setStyleSheet("background: #141724; border-radius: 6px; border: 1px solid rgba(255,255,255,0.12);")
        self.lbl_art.setScaledContents(True)
        layout.addWidget(self.lbl_art)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(0)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.lbl_title = QLabel("Lyrune Studio", self)
        self.lbl_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #FFFFFF;")
        self.lbl_title.setMaximumWidth(150)
        info_layout.addWidget(self.lbl_title)

        self.lbl_artist = QLabel("No track playing", self)
        self.lbl_artist.setStyleSheet("font-size: 9px; color: #8A8D9B;")
        self.lbl_artist.setMaximumWidth(150)
        info_layout.addWidget(self.lbl_artist)
        layout.addLayout(info_layout, 1)

        # Mini transport controls
        self.btn_prev = QPushButton(self)
        self.btn_prev.setIcon(get_icon("prev", color="#C5C8D4"))
        self.btn_prev.setFixedSize(20, 20)
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev.setStyleSheet("background: transparent; border: none;")
        self.btn_prev.clicked.connect(self.prevClicked.emit)
        layout.addWidget(self.btn_prev)

        self.btn_play = QPushButton(self)
        self.btn_play.setIcon(get_icon("pause", color="#2ED573"))
        self.btn_play.setFixedSize(24, 24)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.setStyleSheet("""
            QPushButton {
                background: rgba(46, 213, 115, 0.15);
                border: 1px solid rgba(46, 213, 115, 0.35);
                border-radius: 12px;
            }
            QPushButton:hover {
                background: rgba(46, 213, 115, 0.25);
            }
        """)
        self.btn_play.clicked.connect(self.playPauseClicked.emit)
        layout.addWidget(self.btn_play)

        self.btn_next = QPushButton(self)
        self.btn_next.setIcon(get_icon("next", color="#C5C8D4"))
        self.btn_next.setFixedSize(20, 20)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.setStyleSheet("background: transparent; border: none;")
        self.btn_next.clicked.connect(self.nextClicked.emit)
        layout.addWidget(self.btn_next)

    def update_media(self, title: str, artist: str, pixmap: Optional[QPixmap] = None, is_playing: bool = True):
        display_title = title or "Lyrune Studio"
        display_artist = artist or "No track playing"

        # Truncate if long
        fm = QFontMetrics(self.lbl_title.font())
        elided_title = fm.elidedText(display_title, Qt.TextElideMode.ElideRight, 140)
        self.lbl_title.setText(elided_title)
        self.lbl_title.setToolTip(display_title)

        fm_a = QFontMetrics(self.lbl_artist.font())
        elided_artist = fm_a.elidedText(display_artist, Qt.TextElideMode.ElideRight, 140)
        self.lbl_artist.setText(elided_artist)
        self.lbl_artist.setToolTip(display_artist)

        if pixmap and not pixmap.isNull():
            self.lbl_art.setPixmap(pixmap.scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        self.btn_play.setIcon(get_icon("pause" if is_playing else "play", color="#2ED573"))


# ==============================================================================
# SegmentedSwitch Component (Studio Header Switcher)
# ==============================================================================

class SegmentedSwitch(GlassCard):
    """
    Segmented pill switch for Wallpaper Studio / Visualizer Studio.
    """
    switched = pyqtSignal(int)

    def __init__(self, segments: List[Tuple[str, str]], parent: Optional[QWidget] = None):
        super().__init__(radius=12, elevated=True, interactive=False, parent=parent)
        self.setFixedHeight(38)
        self._current_index = 0
        self._buttons: List[QPushButton] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)

        for i, (icon_k, label) in enumerate(segments):
            btn = QPushButton(f" {label}", self)
            btn.setIcon(get_icon(icon_k, color="#FFFFFF" if i == 0 else "#8A8D9B"))
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, idx=i: self._on_btn_clicked(idx))
            layout.addWidget(btn, 1)
            self._buttons.append(btn)

        self._update_styles()

    def _on_btn_clicked(self, index: int):
        if self._current_index != index:
            self._current_index = index
            self._update_styles()
            self.switched.emit(index)

    def _update_styles(self):
        for i, btn in enumerate(self._buttons):
            if i == self._current_index:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(48, 56, 80, 0.85);
                        color: #FFFFFF;
                        font-size: 12px;
                        font-weight: 700;
                        border: 1px solid rgba(255, 255, 255, 0.18);
                        border-radius: 8px;
                        padding: 0 12px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #8A8D9B;
                        font-size: 12px;
                        font-weight: 500;
                        border: none;
                        border-radius: 8px;
                        padding: 0 12px;
                    }
                    QPushButton:hover {
                        color: #F0F1F5;
                    }
                """)

    def index(self) -> int:
        return self._current_index

    def setIndex(self, index: int):
        if self._current_index != index and 0 <= index < len(self._buttons):
            self._current_index = index
            self._update_styles()
            self.switched.emit(index)


# ==============================================================================
# SubTabRow Component (Studio Sub-Navigation)
# ==============================================================================

class SubTabRow(QWidget):
    """
    Sub-tab navigation bar with green active underline bar.
    """
    tabSelected = pyqtSignal(int)

    def __init__(self, tabs: List[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self._tabs = tabs
        self._current_index = 0
        self._buttons: List[QPushButton] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(16)

        for i, text in enumerate(tabs):
            btn = QPushButton(text, self)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self.set_index(idx))
            layout.addWidget(btn)
            self._buttons.append(btn)

        layout.addStretch(1)
        self._update_tab_styles()

    def set_index(self, index: int):
        if self._current_index != index:
            self._current_index = index
            self._update_tab_styles()
            self.tabSelected.emit(index)

    def _update_tab_styles(self):
        for i, btn in enumerate(self._buttons):
            if i == self._current_index:
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #2ED573;
                        font-size: 11px;
                        font-weight: 700;
                        letter-spacing: 0.5px;
                        border: none;
                        border-bottom: 2px solid #2ED573;
                        padding: 6px 4px 6px 4px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #8A8D9B;
                        font-size: 11px;
                        font-weight: 600;
                        letter-spacing: 0.5px;
                        border: none;
                        border-bottom: 2px solid transparent;
                        padding: 6px 4px 6px 4px;
                    }
                    QPushButton:hover {
                        color: #F0F1F5;
                    }
                """)


# ==============================================================================
# ToggleSwitch Component
# ==============================================================================

class ToggleSwitch(QWidget):
    """Modern smooth rounded pill toggle switch."""
    toggled = pyqtSignal(bool)

    def __init__(self, label: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._checked = False
        self._label = label
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(26)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        if self._label:
            self.lbl = QLabel(self._label, self)
            self.lbl.setStyleSheet("font-size: 12px; color: #F0F1F5; font-weight: 500;")
            layout.addWidget(self.lbl)
            layout.addStretch(1)

        self.switch_pill = QWidget(self)
        self.switch_pill.setFixedSize(42, 22)
        self.switch_pill.paintEvent = self._paint_pill
        layout.addWidget(self.switch_pill)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self.switch_pill.update()
            self.toggled.emit(self._checked)

    def _paint_pill(self, event):
        painter = QPainter(self.switch_pill)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.switch_pill.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if self._checked:
            bg_brush = QBrush(QColor("#2ED573"))
            pen = QPen(QColor(255, 255, 255, 30), 1)
            thumb_x = rect.right() - 17.5
        else:
            bg_brush = QBrush(QColor(36, 42, 60, 200))
            pen = QPen(QColor(255, 255, 255, 20), 1)
            thumb_x = rect.left() + 2.5

        painter.setBrush(bg_brush)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 11, 11)

        # White thumb
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(thumb_x, rect.top() + 2.5, 16, 16))

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)


# ==============================================================================
# ValueSlider Component
# ==============================================================================

class ValueSlider(QWidget):
    """
    Modern translucent slider with thin accent track, glowing white thumb,
    and trailing numeric badge.
    """
    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        min_val: int = 0,
        max_val: int = 100,
        val: int = 50,
        suffix: str = "%",
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._suffix = suffix

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(min_val, max_val)
        self.slider.setValue(val)
        self.slider.setFixedHeight(20)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #2ED573;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: 1px solid rgba(0,0,0,0.1);
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #2ED573;
            }
        """)
        self.slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self.slider, 1)

        self.lbl_val = QLabel(f"{val}{suffix}", self)
        self.lbl_val.setStyleSheet("font-size: 11px; font-weight: 600; color: #8A8D9B; min-width: 38px; text-align: right;")
        self.lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.lbl_val)

    def _on_value_changed(self, v: int):
        self.lbl_val.setText(f"{v}{self._suffix}")
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int):
        self.slider.setValue(v)
        self.lbl_val.setText(f"{v}{self._suffix}")


# ==============================================================================
# ColorSwatchButton & KeycapWidget
# ==============================================================================

class ColorSwatchButton(QPushButton):
    """Color swatch button with hex label."""
    colorChanged = pyqtSignal(str)

    def __init__(self, color_hex: str = "#FFFFFF", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = color_hex
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_appearance()
        self.clicked.connect(self._pick_color)

    def _pick_color(self):
        col = QColorDialog.getColor(QColor(self._color), self, "Select Color")
        if col.isValid():
            self._color = col.name().upper()
            self._update_appearance()
            self.colorChanged.emit(self._color)

    def _update_appearance(self):
        self.setText(f"  {self._color}")
        self.setStyleSheet(f"""
            QPushButton {{
                background: rgba(24, 28, 38, 0.68);
                color: #F0F1F5;
                font-family: monospace;
                font-size: 11px;
                font-weight: 600;
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 8px;
                padding: 4px 10px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: rgba(255, 255, 255, 0.20);
            }}
        """)
        pix = QPixmap(14, 14)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(self._color)))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawEllipse(0, 0, 13, 13)
        p.end()
        self.setIcon(QIcon(pix))

    def color(self) -> str:
        return self._color

    def setColor(self, color_hex: str):
        self._color = color_hex
        self._update_appearance()


class KeycapWidget(QWidget):
    """Physical keycap hotkey recorder."""
    def __init__(self, key_sequence: str = "Ctrl+H", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._seq = key_sequence

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        parts = self._seq.split("+")
        for p in parts:
            lbl = QLabel(p, self)
            lbl.setStyleSheet("""
                background: rgba(30, 35, 46, 0.78);
                color: #2ED573;
                font-weight: 700;
                font-size: 11px;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 4px 8px;
            """)
            layout.addWidget(lbl)

        btn_change = QPushButton("Change", self)
        btn_change.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8A8D9B;
                font-size: 11px;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                color: #FFFFFF;
                border-color: #2ED573;
            }
        """)
        layout.addWidget(btn_change)

    def keySequence(self) -> QKeySequence:
        return QKeySequence(self._seq)
