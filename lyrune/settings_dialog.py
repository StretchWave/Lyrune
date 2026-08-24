"""
settings_dialog.py — Modern Translucent Cinematic Glass Desktop Studio for Lyrune.

Full 11-page information architecture, real bi-directional state binding, command palette (Ctrl+K),
manual lyrics correction modal, Wallpaper/Visualizer studio live previews, and diagnostics exporter.
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
    QLinearGradient, QRadialGradient, QPixmap, QCursor, QPainterPath, QFontMetrics, QShortcut
)
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QPushButton, QComboBox, QFontComboBox, QTextEdit, QCheckBox,
    QListWidget, QListWidgetItem, QStackedWidget, QScrollArea, QFrame,
    QApplication, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QSizePolicy, QToolButton, QSlider, QMessageBox
)

from lyrune.ui_theme import (
    PALETTE, DARK_THEME_STYLESHEET, MENU_STYLESHEET, get_icon, get_app_icon,
    extract_dominant_accent, paint_atmospheric_background, GlassCard, BentoCard, BentoStatusCard,
    DynamicIslandBar, SegmentedSwitch, SubTabRow, ToggleSwitch, ValueSlider,
    ColorSwatchButton, KeycapWidget, CommandPaletteDialog, ManualLyricSearchDialog,
    MetricGaugeCard, GlassButton
)
from lyrune.settings_manager import SettingsManager, DEFAULT_SETTINGS, PRESETS
from lyrune.logger import event_logger, log_event
from lyrune.animation_engine import LyricsRenderer
from lyrune.lrclib_client import LRCLibClient
from lyrune.visualizer import BarVisualizer, AudioData
from lyrune.window_utils import get_available_screen_options, enable_acrylic_blur
from lyrune.wallpaper.preview_widget import WallpaperPreviewWidget
from lyrune.wallpaper.model import WallpaperConfig, MediaSnapshot
from lyrune.wallpaper.monitor import get_wallpaper_display_options
from lyrune.shortcuts import SHORTCUT_DEFINITIONS, find_shortcut_conflicts, normalize_shortcut_key
from lyrune.diagnostics import get_subsystem_health, generate_full_diagnostics_report


class VisualizerPreviewWidget(QWidget):
    """
    Live interactive preview canvas for the visualizer inside SettingsDialog.
    Supports DEMO mode (simulated frequencies) and LIVE AUDIO mode (WASAPI loopback).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(140)
        self.setMinimumWidth(280)
        self.renderer = BarVisualizer()
        self.renderer.set_orientation("BOTTOM")
        self._mode = "Demo"
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)  # 60 FPS
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def set_preview_mode(self, mode: str):
        self._mode = mode

    def update_style(self, settings_dict: Dict[str, Any]):
        self.renderer.set_style(settings_dict)
        self.update()

    def feed_live_audio(self, audio_data: AudioData):
        if self._mode == "Live Audio":
            self.renderer.update_audio(audio_data)
            self.update()

    def _on_tick(self):
        if not self.isVisible() or self._mode != "Demo":
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


class CustomTitleBar(QWidget):
    """
    Modern glass title bar with logo, Dynamic Island media pill, and window controls.
    """
    minimizeClicked = pyqtSignal()
    maximizeClicked = pyqtSignal()
    closeClicked = pyqtSignal()
    commandPaletteClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 6, 18, 6)
        layout.setSpacing(12)

        # Left: App Logo
        lbl_logo = QLabel(self)
        lbl_logo.setPixmap(get_app_icon().pixmap(20, 20))
        lbl_brand = QLabel("LYRUNE", self)
        lbl_brand.setStyleSheet("font-weight: 800; font-size: 13px; letter-spacing: 1.5px; color: #FFFFFF;")

        layout.addWidget(lbl_logo)
        layout.addWidget(lbl_brand)
        layout.addSpacing(16)

        # Center: Dynamic Island Media Pill
        self.dynamic_island = DynamicIslandBar(self)
        layout.addWidget(self.dynamic_island, 1)

        # Right: Omnibox Trigger + Window Actions
        self.btn_cmd = QPushButton(" 🔍 Search (Ctrl+K) ", self)
        self.btn_cmd.setFixedHeight(28)
        self.btn_cmd.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cmd.setStyleSheet("""
            QPushButton {
                background: rgba(30, 35, 46, 0.65);
                color: #8A8D9B;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 7px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 8px;
            }
            QPushButton:hover {
                color: #FFFFFF;
                border-color: #2ED573;
            }
        """)
        self.btn_cmd.clicked.connect(self.commandPaletteClicked.emit)
        layout.addWidget(self.btn_cmd)

        self.btn_min = QPushButton(self)
        self.btn_min.setIcon(get_icon("minimize", "#C5C8D4", 12))
        self.btn_min.setFixedSize(28, 28)
        self.btn_min.setStyleSheet("background: transparent; border: none; border-radius: 6px;")
        self.btn_min.clicked.connect(self.minimizeClicked.emit)

        self.btn_max = QPushButton(self)
        self.btn_max.setIcon(get_icon("maximize", "#C5C8D4", 12))
        self.btn_max.setFixedSize(28, 28)
        self.btn_max.setStyleSheet("background: transparent; border: none; border-radius: 6px;")
        self.btn_max.clicked.connect(self.maximizeClicked.emit)

        self.btn_close = QPushButton(self)
        self.btn_close.setIcon(get_icon("close", "#C5C8D4", 12))
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setStyleSheet("background: transparent; border: none; border-radius: 6px;")
        self.btn_close.clicked.connect(self.closeClicked.emit)

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

    def set_maximized_state(self, is_max: bool):
        icon_name = "restore" if is_max else "maximize"
        self.btn_max.setIcon(get_icon(icon_name, "#C5C8D4", 12))


class SettingsDialog(QDialog):
    """
    Lyrune Studio Desktop Master Window.
    Full 11-page information architecture with bi-directional bindings and transaction semantics.
    """
    settings_changed = pyqtSignal(dict)

    def __init__(self, settings_manager: SettingsManager, player=None, parent=None):
        super().__init__(parent)
        self.settings_mgr = settings_manager
        self.player = player
        self.lyrics_client = LRCLibClient()

        # Working settings transaction state
        self.saved_settings: Dict[str, Any] = dict(self.settings_mgr.settings)
        self.working_settings: Dict[str, Any] = dict(self.saved_settings)
        self._undo_stack: List[Dict[str, Any]] = [dict(self.working_settings)]
        self._redo_stack: List[Dict[str, Any]] = []

        self._ambient_accent: Optional[QColor] = None
        self._is_maximized_custom: bool = False
        self._pre_max_geometry: Optional[QRect] = None

        # Frameless edge resizing
        self._resize_edge: Optional[str] = None
        self._resize_drag_start: Optional[QPoint] = None
        self._resize_start_geometry: Optional[QRect] = None
        self.setMouseTracking(True)

        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowMinMaxButtonsHint |
            Qt.WindowType.WindowSystemMenuHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(DARK_THEME_STYLESHEET)
        self.setMinimumSize(960, 680)
        self.resize(1080, 740)

        self._init_ui()
        self._setup_shortcuts()
        self._connect_player_signals()
        self._load_working_settings_to_ui()

    # === Window Management & Frameless Sizing ===

    def showEvent(self, event):
        super().showEvent(event)
        try:
            enable_acrylic_blur(int(self.winId()))
        except Exception:
            pass

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # 1. Atmospheric translucent cosmic nebula
        paint_atmospheric_background(painter, rect, self._ambient_accent)

        # 2. Translucent glass shell
        painter.setBrush(QBrush(QColor(15, 18, 25, 130)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 20, 20)

        # 3. Outer window border
        painter.setPen(QPen(QColor(255, 255, 255, 24), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 20, 20)

        # Specular line
        painter.setPen(QPen(QColor(255, 255, 255, 16), 1))
        painter.drawLine(QPointF(rect.left() + 20, rect.top()), QPointF(rect.right() - 20, rect.top()))

    def _determine_edge(self, pos: QPoint) -> Optional[str]:
        if self._is_maximized_custom:
            return None
        margin = 6
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()

        on_left = x <= margin
        on_right = x >= w - margin
        on_top = y <= margin
        on_bottom = y >= h - margin

        if on_top and on_left: return "top_left"
        if on_top and on_right: return "top_right"
        if on_bottom and on_left: return "bottom_left"
        if on_bottom and on_right: return "bottom_right"
        if on_left: return "left"
        if on_right: return "right"
        if on_top: return "top"
        if on_bottom: return "bottom"
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
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._resize_edge and self._resize_drag_start and self._resize_start_geometry:
            delta = event.globalPosition().toPoint() - self._resize_drag_start
            g = QRect(self._resize_start_geometry)
            edge = self._resize_edge

            if "left" in edge:
                new_w = max(self.minimumWidth(), g.width() - delta.x())
                g.setLeft(g.right() - new_w)
            elif "right" in edge:
                g.setWidth(max(self.minimumWidth(), g.width() + delta.x()))

            if "top" in edge:
                new_h = max(self.minimumHeight(), g.height() - delta.y())
                g.setTop(g.bottom() - new_h)
            elif "bottom" in edge:
                g.setHeight(max(self.minimumHeight(), g.height() + delta.y()))

            self.setGeometry(g)
            event.accept()
            return

        edge = self._determine_edge(event.pos())
        if edge in ("top_left", "bottom_right"): self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in ("top_right", "bottom_left"): self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edge in ("left", "right"): self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in ("top", "bottom"): self.setCursor(Qt.CursorShape.SizeVerCursor)
        else: self.setCursor(Qt.CursorShape.ArrowCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._resize_edge = None
        self._resize_drag_start = None
        self._resize_start_geometry = None
        super().mouseReleaseEvent(event)

    def _toggle_maximize_restore(self):
        if self._is_maximized_custom:
            if self._pre_max_geometry:
                self.setGeometry(self._pre_max_geometry)
            self._is_maximized_custom = False
        else:
            self._pre_max_geometry = self.geometry()
            screen = self.screen() or QApplication.primaryScreen()
            if screen:
                self.setGeometry(screen.availableGeometry())
            self._is_maximized_custom = True
        self.title_bar.set_maximized_state(self._is_maximized_custom)

    # === Shortcuts & Transactions ===

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+K"), self, self._open_command_palette)
        QShortcut(QKeySequence("Ctrl+Z"), self, self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self._redo)

    def _record_transaction(self):
        self._undo_stack.append(dict(self.working_settings))
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_unsaved_indicator()

    def _undo(self):
        if len(self._undo_stack) > 1:
            self._redo_stack.append(self._undo_stack.pop())
            self.working_settings = dict(self._undo_stack[-1])
            self._load_working_settings_to_ui()
            self._update_unsaved_indicator()

    def _redo(self):
        if self._redo_stack:
            state = self._redo_stack.pop()
            self._undo_stack.append(state)
            self.working_settings = dict(state)
            self._load_working_settings_to_ui()
            self._update_unsaved_indicator()

    def _update_unsaved_indicator(self):
        has_changes = (self.working_settings != self.saved_settings)
        self.btn_apply.setEnabled(has_changes)
        self.btn_cancel.setEnabled(has_changes)
        if has_changes:
            self.lbl_unsaved.setText("● Unsaved Changes")
            self.lbl_unsaved.setStyleSheet("color: #FF4757; font-size: 11px; font-weight: 700;")
        else:
            self.lbl_unsaved.setText("All changes saved")
            self.lbl_unsaved.setStyleSheet("color: #8A8D9B; font-size: 11px;")

    # === UI Construction ===

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Title bar
        self.title_bar = CustomTitleBar(self)
        self.title_bar.minimizeClicked.connect(self.showMinimized)
        self.title_bar.maximizeClicked.connect(self._toggle_maximize_restore)
        self.title_bar.closeClicked.connect(self.reject)
        self.title_bar.commandPaletteClicked.connect(self._open_command_palette)
        root_layout.addWidget(self.title_bar)

        # 2. Main workspace layout (Sidebar + Stack)
        workspace = QWidget(self)
        ws_layout = QHBoxLayout(workspace)
        ws_layout.setContentsMargins(14, 4, 14, 10)
        ws_layout.setSpacing(14)

        # 2A. Sidebar
        self.sidebar_card = GlassCard(radius=18, elevated=False, parent=workspace)
        self.sidebar_card.setFixedWidth(185)
        sb_layout = QVBoxLayout(self.sidebar_card)
        sb_layout.setContentsMargins(10, 14, 10, 14)
        sb_layout.setSpacing(4)

        # Nav items
        self.nav_items = [
            ("Home", "home", "Overview & live status"),
            ("Media", "music", "Sources & priority"),
            ("Lyrics", "lyrics", "Matching & sync"),
            ("Wallpaper", "wallpaper", "Scene canvas & vinyl"),
            ("Visualizer", "visualizer", "Live DSP spectrum"),
            ("Appearance", "palette", "Themes & materials"),
            ("Behavior", "sliders", "Window & capture"),
            ("Shortcuts", "keyboard", "Global hotkeys"),
            ("Performance", "zap", "Resource metrics"),
            ("Diagnostics", "terminal", "Health & logs"),
            ("Advanced", "settings", "Caches & profiles")
        ]

        self.nav_buttons: List[QPushButton] = []
        for idx, (label, icon_n, desc) in enumerate(self.nav_items):
            btn = QPushButton(f"  {label}", self.sidebar_card)
            btn.setIcon(get_icon(icon_n, "#C5C8D4", 16))
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #C5C8D4;
                    font-size: 12px;
                    font-weight: 600;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding-left: 10px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.06);
                    color: #FFFFFF;
                }
            """)
            btn.clicked.connect(lambda _, i=idx: self._switch_nav_page(i))
            sb_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sb_layout.addStretch()

        # Bottom media connection pill
        self.media_pill = GlassCard(radius=10, elevated=True, parent=self.sidebar_card)
        mp_l = QHBoxLayout(self.media_pill)
        mp_l.setContentsMargins(8, 8, 8, 8)
        self.lbl_media_icon = QLabel(self.media_pill)
        self.lbl_media_icon.setPixmap(get_icon("spotify", "#2ED573", 14).pixmap(14, 14))
        self.lbl_media_status = QLabel("Auto-Detect\n• Ready", self.media_pill)
        self.lbl_media_status.setStyleSheet("font-size: 10px; font-weight: 600; color: #8A8D9B;")
        mp_l.addWidget(self.lbl_media_icon)
        mp_l.addWidget(self.lbl_media_status, 1)
        sb_layout.addWidget(self.media_pill)

        ws_layout.addWidget(self.sidebar_card)

        # 2B. Content Stack
        self.stack = QStackedWidget(workspace)
        self._build_pages()
        ws_layout.addWidget(self.stack, 1)
        root_layout.addWidget(workspace, 1)

        # 3. Bottom Transaction Bar
        bot_bar = QWidget(self)
        bot_bar.setFixedHeight(48)
        bot_layout = QHBoxLayout(bot_bar)
        bot_layout.setContentsMargins(20, 0, 20, 10)

        self.lbl_unsaved = QLabel("All changes saved", bot_bar)
        self.lbl_unsaved.setStyleSheet("color: #8A8D9B; font-size: 11px;")
        bot_layout.addWidget(self.lbl_unsaved)

        btn_reset = GlassButton("Reset to Defaults", variant="secondary", icon_name="refresh", parent=bot_bar)
        btn_reset.clicked.connect(self._reset_defaults)
        bot_layout.addWidget(btn_reset)

        bot_layout.addStretch()

        self.btn_cancel = GlassButton("Cancel", variant="secondary", parent=bot_bar)
        self.btn_cancel.clicked.connect(self._cancel_changes)
        self.btn_cancel.setEnabled(False)
        bot_layout.addWidget(self.btn_cancel)

        self.btn_apply = GlassButton("Apply Changes", variant="primary", icon_name="check", parent=bot_bar)
        self.btn_apply.clicked.connect(self._apply_changes)
        self.btn_apply.setEnabled(False)
        bot_layout.addWidget(self.btn_apply)

        btn_ok = GlassButton("OK", variant="primary", parent=bot_bar)
        btn_ok.clicked.connect(self._on_ok)
        bot_layout.addWidget(btn_ok)

        root_layout.addWidget(bot_bar)
        self._switch_nav_page(0)

    def _switch_nav_page(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            if i == index:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(46, 213, 115, 0.16);
                        color: #2ED573;
                        font-size: 12px;
                        font-weight: 700;
                        border: 1px solid rgba(46, 213, 115, 0.35);
                        border-radius: 8px;
                        text-align: left;
                        padding-left: 10px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #C5C8D4;
                        font-size: 12px;
                        font-weight: 600;
                        border: none;
                        border-radius: 8px;
                        text-align: left;
                        padding-left: 10px;
                    }
                    QPushButton:hover {
                        background: rgba(255, 255, 255, 0.06);
                        color: #FFFFFF;
                    }
                """)

    def _switch_page(self, page_identifier):
        """Switches page by index or string name (e.g. 'home', 'wallpaper', 'visualizer')."""
        if isinstance(page_identifier, int):
            self._switch_nav_page(page_identifier)
            return

        page_name = str(page_identifier).strip().lower()
        mapping = {
            "home": 0, "overview": 0,
            "media": 1, "sources": 1,
            "lyrics": 2,
            "wallpaper": 3,
            "visualizer": 4,
            "appearance": 5, "theme": 5,
            "behavior": 6,
            "shortcuts": 7, "hotkeys": 7,
            "performance": 8,
            "diagnostics": 9, "logs": 9,
            "advanced": 10, "profiles": 10, "caches": 10
        }
        idx = mapping.get(page_name, 0)
        self._switch_nav_page(idx)

    def _refresh_media_sources(self):
        """Scans active media sessions and updates the UI sources list."""
        self._scan_media_sessions()

    # === Pages Implementation ===

    def _build_pages(self):
        # 0: HOME
        self.stack.addWidget(self._build_page_home())
        # 1: MEDIA
        self.stack.addWidget(self._build_page_media())
        # 2: LYRICS
        self.stack.addWidget(self._build_page_lyrics())
        # 3: WALLPAPER
        self.stack.addWidget(self._build_page_wallpaper())
        # 4: VISUALIZER
        self.stack.addWidget(self._build_page_visualizer())
        # 5: APPEARANCE
        self.stack.addWidget(self._build_page_appearance())
        # 6: BEHAVIOR
        self.stack.addWidget(self._build_page_behavior())
        # 7: SHORTCUTS
        self.stack.addWidget(self._build_page_shortcuts())
        # 8: PERFORMANCE
        self.stack.addWidget(self._build_page_performance())
        # 9: DIAGNOSTICS
        self.stack.addWidget(self._build_page_diagnostics())
        # 10: ADVANCED
        self.stack.addWidget(self._build_page_advanced())

    # --- 0: HOME ---
    def _build_page_home(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # Header Now Playing Banner
        now_card = GlassCard(radius=16, elevated=True, parent=page)
        nc_layout = QHBoxLayout(now_card)
        nc_layout.setContentsMargins(16, 14, 16, 14)

        self.home_art_lbl = QLabel(now_card)
        self.home_art_lbl.setFixedSize(68, 68)
        self.home_art_lbl.setStyleSheet("background: rgba(0,0,0,0.3); border-radius: 10px;")
        nc_layout.addWidget(self.home_art_lbl)

        info_v = QVBoxLayout()
        self.home_title_lbl = QLabel("No Track Playing", now_card)
        self.home_title_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #FFFFFF;")
        self.home_artist_lbl = QLabel("Waiting for media session...", now_card)
        self.home_artist_lbl.setStyleSheet("font-size: 12px; color: #8A8D9B;")
        self.home_meta_lbl = QLabel("Auto-Detect  •  Ready", now_card)
        self.home_meta_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #2ED573;")

        info_v.addWidget(self.home_title_lbl)
        info_v.addWidget(self.home_artist_lbl)
        info_v.addWidget(self.home_meta_lbl)
        nc_layout.addLayout(info_v, 1)

        layout.addWidget(now_card)

        # Bento Status Grid (Clickable)
        grid_card = GlassCard(radius=16, elevated=False, parent=page)
        gc_l = QVBoxLayout(grid_card)
        gc_l.setContentsMargins(14, 12, 14, 12)
        gc_l.setSpacing(10)

        lbl_grid_t = QLabel("Subsystems Status (Click to configure)", grid_card)
        lbl_grid_t.setStyleSheet("font-size: 12px; font-weight: 700; color: #8A8D9B;")
        gc_l.addWidget(lbl_grid_t)

        h1 = QHBoxLayout()
        self.bento_lyrics = BentoStatusCard("Lyrics Overlay", "Active", "Lyrics syncing in real time", "A", "#2ED573", grid_card)
        self.bento_lyrics.mousePressEvent = lambda _: self._switch_nav_page(2)
        self.bento_vis = BentoStatusCard("Visualizer", "Standby", "Audio reactive spectrum", "V", "#38BDF8", grid_card)
        self.bento_vis.mousePressEvent = lambda _: self._switch_nav_page(4)
        h1.addWidget(self.bento_lyrics)
        h1.addWidget(self.bento_vis)
        gc_l.addLayout(h1)

        h2 = QHBoxLayout()
        self.bento_wp = BentoStatusCard("Wallpaper Engine", "Standby", "Dynamic vinyl on WorkerW", "W", "#9B51E0", grid_card)
        self.bento_wp.mousePressEvent = lambda _: self._switch_nav_page(3)
        self.bento_media = BentoStatusCard("Media Source", "Active", "GSMTC Media Interop", "M", "#1DB954", grid_card)
        self.bento_media.mousePressEvent = lambda _: self._switch_nav_page(1)
        h2.addWidget(self.bento_wp)
        h2.addWidget(self.bento_media)
        gc_l.addLayout(h2)

        layout.addWidget(grid_card)

        # Quick Action Buttons
        qa_card = GlassCard(radius=14, elevated=False, parent=page)
        qa_l = QHBoxLayout(qa_card)
        qa_l.setContentsMargins(12, 10, 12, 10)

        btn_qa_ref = GlassButton("Refresh Lyrics", icon_name="refresh", parent=qa_card)
        btn_qa_ref.clicked.connect(self._quick_refresh_lyrics)
        btn_qa_find = GlassButton("Find Lyrics", icon_name="search", parent=qa_card)
        btn_qa_find.clicked.connect(self._open_manual_search)
        btn_qa_logs = GlassButton("Open Logs", icon_name="terminal", parent=qa_card)
        btn_qa_logs.clicked.connect(lambda: self._switch_nav_page(9))

        qa_l.addWidget(btn_qa_ref)
        qa_l.addWidget(btn_qa_find)
        qa_l.addWidget(btn_qa_logs)
        qa_l.addStretch()

        layout.addWidget(qa_card)
        layout.addStretch()
        return page

    # --- 1: MEDIA ---
    def _build_page_media(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(12)

        lbl_h = QLabel("Media Sources & Priority", card)
        lbl_h.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl_h)

        # Preferred source
        s_form = QFormLayout()
        self.cmb_media_src = QComboBox(card)
        self.cmb_media_src.addItems(["Auto-Detect", "Spotify Desktop", "Spotify Web", "YouTube Music", "Brave", "Chrome", "Edge", "Firefox", "Opera"])
        self.cmb_media_src.currentTextChanged.connect(self._on_media_src_changed)
        s_form.addRow("Target Media Source:", self.cmb_media_src)

        self.sw_prefer_playing = ToggleSwitch("Prefer Currently Playing Session", parent=card)
        self.sw_prefer_playing.toggled.connect(lambda v: self._set_setting("prefer_playing_session", v))
        c_l.addLayout(s_form)
        c_l.addWidget(self.sw_prefer_playing)

        # Priority List
        lbl_prio = QLabel("Auto-Detect Source Priority Ranking (Top = Highest Priority):", card)
        lbl_prio.setStyleSheet("font-size: 12px; font-weight: 600; color: #8A8D9B; margin-top: 8px;")
        c_l.addWidget(lbl_prio)

        self.list_priority = QListWidget(card)
        self.list_priority.setFixedHeight(140)
        self.list_priority.setStyleSheet("""
            QListWidget {
                background: rgba(24, 28, 38, 0.65);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 4px;
                color: #FFFFFF;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background: rgba(46, 213, 115, 0.22);
                color: #2ED573;
            }
        """)
        for item in self.working_settings.get("source_priority", []):
            self.list_priority.addItem(item)
        c_l.addWidget(self.list_priority)

        # Reorder buttons
        btn_h = QHBoxLayout()
        btn_up = GlassButton("Move Up", icon_name="chevron_up", parent=card)
        btn_up.clicked.connect(self._priority_move_up)
        btn_down = GlassButton("Move Down", icon_name="chevron_down", parent=card)
        btn_down.clicked.connect(self._priority_move_down)
        btn_scan = GlassButton("Scan Active Sessions", icon_name="refresh", parent=card)
        btn_scan.clicked.connect(self._scan_media_sessions)

        btn_h.addWidget(btn_up)
        btn_h.addWidget(btn_down)
        btn_h.addStretch()
        btn_h.addWidget(btn_scan)
        c_l.addLayout(btn_h)

        layout.addWidget(card)
        layout.addStretch()
        return page

    # --- 2: LYRICS ---
    def _build_page_lyrics(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        lbl_h = QLabel("Lyrics Synchronization & Matching", card)
        lbl_h.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl_h)

        # Match confidence & search modal trigger
        match_h = QHBoxLayout()
        self.lbl_match_score = QLabel("LRCLIB Match Confidence: 94% (HIGH)", card)
        self.lbl_match_score.setStyleSheet("font-size: 12px; font-weight: 700; color: #2ED573;")
        btn_manual_search = GlassButton("Find / Correct Lyrics...", icon_name="search", parent=card)
        btn_manual_search.clicked.connect(self._open_manual_search)

        match_h.addWidget(self.lbl_match_score)
        match_h.addStretch()
        match_h.addWidget(btn_manual_search)
        c_l.addLayout(match_h)

        # Sync offset sliders
        lbl_sync = QLabel("Global Timing Offset (milliseconds):", card)
        lbl_sync.setStyleSheet("font-size: 11px; font-weight: 600; color: #8A8D9B; margin-top: 6px;")
        c_l.addWidget(lbl_sync)

        self.sld_sync = ValueSlider(-5000, 5000, 0, "ms", parent=card)
        self.sld_sync.valueChanged.connect(lambda v: self._set_setting("sync_offset_ms", v))
        c_l.addWidget(self.sld_sync)

        # Quick nudge buttons
        nudge_h = QHBoxLayout()
        btn_nudge_m = GlassButton("-250ms (Earlier)", parent=card)
        btn_nudge_m.clicked.connect(lambda: self.sld_sync.setValue(self.sld_sync.value() - 250))
        btn_nudge_p = GlassButton("+250ms (Later)", parent=card)
        btn_nudge_p.clicked.connect(lambda: self.sld_sync.setValue(self.sld_sync.value() + 250))
        btn_nudge_zero = GlassButton("Reset 0ms", parent=card)
        btn_nudge_zero.clicked.connect(lambda: self.sld_sync.setValue(0))

        nudge_h.addWidget(btn_nudge_m)
        nudge_h.addWidget(btn_nudge_p)
        nudge_h.addWidget(btn_nudge_zero)
        nudge_h.addStretch()
        c_l.addLayout(nudge_h)

        # Presentation & Modes
        lbl_mode = QLabel("Lyrics Presentation Mode:", card)
        lbl_mode.setStyleSheet("font-size: 11px; font-weight: 600; color: #8A8D9B; margin-top: 8px;")
        c_l.addWidget(lbl_mode)

        self.cmb_view_mode = QComboBox(card)
        self.cmb_view_mode.addItems(["Multi-line", "Single-line Ticker", "Minimal"])
        self.cmb_view_mode.currentTextChanged.connect(lambda v: self._set_setting("lyrics_view_mode", v))
        c_l.addWidget(self.cmb_view_mode)

        # Context lines
        self.sld_context = ValueSlider(0, 5, 2, " lines", parent=card)
        self.sld_context.valueChanged.connect(lambda v: self._set_setting("context_lines", v))
        c_l.addWidget(self.sld_context)

        layout.addWidget(card)
        layout.addStretch()
        return page

    # --- 3: WALLPAPER STUDIO ---
    def _build_page_wallpaper(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        # Top bar with Enable Switch
        top_h = QHBoxLayout()
        lbl_t = QLabel("Wallpaper Studio", card)
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        self.sw_wallpaper = ToggleSwitch("Enable Dynamic Desktop Wallpaper", parent=card)
        self.sw_wallpaper.toggled.connect(lambda v: self._set_setting("wallpaper_enabled", v))

        top_h.addWidget(lbl_t)
        top_h.addStretch()
        top_h.addWidget(self.sw_wallpaper)
        c_l.addLayout(top_h)

        # Interactive Canvas
        self.wp_canvas = WallpaperPreviewWidget(card)
        self.wp_canvas.setFixedHeight(220)
        self.wp_canvas.vinyl_position_changed.connect(self._on_wp_pos_changed)
        self.wp_canvas.vinyl_size_changed.connect(self._on_wp_size_changed)
        c_l.addWidget(self.wp_canvas)

        # Alignment Toolbar
        align_h = QHBoxLayout()
        btn_al = GlassButton("Align Left", parent=card)
        btn_al.clicked.connect(lambda: self._align_vinyl(0.20, None))
        btn_ac = GlassButton("Center", parent=card)
        btn_ac.clicked.connect(lambda: self._align_vinyl(0.50, 0.50))
        btn_ar = GlassButton("Align Right", parent=card)
        btn_ar.clicked.connect(lambda: self._align_vinyl(0.78, None))
        btn_dbg = GlassButton("Toggle Debug HUD", parent=card)
        btn_dbg.clicked.connect(self.wp_canvas.toggle_debug_overlay)

        align_h.addWidget(btn_al)
        align_h.addWidget(btn_ac)
        align_h.addWidget(btn_ar)
        align_h.addStretch()
        align_h.addWidget(btn_dbg)
        c_l.addLayout(align_h)

        # Controls grid
        form = QFormLayout()
        self.cmb_wp_scaling = QComboBox(card)
        self.cmb_wp_scaling.addItems(["fill", "fit", "stretch", "center"])
        self.cmb_wp_scaling.currentTextChanged.connect(self._on_wp_scaling_changed)
        form.addRow("Scaling Mode:", self.cmb_wp_scaling)

        self.cmb_wp_display = QComboBox(card)
        for opt in get_wallpaper_display_options():
            self.cmb_wp_display.addItem(opt)
        self.cmb_wp_display.currentTextChanged.connect(lambda v: self._set_setting("wallpaper_display_mode", v))
        form.addRow("Target Display:", self.cmb_wp_display)

        c_l.addLayout(form)
        layout.addWidget(card)
        return page

    # --- 4: VISUALIZER STUDIO ---
    def _build_page_visualizer(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        # Top Bar
        top_h = QHBoxLayout()
        lbl_t = QLabel("Visualizer Studio", card)
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        self.sw_vis_enable = ToggleSwitch("Enable Audio Visualizer", parent=card)
        self.sw_vis_enable.toggled.connect(lambda v: self._set_setting("visualizer_enabled", v))

        top_h.addWidget(lbl_t)
        top_h.addStretch()
        top_h.addWidget(self.sw_vis_enable)
        c_l.addLayout(top_h)

        # Live Preview Canvas
        self.vis_preview = VisualizerPreviewWidget(card)
        c_l.addWidget(self.vis_preview)

        # Preview mode switcher (Demo vs Live Audio)
        mode_h = QHBoxLayout()
        self.seg_vis_preview = SegmentedSwitch([("play", "Demo Mode"), ("visualizer", "Live Audio Mode")], parent=card)
        self.seg_vis_preview.switched.connect(lambda idx: self.vis_preview.set_preview_mode("Live Audio" if idx == 1 else "Demo"))
        mode_h.addWidget(self.seg_vis_preview)
        mode_h.addStretch()
        c_l.addLayout(mode_h)

        # Controls
        form = QFormLayout()
        self.cmb_vis_style = QComboBox(card)
        self.cmb_vis_style.addItems(["Pill Bars", "Standard Bars", "Square Bar"])
        self.cmb_vis_style.currentTextChanged.connect(self._on_vis_style_changed)
        form.addRow("Bar Style:", self.cmb_vis_style)

        self.sld_vis_bars = ValueSlider(8, 128, 32, " bars", parent=card)
        self.sld_vis_bars.valueChanged.connect(self._on_vis_bars_changed)
        form.addRow("Bar Count:", self.sld_vis_bars)

        self.sld_vis_smooth = ValueSlider(0, 100, 75, "%", parent=card)
        self.sld_vis_smooth.valueChanged.connect(lambda v: self._set_setting("visualizer_smoothing", v))
        form.addRow("Smoothing:", self.sld_vis_smooth)

        c_l.addLayout(form)
        layout.addWidget(card)
        return page

    # --- 5: APPEARANCE ---
    def _build_page_appearance(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(12)

        lbl_t = QLabel("Global Appearance & Materials", card)
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl_t)

        form = QFormLayout()
        self.cmb_theme_mode = QComboBox(card)
        self.cmb_theme_mode.addItems(["Dynamic Album Accent", "Manual Accent", "Neutral Dark"])
        self.cmb_theme_mode.currentTextChanged.connect(lambda v: self._set_setting("theme_mode", v))
        form.addRow("Accent Mode:", self.cmb_theme_mode)

        self.btn_manual_accent = ColorSwatchButton("#1DB954", card)
        self.btn_manual_accent.colorChanged.connect(lambda col: self._set_setting("manual_accent_color", col))
        form.addRow("Manual Accent Color:", self.btn_manual_accent)

        self.sld_glass = ValueSlider(20, 100, 75, "%", parent=card)
        self.sld_glass.valueChanged.connect(lambda v: self._set_setting("glass_intensity", v))
        form.addRow("Glass Opacity Intensity:", self.sld_glass)

        c_l.addLayout(form)

        self.sw_reduced_motion = ToggleSwitch("Reduced Motion (disable large animated transitions)", parent=card)
        self.sw_reduced_motion.toggled.connect(lambda v: self._set_setting("reduced_motion", v))
        c_l.addWidget(self.sw_reduced_motion)

        layout.addWidget(card)
        layout.addStretch()
        return page

    # --- 6: BEHAVIOR ---
    def _build_page_behavior(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        lbl_t = QLabel("Window Behavior & System Integration", card)
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl_t)

        self.sw_topmost = ToggleSwitch("Keep Lyrics Overlay Always on Top", parent=card)
        self.sw_topmost.toggled.connect(lambda v: self._set_setting("always_on_top", v))
        c_l.addWidget(self.sw_topmost)

        self.sw_click_thru = ToggleSwitch("Click-Through Mode (pass mouse clicks to desktop/games)", parent=card)
        self.sw_click_thru.toggled.connect(lambda v: self._set_setting("click_through", v))
        c_l.addWidget(self.sw_click_thru)

        self.sw_exclude_cap = ToggleSwitch("Exclude from Screen Capture (hide from OBS/Discord)", parent=card)
        self.sw_exclude_cap.toggled.connect(lambda v: self._set_setting("exclude_from_capture", v))
        c_l.addWidget(self.sw_exclude_cap)

        self.sw_auto_hide = ToggleSwitch("Auto-hide Lyrics Overlay when playback is paused", parent=card)
        self.sw_auto_hide.toggled.connect(lambda v: self._set_setting("auto_hide_on_pause", v))
        c_l.addWidget(self.sw_auto_hide)

        form = QFormLayout()
        self.cmb_close_act = QComboBox(card)
        self.cmb_close_act.addItems(["Minimize to Tray", "Hide Window", "Quit App"])
        self.cmb_close_act.currentTextChanged.connect(lambda v: self._set_setting("close_action", v))
        form.addRow("Closing Studio Window:", self.cmb_close_act)
        c_l.addLayout(form)

        layout.addWidget(card)
        layout.addStretch()
        return page

    # --- 7: SHORTCUTS ---
    def _build_page_shortcuts(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        lbl_t = QLabel("Global Keyboard Shortcuts", card)
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl_t)

        self.table_shortcuts = QTableWidget(card)
        self.table_shortcuts.setColumnCount(3)
        self.table_shortcuts.setHorizontalHeaderLabels(["Action", "Key Combination", "Status"])
        self.table_shortcuts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_shortcuts.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_shortcuts.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_shortcuts.verticalHeader().setVisible(False)
        self.table_shortcuts.setFixedHeight(240)
        self.table_shortcuts.setStyleSheet("""
            QTableWidget {
                background: rgba(24, 28, 38, 0.65);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                color: #FFFFFF;
            }
        """)

        self._populate_shortcuts_table()
        c_l.addWidget(self.table_shortcuts)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _populate_shortcuts_table(self):
        conflicts = find_shortcut_conflicts(self.working_settings)
        self.table_shortcuts.setRowCount(len(SHORTCUT_DEFINITIONS))

        for row, item in enumerate(SHORTCUT_DEFINITIONS):
            k_id = item["key_id"]
            val = self.working_settings.get(k_id, item["default"])

            item_act = QTableWidgetItem(item["name"])
            item_act.setToolTip(item["description"])
            self.table_shortcuts.setItem(row, 0, item_act)

            item_key = QTableWidgetItem(val)
            self.table_shortcuts.setItem(row, 1, item_key)

            if k_id in conflicts:
                status_item = QTableWidgetItem("⚠️ Conflict")
                status_item.setForeground(QColor("#FF4757"))
            else:
                status_item = QTableWidgetItem("✓ Active")
                status_item.setForeground(QColor("#2ED573"))
            self.table_shortcuts.setItem(row, 2, status_item)

    # --- 8: PERFORMANCE ---
    def _build_page_performance(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # Gauges row
        g_row = QHBoxLayout()
        self.gauge_cpu = MetricGaugeCard("CPU Usage", "1.4%", "Host Process", parent=page)
        self.gauge_ram = MetricGaugeCard("RAM Usage", "84 MB", "Heap Allocation", parent=page)
        self.gauge_fps = MetricGaugeCard("Render FPS", "60.0", "Active VSync", parent=page)
        g_row.addWidget(self.gauge_cpu)
        g_row.addWidget(self.gauge_ram)
        g_row.addWidget(self.gauge_fps)
        layout.addLayout(g_row)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        lbl_t = QLabel("Power & Rendering Profiles", card)
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl_t)

        form = QFormLayout()
        self.cmb_power_prof = QComboBox(card)
        self.cmb_power_prof.addItems(["High Performance (60 FPS)", "Balanced (30 FPS)", "Battery Saver (15 FPS)"])
        self.cmb_power_prof.currentTextChanged.connect(lambda v: self._set_setting("power_profile", v))
        form.addRow("Active Power Profile:", self.cmb_power_prof)

        self.sld_preview_fps = ValueSlider(15, 120, 60, " FPS", parent=card)
        self.sld_preview_fps.valueChanged.connect(lambda v: self._set_setting("preview_fps", v))
        form.addRow("Studio Preview FPS:", self.sld_preview_fps)

        c_l.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return page

    # --- 9: DIAGNOSTICS ---
    def _build_page_diagnostics(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        top_h = QHBoxLayout()
        lbl_t = QLabel("Subsystem Health & Live Logs", card)
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        btn_copy = GlassButton("Copy Diagnostics", icon_name="clipboard", parent=card)
        btn_copy.clicked.connect(self._copy_diagnostics)
        btn_export = GlassButton("Export JSON", icon_name="download", parent=card)
        btn_export.clicked.connect(self._export_diagnostics)

        top_h.addWidget(lbl_t)
        top_h.addStretch()
        top_h.addWidget(btn_copy)
        top_h.addWidget(btn_export)
        c_l.addLayout(top_h)

        # Log viewer
        self.txt_logs = QTextEdit(card)
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setFixedHeight(260)
        self.txt_logs.setStyleSheet("""
            QTextEdit {
                background: rgba(10, 13, 20, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                color: #A0A5B5;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                padding: 8px;
            }
        """)
        self._refresh_logs()
        c_l.addWidget(self.txt_logs)

        # Clear logs button
        log_act_h = QHBoxLayout()
        btn_ref_logs = GlassButton("Refresh Logs", parent=card)
        btn_ref_logs.clicked.connect(self._refresh_logs)
        btn_clear_logs = GlassButton("Clear Logs", parent=card)
        btn_clear_logs.clicked.connect(self._clear_logs)

        log_act_h.addWidget(btn_ref_logs)
        log_act_h.addWidget(btn_clear_logs)
        log_act_h.addStretch()
        c_l.addLayout(log_act_h)

        layout.addWidget(card)
        layout.addStretch()
        return page

    # --- 10: ADVANCED ---
    def _build_page_advanced(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        card = GlassCard(radius=16, elevated=False, parent=page)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        lbl_t = QLabel("Storage Caches & Profile Presets", card)
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl_t)

        # Cache stats
        stats = self.lyrics_client.get_cache_stats()
        self.lbl_cache_info = QLabel(f"Cached Lyrics: {stats['file_count']} files ({stats['formatted_size']})", card)
        self.lbl_cache_info.setStyleSheet("font-size: 12px; color: #C5C8D4;")
        c_l.addWidget(self.lbl_cache_info)

        cache_btn_h = QHBoxLayout()
        btn_clr_lyrics = GlassButton("Clear Lyrics Cache", parent=card)
        btn_clr_lyrics.clicked.connect(self._clear_lyrics_cache)
        btn_clr_all = GlassButton("Clear All Caches", parent=card)
        btn_clr_all.clicked.connect(self._clear_all_caches)

        cache_btn_h.addWidget(btn_clr_lyrics)
        cache_btn_h.addWidget(btn_clr_all)
        cache_btn_h.addStretch()
        c_l.addLayout(cache_btn_h)

        # Backup & Restore
        lbl_b = QLabel("Settings Backup & Restore:", card)
        lbl_b.setStyleSheet("font-size: 12px; font-weight: 600; color: #8A8D9B; margin-top: 10px;")
        c_l.addWidget(lbl_b)

        bak_h = QHBoxLayout()
        btn_create_bak = GlassButton("Create Backup", icon_name="download", parent=card)
        btn_create_bak.clicked.connect(self._create_backup)
        btn_restore_bak = GlassButton("Restore Backup...", icon_name="refresh", parent=card)
        btn_restore_bak.clicked.connect(self._restore_backup)

        bak_h.addWidget(btn_create_bak)
        bak_h.addWidget(btn_restore_bak)
        bak_h.addStretch()
        c_l.addLayout(bak_h)

        # About App
        lbl_about = QLabel(f"Lyrune Studio v2.0.0  •  Qt 6.8  •  Python {platform.python_version()}", card)
        lbl_about.setStyleSheet("font-size: 11px; color: #525666; margin-top: 14px;")
        c_l.addWidget(lbl_about)

        layout.addWidget(card)
        layout.addStretch()
        return page

    # === State Bindings & Handlers ===

    def _set_setting(self, key: str, value: Any):
        self._record_transaction()
        self.working_settings[key] = value
        self._update_unsaved_indicator()

    def _on_media_src_changed(self, text: str):
        self._set_setting("selected_media_source", text)
        if self.player:
            self.player.set_target_source(text)

    def _priority_move_up(self):
        row = self.list_priority.currentRow()
        if row > 0:
            item = self.list_priority.takeItem(row)
            self.list_priority.insertItem(row - 1, item)
            self.list_priority.setCurrentRow(row - 1)
            self._save_priority_from_list()

    def _priority_move_down(self):
        row = self.list_priority.currentRow()
        if 0 <= row < self.list_priority.count() - 1:
            item = self.list_priority.takeItem(row)
            self.list_priority.insertItem(row + 1, item)
            self.list_priority.setCurrentRow(row + 1)
            self._save_priority_from_list()

    def _save_priority_from_list(self):
        order = [self.list_priority.item(i).text() for i in range(self.list_priority.count())]
        self._set_setting("source_priority", order)
        if self.player:
            self.player.set_source_priority(order)

    def _scan_media_sessions(self):
        if self.player and hasattr(self.player, "_worker_thread") and self.player._worker_thread:
            self.player._worker_thread.request_source_scan()
            log_event("[Media] Requested scan of active GSMTC media sessions.")

    def _open_manual_search(self):
        art = self.home_artist_lbl.text() if self.home_artist_lbl.text() != "Waiting for media session..." else ""
        tit = self.home_title_lbl.text() if self.home_title_lbl.text() != "No Track Playing" else ""
        dlg = ManualLyricSearchDialog(self.lyrics_client, art, tit, parent=self)
        dlg.lyricsSelected.connect(self._on_custom_lyrics_bound)
        dlg.move(self.x() + (self.width() - dlg.width()) // 2, self.y() + (self.height() - dlg.height()) // 2)
        dlg.show()

    def _on_custom_lyrics_bound(self, artist, title, synced, unsynced):
        log_event(f"[Studio] Custom lyrics bound for '{artist} - {title}'")
        self.settings_changed.emit(self.working_settings)

    def _quick_refresh_lyrics(self):
        art = self.home_artist_lbl.text()
        tit = self.home_title_lbl.text()
        if art and tit:
            self.lyrics_client.clear_track_cache(art, tit)
        self.settings_changed.emit(self.working_settings)

    def _on_wp_pos_changed(self, lx: float, ly: float):
        self.working_settings["wallpaper_vinyl_x"] = lx
        self.working_settings["wallpaper_vinyl_y"] = ly
        self._update_unsaved_indicator()

    def _on_wp_size_changed(self, l_size: float):
        self.working_settings["wallpaper_vinyl_size"] = l_size
        self._update_unsaved_indicator()

    def _align_vinyl(self, x: Optional[float], y: Optional[float]):
        self._record_transaction()
        if x is not None:
            self.working_settings["wallpaper_vinyl_x"] = x
        if y is not None:
            self.working_settings["wallpaper_vinyl_y"] = y
        self.wp_canvas.update_vinyl_position(
            self.working_settings["wallpaper_vinyl_x"],
            self.working_settings["wallpaper_vinyl_y"]
        )
        self._update_unsaved_indicator()

    def _on_wp_scaling_changed(self, mode: str):
        self._set_setting("wallpaper_scaling_mode", mode)
        cfg = WallpaperConfig.from_settings(self.working_settings)
        self.wp_canvas.set_config(cfg)

    def _on_vis_style_changed(self, style_name: str):
        self._set_setting("visualizer_style", style_name)
        self.vis_preview.update_style(self.working_settings)

    def _on_vis_bars_changed(self, count: int):
        self._set_setting("visualizer_bar_count", count)
        self.vis_preview.update_style(self.working_settings)

    def _copy_diagnostics(self):
        data = generate_full_diagnostics_report(self.player, self.lyrics_client)
        text = json.dumps(data, indent=2)
        QApplication.clipboard().setText(text)
        log_event("[Diagnostics] Full report copied to clipboard.")

    def _export_diagnostics(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Diagnostics", "lyrune_diagnostics.json", "JSON (*.json)")
        if path:
            data = generate_full_diagnostics_report(self.player, self.lyrics_client)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            log_event(f"[Diagnostics] Exported diagnostics to: {path}")

    def _refresh_logs(self):
        history = event_logger.get_history()
        self.txt_logs.setPlainText("\n".join(history))
        self.txt_logs.verticalScrollBar().setValue(self.txt_logs.verticalScrollBar().maximum())

    def _clear_logs(self):
        event_logger.clear()
        self.txt_logs.clear()

    def _clear_lyrics_cache(self):
        count = self.lyrics_client.clear_cache()
        stats = self.lyrics_client.get_cache_stats()
        self.lbl_cache_info.setText(f"Cached Lyrics: {stats['file_count']} files ({stats['formatted_size']})")
        log_event(f"[Caches] Cleared {count} lyrics cache files.")

    def _clear_all_caches(self):
        self._clear_lyrics_cache()
        log_event("[Caches] All caches cleared.")

    def _create_backup(self):
        path = self.settings_mgr.create_backup()
        QMessageBox.information(self, "Backup Created", f"Settings backup saved to:\n{path}")

    def _restore_backup(self):
        backups = self.settings_mgr.list_backups()
        if not backups:
            QMessageBox.warning(self, "No Backups", "No backup files found in backup directory.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select Backup File", self.settings_mgr.backup_dir, "JSON (*.json)")
        if path and self.settings_mgr.restore_backup(path):
            self.saved_settings = dict(self.settings_mgr.settings)
            self.working_settings = dict(self.saved_settings)
            self._load_working_settings_to_ui()
            self._update_unsaved_indicator()
            self.settings_changed.emit(self.working_settings)

    def _reset_defaults(self):
        self.working_settings = dict(DEFAULT_SETTINGS)
        self._load_working_settings_to_ui()
        self._update_unsaved_indicator()

    def _cancel_changes(self):
        self.working_settings = dict(self.saved_settings)
        self._load_working_settings_to_ui()
        self._update_unsaved_indicator()

    def _apply_changes(self):
        self.settings_mgr.update(self.working_settings)
        self.saved_settings = dict(self.working_settings)
        self._update_unsaved_indicator()
        self.settings_changed.emit(self.working_settings)

    def _on_ok(self):
        if self.working_settings != self.saved_settings:
            self._apply_changes()
        self.accept()

    def _load_working_settings_to_ui(self):
        s = self.working_settings
        self.cmb_media_src.setCurrentText(s.get("selected_media_source", "Auto-Detect"))
        self.sw_prefer_playing.setChecked(s.get("prefer_playing_session", True))
        self.sld_sync.setValue(s.get("sync_offset_ms", 0))
        self.cmb_view_mode.setCurrentText(s.get("lyrics_view_mode", "Multi-line"))
        self.sld_context.setValue(s.get("context_lines", 2))
        self.sw_wallpaper.setChecked(s.get("wallpaper_enabled", False))
        self.cmb_wp_scaling.setCurrentText(s.get("wallpaper_scaling_mode", "fill"))
        self.cmb_wp_display.setCurrentText(s.get("wallpaper_display_mode", "Primary Display"))
        self.sw_vis_enable.setChecked(s.get("visualizer_enabled", False))
        self.cmb_vis_style.setCurrentText(s.get("visualizer_style", "Pill Bars"))
        self.sld_vis_bars.setValue(s.get("visualizer_bar_count", 32))
        self.sld_vis_smooth.setValue(s.get("visualizer_smoothing", 75))
        self.cmb_theme_mode.setCurrentText(s.get("theme_mode", "Dynamic Album Accent"))
        self.btn_manual_accent.setColor(s.get("manual_accent_color", "#1DB954"))
        self.sld_glass.setValue(s.get("glass_intensity", 75))
        self.sw_reduced_motion.setChecked(s.get("reduced_motion", False))
        self.sw_topmost.setChecked(s.get("always_on_top", True))
        self.sw_click_thru.setChecked(s.get("click_through", False))
        self.sw_exclude_cap.setChecked(s.get("exclude_from_capture", False))
        self.sw_auto_hide.setChecked(s.get("auto_hide_on_pause", False))
        self.cmb_close_act.setCurrentText(s.get("close_action", "Minimize to Tray"))

        cfg = WallpaperConfig.from_settings(s)
        self.wp_canvas.set_config(cfg)
        self.vis_preview.update_style(s)
        self._populate_shortcuts_table()

    # === Command Palette (Ctrl+K) ===

    def _open_command_palette(self):
        actions = [
            {"id": "nav_0", "name": "Go to Home / Overview", "desc": "Live now playing dashboard", "category": "Navigation"},
            {"id": "nav_1", "name": "Go to Media Sources", "desc": "Priority & session management", "category": "Navigation"},
            {"id": "nav_2", "name": "Go to Lyrics Workspace", "desc": "Matching, confidence & sync", "category": "Navigation"},
            {"id": "nav_3", "name": "Go to Wallpaper Studio", "desc": "Scene editor & vinyl placement", "category": "Navigation"},
            {"id": "nav_4", "name": "Go to Visualizer Studio", "desc": "Live audio & style editor", "category": "Navigation"},
            {"id": "nav_5", "name": "Go to Appearance", "desc": "Themes, accents & materials", "category": "Navigation"},
            {"id": "nav_6", "name": "Go to Behavior", "desc": "Window layering & capture", "category": "Navigation"},
            {"id": "nav_7", "name": "Go to Shortcuts", "desc": "Global hotkey manager", "category": "Navigation"},
            {"id": "nav_8", "name": "Go to Performance", "desc": "Hardware resource gauges", "category": "Navigation"},
            {"id": "nav_9", "name": "Go to Diagnostics", "desc": "Subsystem health & logs", "category": "Navigation"},
            {"id": "nav_10", "name": "Go to Advanced & Caches", "desc": "Storage & backups", "category": "Navigation"},
            {"id": "act_search", "name": "Find & Correct Lyrics", "desc": "Manual LRCLIB search modal", "category": "Lyrics"},
            {"id": "act_refresh", "name": "Force Refresh Lyrics", "desc": "Purge cache and re-query", "category": "Lyrics"},
            {"id": "act_diag_copy", "name": "Copy Diagnostics Report", "desc": "Export health JSON to clipboard", "category": "Diagnostics"},
        ]
        dlg = CommandPaletteDialog(actions, parent=self)
        dlg.actionTriggered.connect(self._on_command_palette_action)
        dlg.move(self.x() + (self.width() - dlg.width()) // 2, self.y() + 80)
        dlg.show()

    def _on_command_palette_action(self, action_id: str):
        if action_id.startswith("nav_"):
            idx = int(action_id.split("_")[1])
            self._switch_nav_page(idx)
        elif action_id == "act_search":
            self._open_manual_search()
        elif action_id == "act_refresh":
            self._quick_refresh_lyrics()
        elif action_id == "act_diag_copy":
            self._copy_diagnostics()

    # === Live Media Updates Connection ===

    def _connect_player_signals(self):
        if self.player and hasattr(self.player, "_worker_thread") and self.player._worker_thread:
            self.player._worker_thread.media_updated.connect(self._on_media_updated)

    def _on_media_updated(self, info: dict):
        tit = info.get("title") or "No Track Playing"
        art = info.get("artist") or "Waiting for media session..."
        self.home_title_lbl.setText(tit)
        self.home_artist_lbl.setText(art)
        self.title_bar.dynamic_island.update_track(tit, art)

        # Album Art
        art_bytes = info.get("album_art_bytes")
        if art_bytes:
            pix = QPixmap()
            if pix.loadFromData(art_bytes):
                self.home_art_lbl.setPixmap(pix.scaled(68, 68, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                self.title_bar.dynamic_island.update_artwork(pix)
                accent = extract_dominant_accent(pix)
                if accent:
                    self._ambient_accent = accent
                    self.update()
