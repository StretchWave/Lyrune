"""
settings_dialog.py — Modern Translucent Cinematic Glass Desktop UI for Lyrune.

Implements the unified glass desktop design with dedicated Studios, real live previews,
frameless window management, and mathematical coordinate accuracy.
"""

import os
import re
import platform
import sys
import math
import time
from typing import Dict, Any, Optional, List, Tuple
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QPointF, QRectF, QRect, QTimer, QSize
from PyQt6.QtGui import (
    QFont, QColor, QKeySequence, QMouseEvent, QPainter, QBrush, QPen,
    QLinearGradient, QRadialGradient, QPixmap, QCursor, QPainterPath, QFontMetrics
)
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QPushButton, QComboBox, QFontComboBox, QTextEdit, QCheckBox,
    QListWidget, QListWidgetItem, QStackedWidget, QScrollArea, QFrame,
    QApplication, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QSizePolicy, QToolButton, QSlider
)

from lyrune.ui_theme import (
    PALETTE, DARK_THEME_STYLESHEET, MENU_STYLESHEET, get_icon, get_app_icon,
    extract_dominant_accent, paint_atmospheric_background, GlassCard, BentoCard,
    DynamicIslandBar, SegmentedSwitch, SubTabRow, ToggleSwitch, ValueSlider,
    ColorSwatchButton, KeycapWidget
)
from lyrune.settings_manager import SettingsManager, PRESETS
from lyrune.logger import AppLogger
from lyrune.animation_engine import LyricsRenderer
from lyrune.lrclib_client import LRCLibClient
from lyrune.visualizer import BarVisualizer, AudioData
from lyrune.window_utils import get_available_screen_options
from lyrune.wallpaper.preview_widget import WallpaperPreviewWidget
from lyrune.wallpaper.model import WallpaperConfig, MediaSnapshot
from lyrune.wallpaper.monitor import get_wallpaper_display_options


class VisualizerPreviewWidget(QWidget):
    """
    Live interactive preview canvas for the visualizer inside SettingsDialog.
    Runs simulated musical frequencies at 60 FPS on glass background.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(140)
        self.setMinimumWidth(280)
        self.renderer = BarVisualizer()
        self.renderer.set_orientation("BOTTOM")
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def update_style(self, settings_dict: Dict[str, Any]):
        self.renderer.set_style(settings_dict)
        self.update()

    def _on_tick(self):
        if not self.isVisible():
            return
        self._phase += 0.05
        count = self.renderer.get_bar_count()
        amps = []
        for i in range(count):
            norm = i / max(1, count - 1)
            val = (
                0.5 * math.sin(self._phase * 3.0 + norm * 5.0) +
                0.3 * math.sin(self._phase * 1.5 - norm * 8.0) +
                0.2 * math.cos(self._phase * 4.0 + norm * 12.0)
            )
            amps.append(max(0.08, min(1.0, 0.45 + 0.55 * val)))
        self.renderer.update_audio(AudioData(amplitudes=amps, energy=0.7, timestamp=time.time()))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setBrush(QBrush(QColor(24, 28, 38, 160)))
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

        draw_rect = self.rect().adjusted(14, 14, -14, -14)
        self.renderer.resize(draw_rect.width(), draw_rect.height())
        self.renderer.paint(painter, draw_rect)


class GradientPreviewBar(QWidget):
    """Visual gradient preview strip."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.stops: List[Dict[str, Any]] = []

    def set_stops(self, stops: List[Dict[str, Any]]):
        self.stops = list(stops)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        grad = QLinearGradient(rect.left(), rect.center().y(), rect.right(), rect.center().y())

        if not self.stops:
            grad.setColorAt(0.0, QColor("#2ED573"))
            grad.setColorAt(1.0, QColor("#1DB954"))
        else:
            for s in sorted(self.stops, key=lambda x: x.get("position", 0.0)):
                pos = max(0.0, min(1.0, float(s.get("position", 0.0))))
                col = QColor(s.get("color", "#2ED573"))
                if not col.isValid():
                    col = QColor("#2ED573")
                col.setAlphaF(max(0.0, min(1.0, float(s.get("opacity", 1.0)))))
                grad.setColorAt(pos, col)

        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        painter.drawRoundedRect(rect, 6, 6)


class CustomTitleBar(QWidget):
    """
    Modern glass title bar featuring:
      - Left: Logo icon + 'LYRUNE' bold text
      - Center: Floating Dynamic Island media pill
      - Right: Window controls (Theme, Minimize, Maximize/Restore, Close)
    """
    minimizeClicked = pyqtSignal()
    maximizeClicked = pyqtSignal()
    closeClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 6, 18, 6)
        layout.setSpacing(12)

        # Left branding
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(8)

        self.lbl_logo = QLabel(self)
        self.lbl_logo.setPixmap(get_icon("visualizer", color="#2ED573").pixmap(20, 20))
        brand_layout.addWidget(self.lbl_logo)

        self.lbl_name = QLabel("LYRUNE", self)
        self.lbl_name.setStyleSheet("font-size: 13px; font-weight: 800; letter-spacing: 1.5px; color: #FFFFFF;")
        brand_layout.addWidget(self.lbl_name)
        layout.addLayout(brand_layout)

        layout.addStretch(1)

        # Center Dynamic Island
        self.dynamic_island = DynamicIslandBar(self)
        layout.addWidget(self.dynamic_island)

        layout.addStretch(1)

        # Right window buttons
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(6)

        self.btn_theme = QPushButton(self)
        self.btn_theme.setIcon(get_icon("moon", color="#C5C8D4"))
        self.btn_theme.setFixedSize(28, 28)
        self.btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 6px; }
            QPushButton:hover { background: rgba(255, 255, 255, 0.08); }
        """)
        ctrl_layout.addWidget(self.btn_theme)

        self.btn_min = QPushButton(self)
        self.btn_min.setIcon(get_icon("minus", color="#C5C8D4"))
        self.btn_min.setFixedSize(28, 28)
        self.btn_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_min.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 6px; }
            QPushButton:hover { background: rgba(255, 255, 255, 0.08); }
        """)
        self.btn_min.clicked.connect(self.minimizeClicked.emit)
        ctrl_layout.addWidget(self.btn_min)

        self.btn_max = QPushButton(self)
        self.btn_max.setIcon(get_icon("maximize", color="#C5C8D4"))
        self.btn_max.setFixedSize(28, 28)
        self.btn_max.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_max.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 6px; }
            QPushButton:hover { background: rgba(255, 255, 255, 0.08); }
        """)
        self.btn_max.clicked.connect(self.maximizeClicked.emit)
        ctrl_layout.addWidget(self.btn_max)

        self.btn_close = QPushButton(self)
        self.btn_close.setIcon(get_icon("close", color="#C5C8D4"))
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 6px; }
            QPushButton:hover { background: rgba(255, 71, 87, 0.35); color: #FF4757; }
        """)
        self.btn_close.clicked.connect(self.closeClicked.emit)
        ctrl_layout.addWidget(self.btn_close)

        layout.addLayout(ctrl_layout)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            if hasattr(win, "_toggle_maximize_restore"):
                win._toggle_maximize_restore()


class SettingsDialog(QDialog):
    """
    Modern translucent cinematic desktop music dashboard and settings studio.
    Provides complete, unified controls for Wallpaper Studio, Visualizer Studio,
    Overlay Appearance, Typography, Behavior, Shortcuts, and Diagnostics.
    """
    settings_changed = pyqtSignal(dict)

    def __init__(self, settings_manager: SettingsManager, player=None, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.player = player
        self.working_settings = dict(settings_manager.settings)
        self._is_initializing = True
        self._current_pixmap: Optional[QPixmap] = None
        self._ambient_accent = QColor("#2ED573")
        self._log_connected = False

        # Window state & Frameless resize support
        self._drag_pos: Optional[QPoint] = None
        self._resize_edge: Optional[str] = None
        self._resize_drag_start: Optional[QPoint] = None
        self._resize_start_geometry: Optional[QRect] = None

        self.setWindowTitle("Lyrune Studio")
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowMinMaxButtonsHint |
            Qt.WindowType.WindowSystemMenuHint
        )
        self.resize(1060, 720)
        self.setMinimumSize(920, 600)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setStyleSheet(DARK_THEME_STYLESHEET)
        self.setWindowIcon(get_app_icon())

        self._init_ui()
        self._load_current_values()

        # Connect live media polling
        if self.player:
            self._sync_media_loop()
            self._media_poll_timer = QTimer(self)
            self._media_poll_timer.setInterval(800)
            self._media_poll_timer.timeout.connect(self._sync_media_loop)
            self._media_poll_timer.start()

        self._is_initializing = False
        self._update_preview()

        # Connect logger
        try:
            AppLogger.instance().log_signal.connect(self._append_log_entry)
            self._log_connected = True
        except Exception:
            pass
        self._load_log_history()

    # === Window Behavior & Edge Resizing ===

    def _toggle_maximize_restore(self):
        if self.isMaximized():
            self.showNormal()
            self.title_bar.btn_max.setIcon(get_icon("maximize", color="#C5C8D4"))
        else:
            self.showMaximized()
            self.title_bar.btn_max.setIcon(get_icon("restore", color="#C5C8D4"))

    def _determine_edge(self, pos: QPoint) -> Optional[str]:
        if self.isMaximized():
            return None
        border = 8
        w = self.width()
        h = self.height()
        x = pos.x()
        y = pos.y()

        left = x <= border
        right = x >= w - border
        top = y <= border
        bottom = y >= h - border

        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._determine_edge(event.pos())
            if edge:
                self._resize_edge = edge
                self._resize_drag_start = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
                event.accept()
                return

            # Check if clicking on title bar area for window dragging
            if event.pos().y() <= 48 and not self.isMaximized():
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # Handle active resizing
        if self._resize_edge and self._resize_drag_start and self._resize_start_geometry:
            diff = event.globalPosition().toPoint() - self._resize_drag_start
            g = QRect(self._resize_start_geometry)
            min_w = self.minimumWidth()
            min_h = self.minimumHeight()

            if "left" in self._resize_edge:
                new_w = max(min_w, g.width() - diff.x())
                g.setLeft(g.right() - new_w)
            if "right" in self._resize_edge:
                new_w = max(min_w, g.width() + diff.x())
                g.setWidth(new_w)
            if "top" in self._resize_edge:
                new_h = max(min_h, g.height() - diff.y())
                g.setTop(g.bottom() - new_h)
            if "bottom" in self._resize_edge:
                new_h = max(min_h, g.height() + diff.y())
                g.setHeight(new_h)

            self.setGeometry(g)
            event.accept()
            return

        # Handle active window dragging
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton and not self.isMaximized():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return

        # Update hover cursor for window edges
        if not self.isMaximized():
            edge = self._determine_edge(event.pos())
            if edge in ("top_left", "bottom_right"):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif edge in ("top_right", "bottom_left"):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif edge in ("left", "right"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif edge in ("top", "bottom"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        self._resize_edge = None
        self._resize_drag_start = None
        self._resize_start_geometry = None
    def showEvent(self, event):
        super().showEvent(event)
        try:
            from lyrune.window_utils import enable_acrylic_blur
            enable_acrylic_blur(int(self.winId()))
        except Exception:
            pass

    def paintEvent(self, event):
        """Draws the atmospheric nebula background with organic color fields and specular frame."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # 1. Atmospheric translucent cosmic nebula background
        paint_atmospheric_background(painter, rect, self._ambient_accent)

        # 2. Translucent shell overlay (~20-30% visual translucency)
        painter.setBrush(QBrush(QColor(15, 18, 25, 130)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 20, 20)

        # 3. Outer window border with specular highlight
        border_pen = QPen(QColor(255, 255, 255, 24), 1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 20, 20)

        # Top specular highlight line
        highlight_pen = QPen(QColor(255, 255, 255, 16), 1)
        painter.setPen(highlight_pen)
        painter.drawLine(
            QPointF(rect.left() + 20, rect.top()),
            QPointF(rect.right() - 20, rect.top())
        )

    # === UI Construction ===

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Custom Title Bar
        self.title_bar = CustomTitleBar(self)
        self.title_bar.minimizeClicked.connect(self.showMinimized)
        self.title_bar.maximizeClicked.connect(self._toggle_maximize_restore)
        self.title_bar.closeClicked.connect(self.reject)
        self.title_bar.dynamic_island.playPauseClicked.connect(self._transport_play_pause)
        self.title_bar.dynamic_island.prevClicked.connect(self._transport_prev)
        self.title_bar.dynamic_island.nextClicked.connect(self._transport_next)
        root_layout.addWidget(self.title_bar)

        # 2. Main Workspace Layout (Sidebar + Content Stack)
        workspace = QWidget(self)
        ws_layout = QHBoxLayout(workspace)
        ws_layout.setContentsMargins(14, 4, 14, 10)
        ws_layout.setSpacing(14)

        # 2A. Floating Sidebar
        self.sidebar_card = GlassCard(radius=18, elevated=False, parent=workspace)
        self.sidebar_card.setFixedWidth(185)
        sb_layout = QVBoxLayout(self.sidebar_card)
        sb_layout.setContentsMargins(10, 14, 10, 14)
        sb_layout.setSpacing(4)

        self._nav_buttons: List[QPushButton] = []
        self._nav_items_data = [
            ("overview", "Overview", 0),
            ("SECTION", "DISPLAY", -1),
            ("appearance", "Appearance", 1),
            ("typography", "Typography", 2),
            ("wallpaper", "Wallpaper Studio", 3),
            ("visualizer", "Visualizer Studio", 4),
            ("SECTION", "SYSTEM", -1),
            ("behavior", "Behavior", 5),
            ("shortcuts", "Shortcuts", 6),
            ("advanced", "Advanced", 7),
        ]

        for icon_key, label, page_idx in self._nav_items_data:
            if icon_key == "SECTION":
                lbl_sec = QLabel(label, self.sidebar_card)
                lbl_sec.setStyleSheet("font-size: 10px; font-weight: 700; color: #525666; letter-spacing: 1px; margin: 10px 6px 4px 6px;")
                sb_layout.addWidget(lbl_sec)
            else:
                btn = QPushButton(f" {label}", self.sidebar_card)
                btn.setIcon(get_icon(icon_key, color="#C5C8D4"))
                btn.setFixedHeight(34)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _, idx=page_idx: self._select_nav(idx))
                sb_layout.addWidget(btn)
                self._nav_buttons.append(btn)

        sb_layout.addStretch(1)

        # Spotify Connection Status Pill
        self.spotify_status_card = GlassCard(radius=12, elevated=True, interactive=True, parent=self.sidebar_card)
        self.spotify_status_card.setFixedHeight(50)
        sp_layout = QHBoxLayout(self.spotify_status_card)
        sp_layout.setContentsMargins(10, 6, 10, 6)
        sp_layout.setSpacing(8)

        sp_icon = QLabel(self.spotify_status_card)
        sp_icon.setPixmap(get_icon("spotify", color="#1DB954").pixmap(20, 20))
        sp_layout.addWidget(sp_icon)

        sp_text_layout = QVBoxLayout()
        sp_text_layout.setSpacing(1)
        sp_lbl1 = QLabel("Spotify", self.spotify_status_card)
        sp_lbl1.setStyleSheet("font-size: 11px; font-weight: 700; color: #FFFFFF;")
        sp_text_layout.addWidget(sp_lbl1)

        self.sp_lbl_status = QLabel("● Connected", self.spotify_status_card)
        self.sp_lbl_status.setStyleSheet("font-size: 9px; color: #2ED573; font-weight: 600;")
        sp_text_layout.addWidget(self.sp_lbl_status)
        sp_layout.addLayout(sp_text_layout, 1)

        lbl_sp_arr = QLabel(self.spotify_status_card)
        lbl_sp_arr.setPixmap(get_icon("chevron_right", color="#525666").pixmap(12, 12))
        sp_layout.addWidget(lbl_sp_arr)

        sb_layout.addWidget(self.spotify_status_card)

        lbl_version = QLabel("v2.4.1", self.sidebar_card)
        lbl_version.setStyleSheet("font-size: 10px; color: #525666; margin-left: 6px; margin-top: 4px;")
        sb_layout.addWidget(lbl_version)

        ws_layout.addWidget(self.sidebar_card)

        # 2B. Content Pages Stack
        self.content_stack = QStackedWidget(workspace)
        self._build_overview_page()
        self._build_appearance_page()
        self._build_typography_page()
        self._build_wallpaper_studio_page()
        self._build_visualizer_studio_page()
        self._build_behavior_page()
        self._build_shortcuts_page()
        self._build_advanced_page()
        ws_layout.addWidget(self.content_stack, 1)

        root_layout.addWidget(workspace, 1)

        # 3. Sticky Bottom Action Bar
        footer = QWidget(self)
        footer.setFixedHeight(54)
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(20, 8, 20, 10)
        f_layout.setSpacing(12)

        self.btn_reset = QPushButton("Reset to Defaults", footer)
        self.btn_reset.setIcon(get_icon("refresh", color="#8A8D9B"))
        self.btn_reset.setFixedHeight(34)
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.setStyleSheet("""
            QPushButton {
                background: rgba(24, 28, 38, 0.68);
                color: #C5C8D4;
                font-size: 12px;
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 10px;
                padding: 0 14px;
            }
            QPushButton:hover {
                background: rgba(36, 42, 58, 0.85);
                color: #FFFFFF;
                border-color: rgba(255, 255, 255, 0.18);
            }
        """)
        self.btn_reset.clicked.connect(self._reset_to_defaults)
        f_layout.addWidget(self.btn_reset)

        f_layout.addStretch(1)

        self.lbl_footer_status = QLabel("Changes will be applied to Lyrune only. ⓘ", footer)
        self.lbl_footer_status.setStyleSheet("color: #8A8D9B; font-size: 11px;")
        f_layout.addWidget(self.lbl_footer_status)

        f_layout.addStretch(1)

        self.btn_cancel = QPushButton("Cancel", footer)
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background: rgba(24, 28, 38, 0.68);
                color: #C5C8D4;
                font-size: 12px;
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 10px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background: rgba(36, 42, 58, 0.85);
                color: #FFFFFF;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        f_layout.addWidget(self.btn_cancel)

        self.btn_apply = QPushButton("Apply", footer)
        self.btn_apply.setFixedHeight(34)
        self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background: rgba(30, 35, 46, 0.78);
                color: #FFFFFF;
                font-size: 12px;
                font-weight: 600;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 10px;
                padding: 0 18px;
            }
            QPushButton:hover {
                background: rgba(46, 54, 76, 0.90);
                border-color: #2ED573;
            }
        """)
        self.btn_apply.clicked.connect(self._on_apply)
        f_layout.addWidget(self.btn_apply)

        self.btn_ok = QPushButton("✓  OK", footer)
        self.btn_ok.setFixedHeight(34)
        self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ok.setStyleSheet("""
            QPushButton {
                background: #2ED573;
                color: #080A12;
                font-size: 12px;
                font-weight: 700;
                border: none;
                border-radius: 10px;
                padding: 0 20px;
            }
            QPushButton:hover {
                background: #26AF5F;
            }
        """)
        self.btn_ok.clicked.connect(self._on_ok)
        f_layout.addWidget(self.btn_ok)

        root_layout.addWidget(footer)

        self._select_nav(0)

    # === Navigation Switcher ===

    def _select_nav(self, page_index: int):
        if page_index < 0 or page_index >= self.content_stack.count():
            return
        self.content_stack.setCurrentIndex(page_index)

        # Update button styles
        btn_idx = 0
        for icon_key, label, p_idx in self._nav_items_data:
            if icon_key == "SECTION":
                continue
            btn = self._nav_buttons[btn_idx]
            if p_idx == page_index:
                btn.setIcon(get_icon(icon_key, color="#2ED573"))
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(46, 213, 115, 0.12);
                        color: #FFFFFF;
                        font-size: 12px;
                        font-weight: 700;
                        border: 1px solid rgba(46, 213, 115, 0.40);
                        border-radius: 10px;
                        text-align: left;
                        padding-left: 10px;
                    }
                """)
            else:
                btn.setIcon(get_icon(icon_key, color="#8A8D9B"))
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #C5C8D4;
                        font-size: 12px;
                        font-weight: 500;
                        border: none;
                        border-radius: 10px;
                        text-align: left;
                        padding-left: 10px;
                    }
                    QPushButton:hover {
                        background: rgba(255, 255, 255, 0.055);
                        color: #FFFFFF;
                    }
                """)
            btn_idx += 1

    # ==============================================================================
    # PAGE 0: OVERVIEW DASHBOARD
    # ==============================================================================

    def _build_overview_page(self):
        self.overview_page = QWidget()
        page_layout = QHBoxLayout(self.overview_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(14)

        # ----------------------------------------------------
        # Left Column (Now Playing + 2x2 Bento Status Grid + Quick Actions)
        # ----------------------------------------------------
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        # Heading
        lbl_heading = QLabel("Overview", self.overview_page)
        lbl_heading.setStyleSheet("font-size: 24px; font-weight: 800; color: #FFFFFF;")
        left_col.addWidget(lbl_heading)

        lbl_subhead = QLabel("Everything looks good. Enjoy the music.", self.overview_page)
        lbl_subhead.setStyleSheet("font-size: 12px; color: #8A8D9B; margin-bottom: 2px;")
        left_col.addWidget(lbl_subhead)

        # Hero Now Playing Bento Card
        self.hero_card = GlassCard(radius=18, elevated=False, interactive=True, parent=self.overview_page)
        self.hero_card.setFixedHeight(168)
        hero_layout = QHBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(14, 14, 16, 14)
        hero_layout.setSpacing(14)

        self.lbl_hero_art = QLabel(self.hero_card)
        self.lbl_hero_art.setFixedSize(140, 140)
        self.lbl_hero_art.setStyleSheet("background: #141724; border-radius: 12px; border: 1px solid rgba(255,255,255,0.12);")
        self.lbl_hero_art.setScaledContents(True)
        hero_layout.addWidget(self.lbl_hero_art)

        hero_info = QVBoxLayout()
        hero_info.setSpacing(4)
        hero_info.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Source badge
        self.lbl_hero_source = QLabel("● Playing on Spotify", self.hero_card)
        self.lbl_hero_source.setStyleSheet("""
            background: rgba(46, 213, 115, 0.12);
            color: #2ED573;
            font-size: 10px;
            font-weight: 700;
            border: 1px solid rgba(46, 213, 115, 0.35);
            border-radius: 10px;
            padding: 3px 8px;
        """)
        self.lbl_hero_source.setFixedHeight(20)
        hero_info.addWidget(self.lbl_hero_source, 0, Qt.AlignmentFlag.AlignLeft)

        self.lbl_hero_title = QLabel("Lyrune Studio", self.hero_card)
        self.lbl_hero_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #FFFFFF;")
        hero_info.addWidget(self.lbl_hero_title)

        self.lbl_hero_artist = QLabel("No track playing", self.hero_card)
        self.lbl_hero_artist.setStyleSheet("font-size: 13px; color: #C5C8D4;")
        hero_info.addWidget(self.lbl_hero_artist)

        # Live Scrubber
        scrub_row = QHBoxLayout()
        scrub_row.setSpacing(8)

        self.lbl_scrub_cur = QLabel("1:07", self.hero_card)
        self.lbl_scrub_cur.setStyleSheet("font-size: 10px; color: #8A8D9B;")
        scrub_row.addWidget(self.lbl_scrub_cur)

        self.hero_progress = QSlider(Qt.Orientation.Horizontal, self.hero_card)
        self.hero_progress.setRange(0, 100)
        self.hero_progress.setValue(32)
        self.hero_progress.setFixedHeight(14)
        self.hero_progress.setStyleSheet("""
            QSlider::groove:horizontal { height: 3px; background: rgba(255,255,255,0.12); border-radius: 1.5px; }
            QSlider::sub-page:horizontal { background: #2ED573; border-radius: 1.5px; }
            QSlider::handle:horizontal { background: #FFFFFF; width: 10px; height: 10px; margin: -3.5px 0; border-radius: 5px; }
        """)
        scrub_row.addWidget(self.hero_progress, 1)

        self.lbl_scrub_tot = QLabel("3:29", self.hero_card)
        self.lbl_scrub_tot.setStyleSheet("font-size: 10px; color: #8A8D9B;")
        scrub_row.addWidget(self.lbl_scrub_tot)
        hero_info.addLayout(scrub_row)

        # Codec / Audio Meta Chips
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)
        chips = ["🎧 320 kbps", "🔊 44.1 kHz", "🔀 Stereo"]
        for c in chips:
            lbl_c = QLabel(c, self.hero_card)
            lbl_c.setStyleSheet("font-size: 10px; color: #8A8D9B;")
            chips_row.addWidget(lbl_c)
        chips_row.addStretch(1)
        hero_info.addLayout(chips_row)

        hero_layout.addLayout(hero_info, 1)
        left_col.addWidget(self.hero_card)

        # 2x2 Bento Status Grid
        grid_layout = QVBoxLayout()
        grid_layout.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.bento_lyrics = BentoCard("Lyrics Overlay", "Lyrics are syncing in real-time", badge_type="lyrics", active=True, parent=self.overview_page)
        self.bento_lyrics.clicked.connect(lambda: self._select_nav(1))
        row1.addWidget(self.bento_lyrics, 1)

        self.bento_visualizer = BentoCard("Visualizer", "Audio reactive spectrum active", badge_type="visualizer", active=True, parent=self.overview_page)
        self.bento_visualizer.clicked.connect(lambda: self._select_nav(4))
        row1.addWidget(self.bento_visualizer, 1)
        grid_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.bento_wallpaper = BentoCard("Wallpaper Engine", "Aurora landscape set as wallpaper", badge_type="wallpaper", active=True, parent=self.overview_page)
        self.bento_wallpaper.clicked.connect(lambda: self._select_nav(3))
        row2.addWidget(self.bento_wallpaper, 1)

        self.bento_media = BentoCard("Media Source", "Spotify Desktop App connected", badge_type="spotify", active=True, parent=self.overview_page)
        self.bento_media.clicked.connect(lambda: self._select_nav(5))
        row2.addWidget(self.bento_media, 1)
        grid_layout.addLayout(row2)

        left_col.addLayout(grid_layout)

        # Quick Actions Row
        lbl_qa = QLabel("Quick Actions", self.overview_page)
        lbl_qa.setStyleSheet("font-size: 12px; font-weight: 600; color: #8A8D9B; margin-top: 4px;")
        left_col.addWidget(lbl_qa)

        qa_row = QHBoxLayout()
        qa_row.setSpacing(6)

        actions = [
            ("refresh", "Refresh Lyrics", self._refresh_lyrics_action),
            ("visualizer", "Calibrate Audio", lambda: self._select_nav(4)),
            ("appearance", "Edit Overlay", lambda: self._select_nav(1)),
            ("shortcuts", "Open Logs", lambda: self._select_nav(7)),
        ]
        for icon_k, label, cb in actions:
            btn = QPushButton(f" {label}", self.overview_page)
            btn.setIcon(get_icon(icon_k, color="#8A8D9B"))
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(24, 28, 38, 0.68);
                    color: #F0F1F5;
                    font-size: 10px;
                    font-weight: 500;
                    border: 1px solid rgba(255, 255, 255, 0.09);
                    border-radius: 8px;
                    padding: 0 4px;
                }
                QPushButton:hover {
                    background: rgba(36, 42, 58, 0.85);
                    border-color: #2ED573;
                    color: #2ED573;
                }
            """)
            btn.clicked.connect(cb)
            qa_row.addWidget(btn, 1)

        left_col.addLayout(qa_row)
        left_col.addStretch(1)
        page_layout.addLayout(left_col, 5)

        # ----------------------------------------------------
        # Right Column (Studio Hub: Segmented Switch + Interactive Preview + Studio Subtabs)
        # ----------------------------------------------------
        self.right_studio_card = GlassCard(radius=18, elevated=False, parent=self.overview_page)
        r_layout = QVBoxLayout(self.right_studio_card)
        r_layout.setContentsMargins(14, 14, 14, 14)
        r_layout.setSpacing(10)

        # Top Segmented Switcher (Wallpaper Studio vs Visualizer Studio)
        self.studio_switch = SegmentedSwitch([
            ("wallpaper", "Wallpaper Studio"),
            ("visualizer", "Visualizer Studio")
        ], self.right_studio_card)
        self.studio_switch.switched.connect(self._on_studio_switch)
        r_layout.addWidget(self.studio_switch)

        # Studio Hub Stack
        self.overview_studio_stack = QStackedWidget(self.right_studio_card)

        # === 1. Wallpaper Hub ===
        self.wp_hub = QWidget()
        wp_h_layout = QVBoxLayout(self.wp_hub)
        wp_h_layout.setContentsMargins(0, 0, 0, 0)
        wp_h_layout.setSpacing(8)

        # Title & Toggle row
        wp_header = QHBoxLayout()
        wp_title_layout = QVBoxLayout()
        wp_title_layout.setSpacing(1)

        lbl_wp_title = QLabel("Desktop Wallpaper", self.wp_hub)
        lbl_wp_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #FFFFFF;")
        wp_title_layout.addWidget(lbl_wp_title)

        lbl_wp_sub = QLabel("Set a dynamic wallpaper with album art, vinyl and lyrics.", self.wp_hub)
        lbl_wp_sub.setStyleSheet("font-size: 11px; color: #8A8D9B;")
        wp_title_layout.addWidget(lbl_wp_sub)
        wp_header.addLayout(wp_title_layout, 1)

        self.toggle_wp_enable = ToggleSwitch("", self.wp_hub)
        self.toggle_wp_enable.setChecked(True)
        self.toggle_wp_enable.toggled.connect(self._on_toggle_wallpaper)
        wp_header.addWidget(self.toggle_wp_enable)
        wp_h_layout.addLayout(wp_header)

        # Live Interactive Wallpaper Canvas
        self.wallpaper_preview = WallpaperPreviewWidget(self.wp_hub)
        self.wallpaper_preview.setFixedHeight(170)
        self.wallpaper_preview.vinyl_position_changed.connect(self._on_vinyl_preview_moved)
        self.wallpaper_preview.vinyl_size_changed.connect(self._on_vinyl_preview_resized)
        wp_h_layout.addWidget(self.wallpaper_preview)

        # Sub Tabs
        self.subtabs_wp = SubTabRow(["GENERAL", "VINYL", "ALBUM ART", "TEXT", "INTERACTION"], self.wp_hub)
        self.subtabs_wp.tabSelected.connect(self._on_wp_subtab_selected)
        wp_h_layout.addWidget(self.subtabs_wp)

        # Subtab Control Stack
        self.wp_subtab_stack = QStackedWidget(self.wp_hub)

        # Subtab 0: GENERAL
        wp_tab_gen = QWidget()
        gen_l = QVBoxLayout(wp_tab_gen)
        gen_l.setContentsMargins(0, 4, 0, 0)
        gen_l.setSpacing(6)

        self.combo_wp_playback = QComboBox(wp_tab_gen)
        self.combo_wp_playback.addItems(["Always Play", "Pause When Hidden", "Mute Audio Only"])
        gen_l.addLayout(self._create_studio_control_row("Playback", "How the wallpaper should behave.", self.combo_wp_playback))

        self.slider_wp_volume = ValueSlider(0, 100, 38, "%", wp_tab_gen)
        self.slider_wp_volume.valueChanged.connect(lambda v: self._set_cfg("wallpaper_volume", v))
        gen_l.addLayout(self._create_studio_control_row("Volume", "Audio volume for the wallpaper.", self.slider_wp_volume))

        self.slider_wp_bright = ValueSlider(0, 100, 72, "%", wp_tab_gen)
        self.slider_wp_bright.valueChanged.connect(lambda v: self._set_cfg("wallpaper_brightness", v))
        gen_l.addLayout(self._create_studio_control_row("Brightness", "Adjust wallpaper brightness.", self.slider_wp_bright))

        self.slider_wp_sat = ValueSlider(0, 100, 64, "%", wp_tab_gen)
        self.slider_wp_sat.valueChanged.connect(lambda v: self._set_cfg("wallpaper_saturation", v))
        gen_l.addLayout(self._create_studio_control_row("Saturation", "Color intensity of the wallpaper.", self.slider_wp_sat))
        self.wp_subtab_stack.addWidget(wp_tab_gen)

        # Subtab 1: VINYL
        wp_tab_vinyl = QWidget()
        v_l = QVBoxLayout(wp_tab_vinyl)
        v_l.setContentsMargins(0, 4, 0, 0)
        v_l.setSpacing(6)

        self.slider_vinyl_size = ValueSlider(5, 60, 40, "%", wp_tab_vinyl)
        self.slider_vinyl_size.valueChanged.connect(self._on_vinyl_size_slider)
        v_l.addLayout(self._create_studio_control_row("Vinyl Size", "Record diameter on screen.", self.slider_vinyl_size))

        self.slider_vinyl_speed = ValueSlider(3, 60, 12, "s", wp_tab_vinyl)
        self.slider_vinyl_speed.valueChanged.connect(lambda v: self._set_cfg("rotation_speed", float(v)))
        v_l.addLayout(self._create_studio_control_row("Rotation Speed", "Seconds per full 360° turn.", self.slider_vinyl_speed))

        self.slider_vinyl_op = ValueSlider(0, 100, 100, "%", wp_tab_vinyl)
        self.slider_vinyl_op.valueChanged.connect(lambda v: self._set_cfg("vinyl_opacity", v))
        v_l.addLayout(self._create_studio_control_row("Opacity", "Overall opacity of the vinyl record.", self.slider_vinyl_op))

        self.toggle_vinyl_rot = ToggleSwitch("", wp_tab_vinyl)
        self.toggle_vinyl_rot.setChecked(True)
        self.toggle_vinyl_rot.toggled.connect(lambda c: self._set_cfg("rotate_while_playing", c))
        v_l.addLayout(self._create_studio_control_row("Rotate While Playing", "Smooth 60 FPS vinyl rotation.", self.toggle_vinyl_rot))
        self.wp_subtab_stack.addWidget(wp_tab_vinyl)

        # Subtab 2: ALBUM ART
        wp_tab_art = QWidget()
        a_l = QVBoxLayout(wp_tab_art)
        a_l.setContentsMargins(0, 4, 0, 0)
        a_l.setSpacing(6)

        self.slider_art_ratio = ValueSlider(20, 80, 50, "%", wp_tab_art)
        self.slider_art_ratio.valueChanged.connect(lambda v: self._set_cfg("cover_size_ratio", v / 100.0))
        a_l.addLayout(self._create_studio_control_row("Center Label Ratio", "Size of album art in center.", self.slider_art_ratio))

        self.toggle_art_spindle = ToggleSwitch("", wp_tab_art)
        self.toggle_art_spindle.setChecked(True)
        self.toggle_art_spindle.toggled.connect(lambda c: self._set_cfg("show_center_spindle", c))
        a_l.addLayout(self._create_studio_control_row("Center Spindle Dot", "Draw center turntable spindle hole.", self.toggle_art_spindle))
        self.wp_subtab_stack.addWidget(wp_tab_art)

        # Subtab 3: TEXT
        wp_tab_text = QWidget()
        t_l = QVBoxLayout(wp_tab_text)
        t_l.setContentsMargins(0, 4, 0, 0)
        t_l.setSpacing(6)

        self.combo_text_pos = QComboBox(wp_tab_text)
        self.combo_text_pos.addItems(["Right of Vinyl", "Below Vinyl", "Above Vinyl", "Hidden"])
        self.combo_text_pos.currentIndexChanged.connect(lambda idx: self._set_cfg("text_position", ["right", "below", "above", "hidden"][idx]))
        t_l.addLayout(self._create_studio_control_row("Text Position", "Song title & artist placement.", self.combo_text_pos))

        self.swatch_text_color = ColorSwatchButton("#FFFFFF", wp_tab_text)
        self.swatch_text_color.colorChanged.connect(lambda c: self._set_cfg("text_color", c))
        t_l.addLayout(self._create_studio_control_row("Text Color", "Color for song metadata text.", self.swatch_text_color))
        self.wp_subtab_stack.addWidget(wp_tab_text)

        # Subtab 4: INTERACTION
        wp_tab_int = QWidget()
        i_l = QVBoxLayout(wp_tab_int)
        i_l.setContentsMargins(0, 4, 0, 0)
        i_l.setSpacing(6)

        self.toggle_wp_pause_mute = ToggleSwitch("", wp_tab_int)
        self.toggle_wp_pause_mute.setChecked(True)
        self.toggle_wp_pause_mute.toggled.connect(lambda c: self._set_cfg("pause_on_pause", c))
        i_l.addLayout(self._create_studio_control_row("Pause on Music Pause", "Halt rotation when playback stops.", self.toggle_wp_pause_mute))

        self.toggle_wp_battery = ToggleSwitch("", wp_tab_int)
        self.toggle_wp_battery.setChecked(True)
        self.toggle_wp_battery.toggled.connect(lambda c: self._set_cfg("pause_on_battery", c))
        i_l.addLayout(self._create_studio_control_row("Battery Saver", "Halt animation when on DC battery.", self.toggle_wp_battery))
        self.wp_subtab_stack.addWidget(wp_tab_int)

        wp_h_layout.addWidget(self.wp_subtab_stack)
        self.overview_studio_stack.addWidget(self.wp_hub)

        # === 2. Visualizer Hub ===
        self.vis_hub = QWidget()
        vis_h_layout = QVBoxLayout(self.vis_hub)
        vis_h_layout.setContentsMargins(0, 0, 0, 0)
        vis_h_layout.setSpacing(8)

        # Header
        vis_header = QHBoxLayout()
        vis_title_layout = QVBoxLayout()
        vis_title_layout.setSpacing(1)

        lbl_vis_title = QLabel("Audio Visualizer", self.vis_hub)
        lbl_vis_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #FFFFFF;")
        vis_title_layout.addWidget(lbl_vis_title)

        lbl_vis_sub = QLabel("Hardware accelerated 60 FPS spectrum analyzer.", self.vis_hub)
        lbl_vis_sub.setStyleSheet("font-size: 11px; color: #8A8D9B;")
        vis_title_layout.addWidget(lbl_vis_sub)
        vis_header.addLayout(vis_title_layout, 1)

        self.toggle_vis_enable = ToggleSwitch("", self.vis_hub)
        self.toggle_vis_enable.setChecked(True)
        self.toggle_vis_enable.toggled.connect(self._on_toggle_visualizer)
        vis_header.addWidget(self.toggle_vis_enable)
        vis_h_layout.addLayout(vis_header)

        # Live 60 FPS spectrum canvas
        self.vis_preview = VisualizerPreviewWidget(self.vis_hub)
        vis_h_layout.addWidget(self.vis_preview)

        # Sub Tabs
        self.subtabs_vis = SubTabRow(["STYLE", "BARS", "GRADIENT", "DYNAMICS", "OVERLAY"], self.vis_hub)
        self.subtabs_vis.tabSelected.connect(self._on_vis_subtab_selected)
        vis_h_layout.addWidget(self.subtabs_vis)

        # Subtab Control Stack
        self.vis_subtab_stack = QStackedWidget(self.vis_hub)

        # Tab 0: STYLE
        vis_tab_style = QWidget()
        vt_s_l = QVBoxLayout(vis_tab_style)
        vt_s_l.setContentsMargins(0, 4, 0, 0)
        vt_s_l.setSpacing(6)

        self.combo_vis_style = QComboBox(vis_tab_style)
        self.combo_vis_style.addItems(["Pill Bars", "Standard Bars", "Rounded Tops"])
        self.combo_vis_style.currentIndexChanged.connect(lambda idx: self._set_cfg("visualizer_style", ["pill", "bars", "rounded"][idx]))
        vt_s_l.addLayout(self._create_studio_control_row("Bar Shape", "Visual styling of spectrum bars.", self.combo_vis_style))

        self.slider_vis_radius = ValueSlider(0, 16, 6, "px", vis_tab_style)
        self.slider_vis_radius.valueChanged.connect(lambda v: self._set_cfg("visualizer_bar_corner_radius", v))
        vt_s_l.addLayout(self._create_studio_control_row("Corner Radius", "Roundness of the bar edges.", self.slider_vis_radius))
        self.vis_subtab_stack.addWidget(vis_tab_style)

        # Tab 1: BARS
        vis_tab_bars = QWidget()
        vt_b_l = QVBoxLayout(vis_tab_bars)
        vt_b_l.setContentsMargins(0, 4, 0, 0)
        vt_b_l.setSpacing(6)

        self.slider_vis_width = ValueSlider(2, 24, 6, "px", vis_tab_bars)
        self.slider_vis_width.valueChanged.connect(lambda v: self._set_cfg("visualizer_bar_width", v))
        vt_b_l.addLayout(self._create_studio_control_row("Bar Width", "Width of each spectrum band.", self.slider_vis_width))

        self.slider_vis_spacing = ValueSlider(1, 16, 3, "px", vis_tab_bars)
        self.slider_vis_spacing.valueChanged.connect(lambda v: self._set_cfg("visualizer_bar_spacing", v))
        vt_b_l.addLayout(self._create_studio_control_row("Bar Spacing", "Gap between adjacent bars.", self.slider_vis_spacing))

        self.slider_vis_max_h = ValueSlider(20, 200, 80, "px", vis_tab_bars)
        self.slider_vis_max_h.valueChanged.connect(lambda v: self._set_cfg("visualizer_max_bar_height", v))
        vt_b_l.addLayout(self._create_studio_control_row("Max Height", "Maximum height of spectrum peaks.", self.slider_vis_max_h))
        self.vis_subtab_stack.addWidget(vis_tab_bars)

        # Tab 2: GRADIENT
        vis_tab_grad = QWidget()
        vt_g_l = QVBoxLayout(vis_tab_grad)
        vt_g_l.setContentsMargins(0, 4, 0, 0)
        vt_g_l.setSpacing(6)

        self.grad_preview_strip = GradientPreviewBar(vis_tab_grad)
        vt_g_l.addWidget(self.grad_preview_strip)

        self.combo_grad_preset = QComboBox(vis_tab_grad)
        self.combo_grad_preset.addItems(["Spotify Glow", "Sunset Neon", "Cyber Violet", "Electric Fire"])
        self.combo_grad_preset.currentIndexChanged.connect(self._on_grad_preset_changed)
        vt_g_l.addLayout(self._create_studio_control_row("Gradient Preset", "Curated color harmony.", self.combo_grad_preset))
        self.vis_subtab_stack.addWidget(vis_tab_grad)

        # Tab 3: DYNAMICS
        vis_tab_dyn = QWidget()
        vt_d_l = QVBoxLayout(vis_tab_dyn)
        vt_d_l.setContentsMargins(0, 4, 0, 0)
        vt_d_l.setSpacing(6)

        self.slider_vis_sens = ValueSlider(10, 200, 100, "%", vis_tab_dyn)
        self.slider_vis_sens.valueChanged.connect(lambda v: self._set_cfg("visualizer_sensitivity", v / 100.0))
        vt_d_l.addLayout(self._create_studio_control_row("Sensitivity", "Audio peak responsiveness.", self.slider_vis_sens))

        self.slider_vis_smooth = ValueSlider(10, 95, 65, "%", vis_tab_dyn)
        self.slider_vis_smooth.valueChanged.connect(lambda v: self._set_cfg("visualizer_smoothing", v / 100.0))
        vt_d_l.addLayout(self._create_studio_control_row("Smoothing", "Time-decay smoothness.", self.slider_vis_smooth))
        self.vis_subtab_stack.addWidget(vis_tab_dyn)

        # Tab 4: OVERLAY
        vis_tab_ov = QWidget()
        vt_o_l = QVBoxLayout(vis_tab_ov)
        vt_o_l.setContentsMargins(0, 4, 0, 0)
        vt_o_l.setSpacing(6)

        self.combo_vis_place = QComboBox(vis_tab_ov)
        self.combo_vis_place.addItems(["Bottom Screen", "Top Screen", "Overlay Center"])
        self.combo_vis_place.currentIndexChanged.connect(lambda idx: self._set_cfg("visualizer_placement", ["bottom", "top", "center"][idx]))
        vt_o_l.addLayout(self._create_studio_control_row("Placement", "Desktop screen placement.", self.combo_vis_place))

        self.toggle_vis_clickthru = ToggleSwitch("", vis_tab_ov)
        self.toggle_vis_clickthru.setChecked(True)
        self.toggle_vis_clickthru.toggled.connect(lambda c: self._set_cfg("visualizer_click_through", c))
        vt_o_l.addLayout(self._create_studio_control_row("Click-Through", "Clicks pass to desktop behind.", self.toggle_vis_clickthru))
        self.vis_subtab_stack.addWidget(vis_tab_ov)

        vis_h_layout.addWidget(self.vis_subtab_stack)
        self.overview_studio_stack.addWidget(self.vis_hub)

        r_layout.addWidget(self.overview_studio_stack, 1)
        page_layout.addWidget(self.right_studio_card, 5)

        self.content_stack.addWidget(self.overview_page)

    def _create_studio_control_row(self, title: str, subtitle: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(12)

        info_l = QVBoxLayout()
        info_l.setSpacing(1)
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("font-size: 12px; font-weight: 700; color: #FFFFFF;")
        info_l.addWidget(lbl_t)

        lbl_s = QLabel(subtitle)
        lbl_s.setStyleSheet("font-size: 10px; color: #8A8D9B;")
        info_l.addWidget(lbl_s)
        row.addLayout(info_l, 1)

        row.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return row

    def _on_studio_switch(self, index: int):
        self.overview_studio_stack.setCurrentIndex(index)

    def _on_wp_subtab_selected(self, index: int):
        self.wp_subtab_stack.setCurrentIndex(index)

    def _on_vis_subtab_selected(self, index: int):
        self.vis_subtab_stack.setCurrentIndex(index)

    # ==============================================================================
    # PAGE 1: APPEARANCE
    # ==============================================================================

    def _build_appearance_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        lbl_title = QLabel("Appearance", page)
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(lbl_title)

        card = GlassCard(radius=16, parent=page)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(16, 16, 16, 16)
        c_layout.setSpacing(12)

        self.swatch_text_c = ColorSwatchButton("#FFFFFF", card)
        self.swatch_text_c.colorChanged.connect(lambda c: self._set_cfg("text_color", c))
        c_layout.addLayout(self._create_studio_control_row("Text Color", "Default text color for lyrics.", self.swatch_text_c))

        self.swatch_active_c = ColorSwatchButton("#2ED573", card)
        self.swatch_active_c.colorChanged.connect(lambda c: self._set_cfg("active_color", c))
        c_layout.addLayout(self._create_studio_control_row("Active Highlight", "Color of the currently singing lyric line.", self.swatch_active_c))

        self.swatch_progress_c = ColorSwatchButton("#1DB954", card)
        self.swatch_progress_c.colorChanged.connect(lambda c: self._set_cfg("progress_fill_color", c))
        c_layout.addLayout(self._create_studio_control_row("Progress Fill", "Fill color for word-level karaoke sync.", self.swatch_progress_c))

        self.slider_bg_opacity = ValueSlider(0, 100, 30, "%", card)
        self.slider_bg_opacity.valueChanged.connect(lambda v: self._set_cfg("background_opacity", v))
        c_layout.addLayout(self._create_studio_control_row("Background Opacity", "Translucency of lyrics overlay card.", self.slider_bg_opacity))

        self.slider_blur = ValueSlider(0, 48, 20, "px", card)
        self.slider_blur.valueChanged.connect(lambda v: self._set_cfg("blur_radius", v))
        c_layout.addLayout(self._create_studio_control_row("Backdrop Blur", "Gaussian glass blur intensity.", self.slider_blur))

        layout.addWidget(card)
        layout.addStretch(1)
        self.content_stack.addWidget(page)

    # ==============================================================================
    # PAGE 2: TYPOGRAPHY
    # ==============================================================================

    def _build_typography_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        lbl_title = QLabel("Typography", page)
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(lbl_title)

        card = GlassCard(radius=16, parent=page)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(16, 16, 16, 16)
        c_layout.setSpacing(12)

        self.font_combo = QFontComboBox(card)
        self.font_combo.currentFontChanged.connect(lambda f: self._set_cfg("font_family", f.family()))
        c_layout.addLayout(self._create_studio_control_row("Font Family", "Primary font for lyrics display.", self.font_combo))

        self.slider_font_size = ValueSlider(12, 64, 28, "pt", card)
        self.slider_font_size.valueChanged.connect(lambda v: self._set_cfg("font_size", v))
        c_layout.addLayout(self._create_studio_control_row("Font Size", "Base font size for active line.", self.slider_font_size))

        self.slider_active_scale = ValueSlider(100, 160, 115, "%", card)
        self.slider_active_scale.valueChanged.connect(lambda v: self._set_cfg("active_line_scale", v / 100.0))
        c_layout.addLayout(self._create_studio_control_row("Active Line Scale", "Enlargement ratio for current line.", self.slider_active_scale))

        self.combo_align = QComboBox(card)
        self.combo_align.addItems(["Left", "Center", "Right"])
        self.combo_align.currentIndexChanged.connect(lambda idx: self._set_cfg("text_alignment", ["Left", "Center", "Right"][idx]))
        c_layout.addLayout(self._create_studio_control_row("Text Alignment", "Horizontal alignment of lyrics.", self.combo_align))

        layout.addWidget(card)
        layout.addStretch(1)
        self.content_stack.addWidget(page)

    # ==============================================================================
    # PAGE 3: FULL DEDICATED WALLPAPER STUDIO
    # ==============================================================================

    def _build_wallpaper_studio_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        lbl_title = QLabel("Wallpaper Studio", page)
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(lbl_title)

        # Large Full-Width Interactive Canvas
        self.full_wp_preview = WallpaperPreviewWidget(page)
        self.full_wp_preview.setFixedHeight(220)
        self.full_wp_preview.vinyl_position_changed.connect(self._on_vinyl_preview_moved)
        self.full_wp_preview.vinyl_size_changed.connect(self._on_vinyl_preview_resized)
        layout.addWidget(self.full_wp_preview)

        # Full Controls Glass Card
        card = GlassCard(radius=16, parent=page)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(16, 14, 16, 14)
        c_layout.setSpacing(10)

        # Wallpaper Source File Row
        src_row = QHBoxLayout()
        self.txt_wp_path = QLineEdit(card)
        self.txt_wp_path.setPlaceholderText("Select video (.mp4, .webm) or image (.png, .jpg)...")
        src_row.addWidget(self.txt_wp_path, 1)

        btn_browse = QPushButton("Browse...", card)
        btn_browse.setFixedHeight(30)
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.setStyleSheet("""
            QPushButton { background: rgba(30,35,46,0.78); color: #FFFFFF; border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; padding: 0 12px; }
            QPushButton:hover { background: rgba(46,54,76,0.90); border-color: #2ED573; }
        """)
        btn_browse.clicked.connect(self._browse_wallpaper)
        src_row.addWidget(btn_browse)
        c_layout.addLayout(self._create_studio_control_row("Wallpaper Source", "Image or video file path.", QWidget()))
        c_layout.addLayout(src_row)

        self.combo_wp_monitor = QComboBox(card)
        for opt in get_wallpaper_display_options():
            self.combo_wp_monitor.addItem(str(opt))
        self.combo_wp_monitor.currentTextChanged.connect(lambda txt: self._set_cfg("wallpaper_display_mode", txt))
        c_layout.addLayout(self._create_studio_control_row("Target Display", "Monitor where wallpaper is rendered.", self.combo_wp_monitor))

        self.combo_wp_scale = QComboBox(card)
        self.combo_wp_scale.addItems(["Fill (Crop to Aspect)", "Fit (Letterbox)", "Stretch (Full Screen)", "Center"])
        self.combo_wp_scale.currentIndexChanged.connect(lambda idx: self._set_cfg("scaling_mode", ["fill", "fit", "stretch", "center"][idx]))
        c_layout.addLayout(self._create_studio_control_row("Scaling Mode", "Aspect ratio handling mode.", self.combo_wp_scale))

        layout.addWidget(card)
        layout.addStretch(1)
        self.content_stack.addWidget(page)

    # ==============================================================================
    # PAGE 4: FULL DEDICATED VISUALIZER STUDIO
    # ==============================================================================

    def _build_visualizer_studio_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        lbl_title = QLabel("Visualizer Studio", page)
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(lbl_title)

        # Large Visualizer Spectrum Canvas
        self.full_vis_preview = VisualizerPreviewWidget(page)
        self.full_vis_preview.setFixedHeight(180)
        layout.addWidget(self.full_vis_preview)

        # Full Controls Glass Card
        card = GlassCard(radius=16, parent=page)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(16, 14, 16, 14)
        c_layout.setSpacing(10)

        self.combo_vis_orient = QComboBox(card)
        self.combo_vis_orient.addItems(["Bottom (Upward)", "Top (Downward)", "Center (Dual-Sided)"])
        self.combo_vis_orient.currentIndexChanged.connect(lambda idx: self._set_cfg("visualizer_orientation", ["BOTTOM", "TOP", "CENTER"][idx]))
        c_layout.addLayout(self._create_studio_control_row("Orientation", "Direction spectrum bars grow.", self.combo_vis_orient))

        self.slider_vis_bars = ValueSlider(16, 128, 64, " bars", card)
        self.slider_vis_bars.valueChanged.connect(lambda v: self._set_cfg("visualizer_bar_count", v))
        c_layout.addLayout(self._create_studio_control_row("Bar Count", "Total frequency bins to render.", self.slider_vis_bars))

        self.toggle_vis_game = ToggleSwitch("", card)
        self.toggle_vis_game.setChecked(True)
        self.toggle_vis_game.toggled.connect(lambda c: self._set_cfg("visualizer_exclude_from_capture", c))
        c_layout.addLayout(self._create_studio_control_row("Capture Exclusion", "Hide visualizer from OBS / Discord stream.", self.toggle_vis_game))

        layout.addWidget(card)
        layout.addStretch(1)
        self.content_stack.addWidget(page)

    # ==============================================================================
    # PAGE 5: BEHAVIOR
    # ==============================================================================

    def _build_behavior_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        lbl_title = QLabel("Behavior", page)
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(lbl_title)

        card = GlassCard(radius=16, parent=page)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(16, 16, 16, 16)
        c_layout.setSpacing(12)

        self.combo_media_src = QComboBox(card)
        self.combo_media_src.addItems(["Auto Detect (Spotify / Windows Media)", "Spotify Desktop App Only", "Windows Media API Only"])
        self.combo_media_src.currentIndexChanged.connect(lambda idx: self._set_cfg("preferred_media_source", ["auto", "spotify", "windows_media"][idx]))
        c_layout.addLayout(self._create_studio_control_row("Media Source", "Active music source query engine.", self.combo_media_src))

        self.toggle_click_thru = ToggleSwitch("", card)
        self.toggle_click_thru.setChecked(False)
        self.toggle_click_thru.toggled.connect(lambda c: self._set_cfg("click_through", c))
        c_layout.addLayout(self._create_studio_control_row("Click-Through Overlay", "Pass mouse clicks to apps beneath lyrics.", self.toggle_click_thru))

        self.toggle_auto_hide = ToggleSwitch("", card)
        self.toggle_auto_hide.setChecked(True)
        self.toggle_auto_hide.toggled.connect(lambda c: self._set_cfg("auto_hide_on_pause", c))
        c_layout.addLayout(self._create_studio_control_row("Auto-Hide on Pause", "Hide lyrics overlay when playback pauses.", self.toggle_auto_hide))

        self.toggle_start_boot = ToggleSwitch("", card)
        self.toggle_start_boot.setChecked(False)
        self.toggle_start_boot.toggled.connect(lambda c: self._set_cfg("start_with_windows", c))
        c_layout.addLayout(self._create_studio_control_row("Start with Windows", "Launch Lyrune on system startup.", self.toggle_start_boot))

        layout.addWidget(card)
        layout.addStretch(1)
        self.content_stack.addWidget(page)

    # ==============================================================================
    # PAGE 6: SHORTCUTS
    # ==============================================================================

    def _build_shortcuts_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        lbl_title = QLabel("Keyboard Shortcuts", page)
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(lbl_title)

        card = GlassCard(radius=16, parent=page)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(16, 16, 16, 16)
        c_layout.setSpacing(12)

        shortcuts = [
            ("Toggle Lyrics Overlay", "Show or hide the desktop lyrics overlay.", "Ctrl+H"),
            ("Open Settings Studio", "Open the Lyrune settings studio dialog.", "Ctrl+,"),
            ("Refresh Lyrics", "Force re-fetch lyrics from LRCLib API.", "Ctrl+R"),
            ("Toggle Wallpaper", "Enable or disable desktop live wallpaper.", "Ctrl+W"),
            ("Toggle Visualizer", "Enable or disable audio reactive visualizer.", "Ctrl+V"),
        ]
        for name, desc, key in shortcuts:
            keycap = KeycapWidget(key, card)
            c_layout.addLayout(self._create_studio_control_row(name, desc, keycap))

        layout.addWidget(card)
        layout.addStretch(1)
        self.content_stack.addWidget(page)

    # ==============================================================================
    # PAGE 7: ADVANCED & LOGS
    # ==============================================================================

    def _build_advanced_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        lbl_title = QLabel("Advanced & Diagnostics", page)
        lbl_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(lbl_title)

        card = GlassCard(radius=16, parent=page)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(16, 14, 16, 14)
        c_layout.setSpacing(10)

        # Clear Cache Button
        btn_cache = QPushButton("Clear Cache", card)
        btn_cache.setFixedHeight(30)
        btn_cache.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cache.setStyleSheet("""
            QPushButton { background: rgba(30,35,46,0.78); color: #FFFFFF; border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; padding: 0 12px; }
            QPushButton:hover { background: rgba(255,71,87,0.35); border-color: #FF4757; color: #FF4757; }
        """)
        btn_cache.clicked.connect(self._clear_cache_action)
        c_layout.addLayout(self._create_studio_control_row("Clear Lyrics & Art Cache", "Free cached lyrics and artwork files on disk.", btn_cache))

        # Live Logs Console
        lbl_log = QLabel("System Log History", card)
        lbl_log.setStyleSheet("font-size: 12px; font-weight: 700; color: #FFFFFF; margin-top: 6px;")
        c_layout.addWidget(lbl_log)

        self.txt_logs = QTextEdit(card)
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setFixedHeight(180)
        self.txt_logs.setStyleSheet("""
            QTextEdit {
                background: #0D101A;
                color: #A0A5B8;
                font-family: 'Consolas', 'Cascadia Code', monospace;
                font-size: 11px;
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 8px;
                padding: 6px;
            }
        """)
        c_layout.addWidget(self.txt_logs)

        layout.addWidget(card)
        layout.addStretch(1)
        self.content_stack.addWidget(page)

    # === Live Media Sync & Dynamic Island Integration ===

    def _sync_media_loop(self):
        if not self.player:
            return
        try:
            info = None
            if hasattr(self.player, "get_playback_info"):
                info = self.player.get_playback_info()
            elif hasattr(self.player, "get_current_track_info"):
                info = self.player.get_current_track_info()

            if not info:
                return

            title = info.get("title", "")
            artist = info.get("artist", "")
            is_playing = info.get("is_playing", True)
            position = info.get("position", 0.0)
            duration = info.get("duration", 0.0)
            art_pixmap = info.get("album_art", None)

            if title and title != self.lbl_hero_title.text():
                self.lbl_hero_title.setText(title)
                self.lbl_hero_artist.setText(artist or "Unknown Artist")
                self._ambient_accent = extract_dominant_accent(art_pixmap)

                if art_pixmap and not art_pixmap.isNull():
                    self._current_pixmap = art_pixmap
                    self.lbl_hero_art.setPixmap(art_pixmap)

                self.title_bar.dynamic_island.update_media(title, artist, art_pixmap, is_playing)

                # Update wallpaper preview
                media_snap = MediaSnapshot(
                    track_id=f"{artist} - {title}",
                    title=title,
                    artist=artist,
                    album_art=art_pixmap,
                    is_playing=is_playing,
                    position=position,
                    duration=duration
                )
                self.wallpaper_preview.set_media(media_snap)
                self.full_wp_preview.set_media(media_snap)
                self.update()

            # Scrubber update
            if duration > 0:
                pct = int((position / duration) * 100)
                self.hero_progress.setValue(max(0, min(100, pct)))
                cur_m, cur_s = divmod(int(position), 60)
                tot_m, tot_s = divmod(int(duration), 60)
                self.lbl_scrub_cur.setText(f"{cur_m}:{cur_s:02d}")
                self.lbl_scrub_tot.setText(f"{tot_m}:{tot_s:02d}")

        except Exception as e:
            pass

    def _transport_play_pause(self):
        if self.player and hasattr(self.player, "play_pause"):
            self.player.play_pause()

    def _transport_prev(self):
        if self.player and hasattr(self.player, "previous_track"):
            self.player.previous_track()

    def _transport_next(self):
        if self.player and hasattr(self.player, "next_track"):
            self.player.next_track()

    # === Interaction Callbacks ===

    def _on_toggle_wallpaper(self, checked: bool):
        self._set_cfg("enable_wallpaper", checked)
        self.bento_wallpaper.set_status(checked, "Aurora landscape set as wallpaper" if checked else "Wallpaper engine disabled")

    def _on_toggle_visualizer(self, checked: bool):
        self._set_cfg("visualizer_enabled", checked)
        self.bento_visualizer.set_status(checked, "Audio reactive spectrum active" if checked else "Visualizer disabled")

    def _on_vinyl_preview_moved(self, norm_x: float, norm_y: float):
        self._set_cfg("vinyl_x", norm_x)
        self._set_cfg("vinyl_y", norm_y)
        self.full_wp_preview.update_vinyl_position(norm_x, norm_y)

    def _on_vinyl_preview_resized(self, norm_size: float):
        self._set_cfg("vinyl_size", norm_size)
        self.slider_vinyl_size.setValue(int(norm_size * 100))
        self.full_wp_preview.update_vinyl_size(norm_size)

    def _on_vinyl_size_slider(self, val: int):
        norm = val / 100.0
        self._set_cfg("vinyl_size", norm)
        self.wallpaper_preview.update_vinyl_size(norm)
        self.full_wp_preview.update_vinyl_size(norm)

    def _on_grad_preset_changed(self, idx: int):
        presets = [
            [{"position": 0.0, "color": "#2ED573", "opacity": 0.9}, {"position": 1.0, "color": "#1DB954", "opacity": 0.4}],
            [{"position": 0.0, "color": "#FF4757", "opacity": 0.9}, {"position": 1.0, "color": "#FFA502", "opacity": 0.4}],
            [{"position": 0.0, "color": "#9B51E0", "opacity": 0.9}, {"position": 1.0, "color": "#00D2D3", "opacity": 0.4}],
            [{"position": 0.0, "color": "#FF6B81", "opacity": 0.9}, {"position": 1.0, "color": "#FF4757", "opacity": 0.4}],
        ]
        if 0 <= idx < len(presets):
            self.grad_preview_strip.set_stops(presets[idx])
            self._set_cfg("visualizer_gradient_stops", presets[idx])

    def _browse_wallpaper(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Select Wallpaper Source", "",
            "Media Files (*.mp4 *.webm *.png *.jpg *.jpeg *.bmp);;All Files (*.*)"
        )
        if fpath:
            self.txt_wp_path.setText(fpath)
            self._set_cfg("wallpaper_path", fpath)
            self.wallpaper_preview.set_background(fpath, self.working_settings.get("scaling_mode", "fill"))
            self.full_wp_preview.set_background(fpath, self.working_settings.get("scaling_mode", "fill"))

    def _refresh_lyrics_action(self):
        if self.player and hasattr(self.player, "force_refresh_lyrics"):
            self.player.force_refresh_lyrics()
        self.lbl_footer_status.setText("Lyrics refresh requested.")

    def _clear_cache_action(self):
        try:
            cache_dir = os.path.join(os.path.dirname(__file__), ".lyrics_cache")
            if os.path.exists(cache_dir):
                for f in os.listdir(cache_dir):
                    p = os.path.join(cache_dir, f)
                    if os.path.isfile(p):
                        os.remove(p)
            self.lbl_footer_status.setText("Cache cleared successfully.")
        except Exception as e:
            self.lbl_footer_status.setText(f"Error clearing cache: {e}")

    def _append_log_entry(self, msg: str):
        if hasattr(self, "txt_logs"):
            self.txt_logs.append(msg)

    def _load_log_history(self):
        try:
            history = AppLogger.instance().get_history()
            if hasattr(self, "txt_logs"):
                self.txt_logs.setPlainText("\n".join(history))
        except Exception:
            pass

    def _reset_to_defaults(self):
        self.working_settings = dict(self.settings_manager.default_settings)
        self._load_current_values()
        self.lbl_footer_status.setText("Settings reset to defaults.")

    def _set_cfg(self, key: str, value: Any):
        if self._is_initializing:
            return
        self.working_settings[key] = value
        self._update_preview()

    def _update_preview(self):
        if hasattr(self, "vis_preview"):
            self.vis_preview.update_style(self.working_settings)
        if hasattr(self, "full_vis_preview"):
            self.full_vis_preview.update_style(self.working_settings)

    def _load_current_values(self):
        # Apply working_settings to all widgets
        cfg = self.working_settings
        wp_cfg = WallpaperConfig(
            enabled=cfg.get("enable_wallpaper", True),
            wallpaper_path=cfg.get("wallpaper_path", ""),
            scaling_mode=cfg.get("scaling_mode", "fill"),
            vinyl_x=cfg.get("vinyl_x", 0.88),
            vinyl_y=cfg.get("vinyl_y", 0.50),
            vinyl_size=cfg.get("vinyl_size", 0.44),
            vinyl_opacity=cfg.get("vinyl_opacity", 100),
            rotation_speed=cfg.get("rotation_speed", 12.0),
            rotate_while_playing=cfg.get("rotate_while_playing", True)
        )
        self.wallpaper_preview.set_config(wp_cfg)
        self.full_wp_preview.set_config(wp_cfg)

        if wp_cfg.wallpaper_path:
            self.wallpaper_preview.set_background(wp_cfg.wallpaper_path, wp_cfg.scaling_mode)
            self.full_wp_preview.set_background(wp_cfg.wallpaper_path, wp_cfg.scaling_mode)

    def _on_apply(self):
        self.settings_manager.update(self.working_settings)
        self.settings_manager.save()
        self.settings_changed.emit(self.working_settings)
        self.lbl_footer_status.setText("Settings applied.")

    def _on_ok(self):
        self._on_apply()
        self.accept()

    def _refresh_media_sources(self):
        pass
