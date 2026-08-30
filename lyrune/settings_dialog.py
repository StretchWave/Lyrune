"""
settings_dialog.py — Modern Translucent Cinematic Glass Desktop Studio for Lyrune.

Full 11-page information architecture with subsection navigation, settings registry
search, progressive disclosure, contextual controls, domain presets, per-section
reset, tooltips, undo/redo, and live preview.
"""

import os
import re
import json
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
    MetricGaugeCard, GlassButton, CollapsibleSection, SubSectionTabs,
    SettingsSearchDialog, ResetButton, TooltipLabel, PresetSelector
)
from lyrune.settings_manager import (
    SettingsManager, DEFAULT_SETTINGS, PRESETS,
    LYRICS_PRESETS, WALLPAPER_PRESETS, VISUALIZER_PRESETS
)
from lyrune.settings_registry import SETTINGS_REGISTRY, SettingMeta
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


# ══════════════════════════════════════════════════════════════════════════════
# Helper: register a setting into the global registry
# ══════════════════════════════════════════════════════════════════════════════

def _reg(setting_id: str, name: str, page: str, section: str,
         description: str = "", keywords: list = None,
         setting_type: str = "string", default: Any = None,
         depends_on: str = None, advanced: bool = False,
         settings_key: str = "", **kw) -> None:
    """Shorthand to register a setting in the global registry."""
    SETTINGS_REGISTRY.register(SettingMeta(
        setting_id=setting_id, name=name, page=page, section=section,
        description=description, keywords=keywords or [],
        setting_type=setting_type, default=default,
        depends_on=depends_on, advanced=advanced,
        settings_key=settings_key or setting_id, **kw
    ))


# ══════════════════════════════════════════════════════════════════════════════
# Helper: create a scrollable subsection page container
# ══════════════════════════════════════════════════════════════════════════════

def _make_scroll_page() -> Tuple[QScrollArea, QWidget, QVBoxLayout]:
    """Create a scroll area with a content widget and layout."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(10)
    scroll.setWidget(content)
    return scroll, content, layout


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
    Full 11-page information architecture with subsection tabs, settings registry
    search, progressive disclosure, bi-directional bindings, and transaction semantics.
    """
    settings_changed = pyqtSignal(dict)

    # Page name → subsection tab names mapping
    PAGE_SUBSECTIONS = {
        "Lyrics": ["Content", "Typography", "Layout", "Appearance", "Animation", "Sync", "Behavior"],
        "Wallpaper": ["Canvas", "Background", "Vinyl", "Text", "Lyrics", "Visualizer", "Layers", "Behavior"],
        "Visualizer": ["Preview", "Audio", "Bars", "Color", "Effects", "Position", "Game Overlay", "Behavior"],
        "Appearance": ["Theme", "Glass", "Accent", "Background", "Motion"],
    }

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

        # Widget references for registry + deep navigation
        self._widget_map: Dict[str, QWidget] = {}
        # Subsection stacks per page
        self._subsection_stacks: Dict[str, QStackedWidget] = {}
        self._subsection_tabs: Dict[str, SubSectionTabs] = {}

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
        QShortcut(QKeySequence("Ctrl+K"), self, self._open_settings_search)
        QShortcut(QKeySequence("Ctrl+F"), self, self._open_settings_search)
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
        self.title_bar.commandPaletteClicked.connect(self._open_settings_search)
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
        """Switches page by index or string name."""
        if isinstance(page_identifier, int):
            self._switch_nav_page(page_identifier)
            return
        page_name = str(page_identifier).strip().lower()
        mapping = {
            "home": 0, "overview": 0, "media": 1, "sources": 1,
            "lyrics": 2, "wallpaper": 3, "visualizer": 4,
            "appearance": 5, "theme": 5, "behavior": 6,
            "shortcuts": 7, "hotkeys": 7, "performance": 8,
            "diagnostics": 9, "logs": 9, "advanced": 10, "profiles": 10, "caches": 10
        }
        idx = mapping.get(page_name, 0)
        self._switch_nav_page(idx)

    def _refresh_media_sources(self):
        """Scans active media sessions and updates the UI sources list."""
        self._scan_media_sessions()

    # === Helper: build a subsectioned page ===

    def _build_subsection_page(self, page_name: str, subsections: List[str],
                                builders: List) -> QWidget:
        """
        Build a page with SubSectionTabs at top and a QStackedWidget holding
        each subsection's content.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        tabs = SubSectionTabs(subsections, parent=page)
        self._subsection_tabs[page_name] = tabs
        layout.addWidget(tabs)

        sub_stack = QStackedWidget(page)
        self._subsection_stacks[page_name] = sub_stack

        for builder in builders:
            sub_stack.addWidget(builder())

        tabs.tabChanged.connect(sub_stack.setCurrentIndex)
        layout.addWidget(sub_stack, 1)
        return page

    # === Pages Implementation ===

    def _build_pages(self):
        self.stack.addWidget(self._build_page_home())           # 0: HOME
        self.stack.addWidget(self._build_page_media())           # 1: MEDIA
        self.stack.addWidget(self._build_page_lyrics())           # 2: LYRICS
        self.stack.addWidget(self._build_page_wallpaper())        # 3: WALLPAPER
        self.stack.addWidget(self._build_page_visualizer())       # 4: VISUALIZER
        self.stack.addWidget(self._build_page_appearance())       # 5: APPEARANCE
        self.stack.addWidget(self._build_page_behavior())         # 6: BEHAVIOR
        self.stack.addWidget(self._build_page_shortcuts())        # 7: SHORTCUTS
        self.stack.addWidget(self._build_page_performance())      # 8: PERFORMANCE
        self.stack.addWidget(self._build_page_diagnostics())      # 9: DIAGNOSTICS
        self.stack.addWidget(self._build_page_advanced())         # 10: ADVANCED

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ 0: HOME                                                             ║
    # ╚══════════════════════════════════════════════════════════════════════╝

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

        # Bento Status Grid
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

        # Quick Actions
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

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ 1: MEDIA                                                            ║
    # ╚══════════════════════════════════════════════════════════════════════╝

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

        s_form = QFormLayout()
        self.cmb_media_src = QComboBox(card)
        self.cmb_media_src.addItems(["Auto-Detect", "Spotify Desktop", "Spotify Web", "YouTube Music", "Brave", "Chrome", "Edge", "Firefox", "Opera"])
        self.cmb_media_src.currentTextChanged.connect(self._on_media_src_changed)
        s_form.addRow("Target Media Source:", self.cmb_media_src)

        self.sw_prefer_playing = ToggleSwitch("Prefer Currently Playing Session", parent=card)
        self.sw_prefer_playing.toggled.connect(lambda v: self._set_setting("prefer_playing_session", v))
        c_l.addLayout(s_form)
        c_l.addWidget(self.sw_prefer_playing)

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
            QListWidget::item { padding: 6px 10px; border-radius: 6px; }
            QListWidget::item:selected { background: rgba(46, 213, 115, 0.22); color: #2ED573; }
        """)
        for item in self.working_settings.get("source_priority", []):
            self.list_priority.addItem(item)
        c_l.addWidget(self.list_priority)

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

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ 2: LYRICS — 7 Subsections                                          ║
    # ╚══════════════════════════════════════════════════════════════════════╝

    def _build_page_lyrics(self) -> QWidget:
        return self._build_subsection_page("Lyrics",
            self.PAGE_SUBSECTIONS["Lyrics"],
            [
                self._build_lyrics_content,
                self._build_lyrics_typography,
                self._build_lyrics_layout,
                self._build_lyrics_appearance,
                self._build_lyrics_animation,
                self._build_lyrics_sync,
                self._build_lyrics_behavior,
            ]
        )

    def _build_lyrics_content(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        # Header + Preset
        top_h = QHBoxLayout()
        lbl = QLabel("Lyrics Content", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        top_h.addWidget(lbl)
        top_h.addStretch()
        preset = PresetSelector(LYRICS_PRESETS, parent=card)
        preset.presetSelected.connect(lambda n: self._apply_domain_preset("lyrics", n))
        top_h.addWidget(preset)
        c_l.addLayout(top_h)

        form = QFormLayout()
        # View mode
        self.cmb_view_mode = QComboBox(card)
        self.cmb_view_mode.addItems(["Multi-line", "Single-line Ticker", "Minimal", "Karaoke"])
        self.cmb_view_mode.currentTextChanged.connect(lambda v: self._set_setting("lyrics_view_mode", v))
        form.addRow("Lyrics Mode:", self.cmb_view_mode)
        _reg("lyrics_view_mode", "Lyrics Mode", "Lyrics", "Content",
             "Display style for lyrics overlay", ["mode", "multi-line", "ticker", "karaoke", "minimal"],
             setting_type="enum", default="Multi-line")

        # Context lines
        self.sld_context = ValueSlider(0, 5, 2, " lines", parent=card)
        self.sld_context.valueChanged.connect(lambda v: self._set_setting("context_lines", v))
        form.addRow("Context Lines:", self.sld_context)
        _reg("context_lines", "Context Lines", "Lyrics", "Content",
             "Number of surrounding lyric lines shown", ["context", "surrounding", "lines"])

        # Max lines
        self.sld_max_lines = ValueSlider(3, 20, 8, " lines", parent=card)
        self.sld_max_lines.valueChanged.connect(lambda v: self._set_setting("lyrics_max_lines", v))
        form.addRow("Maximum Lines:", self.sld_max_lines)
        _reg("lyrics_max_lines", "Maximum Lines", "Lyrics", "Content",
             "Maximum number of lyric lines visible at once", ["max", "limit"], advanced=True)

        # Unsynced behavior
        self.cmb_unsynced = QComboBox(card)
        self.cmb_unsynced.addItems(["Show static", "Hide", "Scroll slowly"])
        self.cmb_unsynced.currentTextChanged.connect(lambda v: self._set_setting("lyrics_unsynced_behavior", v))
        form.addRow("Unsynced Lyrics:", self.cmb_unsynced)
        _reg("lyrics_unsynced_behavior", "Unsynced Lyric Behavior", "Lyrics", "Content",
             "How to display lyrics without timing data", ["unsynced", "static", "scroll"])

        # No-lyrics behavior
        self.cmb_no_lyrics = QComboBox(card)
        self.cmb_no_lyrics.addItems(["Show message", "Hide overlay", "Show track info only"])
        self.cmb_no_lyrics.currentTextChanged.connect(lambda v: self._set_setting("lyrics_no_lyrics_behavior", v))
        form.addRow("No Lyrics Found:", self.cmb_no_lyrics)
        _reg("lyrics_no_lyrics_behavior", "No Lyrics Behavior", "Lyrics", "Content",
             "What to show when no lyrics are available", ["no lyrics", "empty", "hide"])

        # Show song info
        self.sw_song_info = ToggleSwitch("Show Song Title & Artist", parent=card)
        self.sw_song_info.toggled.connect(lambda v: self._set_setting("show_song_info", v))
        c_l.addLayout(form)
        c_l.addWidget(self.sw_song_info)
        _reg("show_song_info", "Show Song Info", "Lyrics", "Content",
             "Display track title and artist above lyrics", ["title", "artist", "song info"])

        # Match confidence + manual search
        match_h = QHBoxLayout()
        self.lbl_match_score = QLabel("LRCLIB Match Confidence: 94% (HIGH)", card)
        self.lbl_match_score.setStyleSheet("font-size: 12px; font-weight: 700; color: #2ED573;")
        btn_manual_search = GlassButton("Find / Correct Lyrics...", icon_name="search", parent=card)
        btn_manual_search.clicked.connect(self._open_manual_search)
        match_h.addWidget(self.lbl_match_score)
        match_h.addStretch()
        match_h.addWidget(btn_manual_search)
        c_l.addLayout(match_h)

        # Reset
        rst_h = QHBoxLayout()
        rst_h.addStretch()
        btn_rst = ResetButton("Reset Content", parent=card)
        btn_rst.clicked.connect(lambda: self._reset_section_ui("lyrics_"))
        rst_h.addWidget(btn_rst)
        c_l.addLayout(rst_h)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_lyrics_typography(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        lbl = QLabel("Typography", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        # Active Line
        lbl_a = QLabel("ACTIVE LINE", card)
        lbl_a.setStyleSheet("font-size: 10px; font-weight: 800; color: #2ED573; letter-spacing: 1px; margin-top: 4px;")
        c_l.addWidget(lbl_a)

        form_a = QFormLayout()
        self.cmb_font = QFontComboBox(card)
        self.cmb_font.currentFontChanged.connect(lambda f: self._set_setting("font_family", f.family()))
        form_a.addRow("Font Family:", self.cmb_font)
        _reg("font_family", "Active Line Font", "Lyrics", "Typography",
             "Font used by the currently highlighted lyric line",
             ["font", "typeface", "typography", "active lyric"], setting_type="font")

        self.sld_font_size = ValueSlider(10, 72, 24, "px", parent=card)
        self.sld_font_size.valueChanged.connect(lambda v: self._set_setting("font_size", v))
        form_a.addRow("Font Size:", self.sld_font_size)
        _reg("font_size", "Active Line Font Size", "Lyrics", "Typography",
             "Size in pixels for the active lyric line", ["size", "pixels", "font size"])

        self.sw_font_bold = ToggleSwitch("Bold", parent=card)
        self.sw_font_bold.toggled.connect(lambda v: self._set_setting("font_bold", v))
        form_a.addRow("Weight:", self.sw_font_bold)
        _reg("font_bold", "Active Line Bold", "Lyrics", "Typography",
             "Make the active lyric line bold", ["bold", "weight", "heavy"])

        self.sw_font_italic = ToggleSwitch("Italic", parent=card)
        self.sw_font_italic.toggled.connect(lambda v: self._set_setting("lyrics_active_font_italic", v))
        form_a.addRow("Italic:", self.sw_font_italic)
        _reg("lyrics_active_font_italic", "Active Line Italic", "Lyrics", "Typography",
             "Italicize the active lyric line", ["italic", "slant"])

        c_l.addLayout(form_a)

        # Context Lines
        lbl_c = QLabel("CONTEXT LINES", card)
        lbl_c.setStyleSheet("font-size: 10px; font-weight: 800; color: #38BDF8; letter-spacing: 1px; margin-top: 8px;")
        c_l.addWidget(lbl_c)

        self.cmb_ctx_font_mode = QComboBox(card)
        self.cmb_ctx_font_mode.addItems(["Use Active Line Settings", "Custom"])
        self.cmb_ctx_font_mode.currentTextChanged.connect(lambda v: self._set_setting("lyrics_context_font_mode", v))
        c_l.addWidget(self.cmb_ctx_font_mode)
        _reg("lyrics_context_font_mode", "Context Font Mode", "Lyrics", "Typography",
             "Inherit active line font or use custom settings", ["context", "inherit", "custom"])

        form_c = QFormLayout()
        self.sld_ctx_size = ValueSlider(8, 48, 18, "px", parent=card)
        self.sld_ctx_size.valueChanged.connect(lambda v: self._set_setting("lyrics_context_font_size", v))
        form_c.addRow("Context Size:", self.sld_ctx_size)
        _reg("lyrics_context_font_size", "Context Line Font Size", "Lyrics", "Typography",
             "Font size for surrounding context lines", ["context", "size"])
        c_l.addLayout(form_c)

        # Advanced Typography
        adv = CollapsibleSection("Advanced Typography", collapsed=True, parent=card)
        adv_form = QFormLayout()

        self.sld_line_height = ValueSlider(100, 250, 140, "%", parent=card)
        self.sld_line_height.valueChanged.connect(lambda v: self._set_setting("lyrics_line_height", v / 100.0))
        adv_form.addRow(TooltipLabel("Line Height:", "Vertical spacing between lyric lines.\nIncrease for more breathing room.", card), self.sld_line_height)
        _reg("lyrics_line_height", "Line Height", "Lyrics", "Typography",
             "Vertical spacing between lines", ["line height", "spacing", "leading"], advanced=True)

        self.cmb_case = QComboBox(card)
        self.cmb_case.addItems(["None", "Uppercase", "Lowercase", "Capitalize"])
        self.cmb_case.currentTextChanged.connect(lambda v: self._set_setting("lyrics_case_transform", v))
        adv_form.addRow("Case Transform:", self.cmb_case)
        _reg("lyrics_case_transform", "Case Transform", "Lyrics", "Typography",
             "Force uppercase, lowercase, or title case", ["case", "uppercase", "transform"], advanced=True)

        adv.add_layout(adv_form)
        c_l.addWidget(adv)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_lyrics_layout(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        lbl = QLabel("Layout & Position", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        # Position presets
        lbl_pos = QLabel("POSITION", card)
        lbl_pos.setStyleSheet("font-size: 10px; font-weight: 800; color: #8A8D9B; letter-spacing: 1px;")
        c_l.addWidget(lbl_pos)

        pos_h = QHBoxLayout()
        for pos_name in ["Top", "Bottom", "Center", "Left", "Right"]:
            btn = GlassButton(pos_name, parent=card)
            btn.clicked.connect(lambda _, p=pos_name: self._set_setting("lyrics_position_preset", p))
            pos_h.addWidget(btn)
        pos_h.addStretch()
        c_l.addLayout(pos_h)
        _reg("lyrics_position_preset", "Position", "Lyrics", "Layout",
             "Quick position preset for the lyrics overlay",
             ["position", "top", "bottom", "center", "left", "right"])

        # Alignment
        form = QFormLayout()
        self.cmb_align_h = QComboBox(card)
        self.cmb_align_h.addItems(["Left", "Center", "Right"])
        self.cmb_align_h.currentTextChanged.connect(lambda v: self._set_setting("text_align", v))
        form.addRow("Horizontal Alignment:", self.cmb_align_h)
        _reg("text_align", "Horizontal Alignment", "Lyrics", "Layout",
             "Text alignment within the lyrics overlay", ["alignment", "left", "center", "right"])

        self.cmb_align_v = QComboBox(card)
        self.cmb_align_v.addItems(["Top", "Center", "Bottom"])
        self.cmb_align_v.currentTextChanged.connect(lambda v: self._set_setting("lyrics_alignment_v", v))
        form.addRow("Vertical Alignment:", self.cmb_align_v)
        _reg("lyrics_alignment_v", "Vertical Alignment", "Lyrics", "Layout",
             "Vertical text alignment", ["alignment", "vertical"])

        # Width / Height
        self.sld_width = ValueSlider(200, 2000, 800, "px", parent=card)
        self.sld_width.valueChanged.connect(lambda v: self._set_setting("window_width", v))
        form.addRow("Width:", self.sld_width)
        _reg("window_width", "Overlay Width", "Lyrics", "Layout",
             "Width of the lyrics overlay window", ["width", "size", "window"])

        self.sld_height = ValueSlider(80, 800, 220, "px", parent=card)
        self.sld_height.valueChanged.connect(lambda v: self._set_setting("window_height", v))
        form.addRow("Height:", self.sld_height)
        _reg("window_height", "Overlay Height", "Lyrics", "Layout",
             "Height of the lyrics overlay window", ["height", "size", "window"])

        c_l.addLayout(form)

        # Auto resize
        self.sw_auto_resize = ToggleSwitch("Auto-resize height based on content", parent=card)
        self.sw_auto_resize.toggled.connect(lambda v: self._set_setting("auto_resize_height", v))
        c_l.addWidget(self.sw_auto_resize)
        _reg("auto_resize_height", "Auto Resize Height", "Lyrics", "Layout",
             "Automatically adjust overlay height to fit visible lines", ["auto", "resize", "fit"])

        # Advanced layout
        adv = CollapsibleSection("Advanced Layout", collapsed=True, parent=card)
        adv_form = QFormLayout()

        self.sld_padding = ValueSlider(0, 40, 12, "px", parent=card)
        self.sld_padding.valueChanged.connect(lambda v: self._set_setting("lyrics_padding", v))
        adv_form.addRow("Padding:", self.sld_padding)
        _reg("lyrics_padding", "Padding", "Lyrics", "Layout",
             "Inner padding of the lyrics overlay", ["padding", "spacing"], advanced=True)

        self.sw_snap = ToggleSwitch("Snap to screen edges", parent=card)
        self.sw_snap.toggled.connect(lambda v: self._set_setting("snap_to_corners", v))
        adv_form.addRow("Snap:", self.sw_snap)
        _reg("snap_to_corners", "Snap to Edges", "Lyrics", "Layout",
             "Snap the overlay to screen edges when dragging", ["snap", "edge", "corner"], advanced=True)

        self.sw_lock = ToggleSwitch("Lock position", parent=card)
        self.sw_lock.toggled.connect(lambda v: self._set_setting("lock_position", v))
        adv_form.addRow("Lock:", self.sw_lock)
        _reg("lock_position", "Lock Position", "Lyrics", "Layout",
             "Prevent accidental overlay movement", ["lock", "position", "drag"], advanced=True)

        adv.add_layout(adv_form)
        c_l.addWidget(adv)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_lyrics_appearance(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        lbl = QLabel("Appearance & Effects", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        # Colors
        lbl_col = QLabel("COLORS", card)
        lbl_col.setStyleSheet("font-size: 10px; font-weight: 800; color: #8A8D9B; letter-spacing: 1px;")
        c_l.addWidget(lbl_col)

        form_c = QFormLayout()
        self.btn_active_color = ColorSwatchButton("#FFFFFF", card)
        self.btn_active_color.colorChanged.connect(lambda c: self._set_setting("text_color", c))
        form_c.addRow("Active Line:", self.btn_active_color)
        _reg("text_color", "Active Line Color", "Lyrics", "Appearance",
             "Color of the currently active lyric line", ["color", "active", "text"])

        self.btn_ctx_color = ColorSwatchButton("#888888", card)
        self.btn_ctx_color.colorChanged.connect(lambda c: self._set_setting("lyrics_context_color", c))
        form_c.addRow("Context Lines:", self.btn_ctx_color)
        _reg("lyrics_context_color", "Context Line Color", "Lyrics", "Appearance",
             "Color of surrounding context lines", ["color", "context"])

        self.btn_bg_color = ColorSwatchButton("#000000", card)
        self.btn_bg_color.colorChanged.connect(lambda c: self._set_setting("bg_color", c))
        form_c.addRow("Background:", self.btn_bg_color)
        _reg("bg_color", "Background Color", "Lyrics", "Appearance",
             "Background color of the lyrics overlay", ["background", "color", "bg"])
        c_l.addLayout(form_c)

        # Color Mode
        form_m = QFormLayout()
        self.cmb_color_mode = QComboBox(card)
        self.cmb_color_mode.addItems(["Manual", "Dynamic Album Accent", "Follow Global Theme"])
        self.cmb_color_mode.currentTextChanged.connect(lambda v: self._set_setting("lyrics_color_mode", v))
        form_m.addRow("Color Mode:", self.cmb_color_mode)
        _reg("lyrics_color_mode", "Color Mode", "Lyrics", "Appearance",
             "How lyric colors are determined", ["color mode", "dynamic", "accent", "theme"])
        c_l.addLayout(form_m)

        # Opacity
        lbl_op = QLabel("OPACITY", card)
        lbl_op.setStyleSheet("font-size: 10px; font-weight: 800; color: #8A8D9B; letter-spacing: 1px; margin-top: 6px;")
        c_l.addWidget(lbl_op)

        form_o = QFormLayout()
        self.sld_active_op = ValueSlider(0, 100, 100, "%", parent=card)
        self.sld_active_op.valueChanged.connect(lambda v: self._set_setting("active_line_opacity", v))
        form_o.addRow("Active Line:", self.sld_active_op)
        _reg("active_line_opacity", "Active Line Opacity", "Lyrics", "Appearance",
             "Opacity of the active lyric line", ["opacity", "active", "transparency"])

        self.sld_ctx_op = ValueSlider(0, 100, 45, "%", parent=card)
        self.sld_ctx_op.valueChanged.connect(lambda v: self._set_setting("context_line_opacity", v))
        form_o.addRow("Context Lines:", self.sld_ctx_op)
        _reg("context_line_opacity", "Context Line Opacity", "Lyrics", "Appearance",
             "Opacity of context lines", ["opacity", "context", "transparency"])

        self.sld_bg_op = ValueSlider(0, 100, 0, "%", parent=card)
        self.sld_bg_op.valueChanged.connect(lambda v: self._set_setting("bg_opacity", v))
        form_o.addRow("Background:", self.sld_bg_op)
        _reg("bg_opacity", "Background Opacity", "Lyrics", "Appearance",
             "Opacity of the overlay background", ["opacity", "background", "transparency"])
        c_l.addLayout(form_o)

        # Effects: Shadow
        lbl_fx = QLabel("EFFECTS", card)
        lbl_fx.setStyleSheet("font-size: 10px; font-weight: 800; color: #8A8D9B; letter-spacing: 1px; margin-top: 6px;")
        c_l.addWidget(lbl_fx)

        self.sw_shadow = ToggleSwitch("Text Shadow", parent=card)
        self.sw_shadow.toggled.connect(lambda v: self._set_setting_and_update_visibility("shadow_enabled", v))
        c_l.addWidget(self.sw_shadow)
        _reg("shadow_enabled", "Text Shadow", "Lyrics", "Appearance",
             "Add a drop shadow behind lyric text", ["shadow", "drop shadow"])

        self._shadow_controls = QWidget(card)
        sh_form = QFormLayout(self._shadow_controls)
        sh_form.setContentsMargins(16, 0, 0, 0)
        self.sld_shadow_blur = ValueSlider(0, 30, 8, "px", parent=card)
        self.sld_shadow_blur.valueChanged.connect(lambda v: self._set_setting("shadow_blur", v))
        sh_form.addRow("Blur:", self.sld_shadow_blur)
        _reg("shadow_blur", "Shadow Blur", "Lyrics", "Appearance",
             "Blur radius of the text shadow", ["shadow", "blur", "radius"],
             depends_on="shadow_enabled", advanced=True)
        self.btn_shadow_color = ColorSwatchButton("#000000", card)
        self.btn_shadow_color.colorChanged.connect(lambda c: self._set_setting("shadow_color", c))
        sh_form.addRow("Color:", self.btn_shadow_color)
        _reg("shadow_color", "Shadow Color", "Lyrics", "Appearance",
             "Color of the text shadow", ["shadow", "color"], depends_on="shadow_enabled", advanced=True)
        c_l.addWidget(self._shadow_controls)

        # Effects: Outline
        self.sw_outline = ToggleSwitch("Text Outline", parent=card)
        self.sw_outline.toggled.connect(lambda v: self._set_setting_and_update_visibility("active_text_outline", v))
        c_l.addWidget(self.sw_outline)
        _reg("active_text_outline", "Text Outline", "Lyrics", "Appearance",
             "Add an outline stroke around lyric text", ["outline", "stroke", "border"])

        # Effects: Glow
        self.sw_glow = ToggleSwitch("Text Glow", parent=card)
        self.sw_glow.toggled.connect(lambda v: self._set_setting_and_update_visibility("lyrics_glow_enabled", v))
        c_l.addWidget(self.sw_glow)
        _reg("lyrics_glow_enabled", "Text Glow", "Lyrics", "Appearance",
             "Add a luminous glow around lyric text", ["glow", "luminous", "neon"])

        self._glow_controls = QWidget(card)
        gl_form = QFormLayout(self._glow_controls)
        gl_form.setContentsMargins(16, 0, 0, 0)
        self.sld_glow_radius = ValueSlider(2, 40, 12, "px", parent=card)
        self.sld_glow_radius.valueChanged.connect(lambda v: self._set_setting("lyrics_glow_radius", v))
        gl_form.addRow("Radius:", self.sld_glow_radius)
        _reg("lyrics_glow_radius", "Glow Radius", "Lyrics", "Appearance",
             "Size of the glow effect", ["glow", "radius", "size"],
             depends_on="lyrics_glow_enabled", advanced=True)
        self.btn_glow_color = ColorSwatchButton("#2ED573", card)
        self.btn_glow_color.colorChanged.connect(lambda c: self._set_setting("lyrics_glow_color", c))
        gl_form.addRow("Color:", self.btn_glow_color)
        _reg("lyrics_glow_color", "Glow Color", "Lyrics", "Appearance",
             "Color of the glow effect", ["glow", "color"],
             depends_on="lyrics_glow_enabled", advanced=True)
        c_l.addWidget(self._glow_controls)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_lyrics_animation(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        lbl = QLabel("Animation", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        form = QFormLayout()
        self.cmb_anim_preset = QComboBox(card)
        self.cmb_anim_preset.addItems(["Smooth", "Fast", "Cinematic", "Off"])
        self.cmb_anim_preset.currentTextChanged.connect(lambda v: self._set_setting("lyrics_animation_preset", v))
        form.addRow("Animation Preset:", self.cmb_anim_preset)
        _reg("lyrics_animation_preset", "Animation Preset", "Lyrics", "Animation",
             "Pre-configured animation behavior", ["animation", "preset", "smooth", "fast", "cinematic"])

        self.sld_anim_speed = ValueSlider(50, 1200, 400, "ms", parent=card)
        self.sld_anim_speed.valueChanged.connect(lambda v: self._set_setting("animation_speed_ms", v))
        form.addRow("Scroll Duration:", self.sld_anim_speed)
        _reg("animation_speed_ms", "Scroll Duration", "Lyrics", "Animation",
             "Duration of the scroll animation in milliseconds", ["animation", "speed", "duration", "scroll"])

        self.sw_reduced_motion_lyrics = ToggleSwitch("Reduced Motion", parent=card)
        self.sw_reduced_motion_lyrics.toggled.connect(lambda v: self._set_setting("lyrics_reduced_motion", v))
        c_l.addLayout(form)
        c_l.addWidget(self.sw_reduced_motion_lyrics)
        _reg("lyrics_reduced_motion", "Reduced Motion (Lyrics)", "Lyrics", "Animation",
             "Minimize animation for accessibility", ["reduced motion", "accessibility", "less animation"])

        # Advanced animation
        adv = CollapsibleSection("Advanced Animation", collapsed=True, parent=card)
        adv_form = QFormLayout()

        self.cmb_easing = QComboBox(card)
        self.cmb_easing.addItems(["OutCubic", "Linear", "OutQuint", "InOutCubic"])
        self.cmb_easing.currentTextChanged.connect(lambda v: self._set_setting("lyrics_scroll_easing", v))
        adv_form.addRow(TooltipLabel("Easing:", "Controls the acceleration curve of scroll animations.", card), self.cmb_easing)
        _reg("lyrics_scroll_easing", "Scroll Easing", "Lyrics", "Animation",
             "Acceleration curve for scroll animations", ["easing", "curve", "acceleration"], advanced=True)

        self.cmb_track_trans = QComboBox(card)
        self.cmb_track_trans.addItems(["Fade", "Scroll", "Instant"])
        self.cmb_track_trans.currentTextChanged.connect(lambda v: self._set_setting("lyrics_track_change_transition", v))
        adv_form.addRow("Track Change:", self.cmb_track_trans)
        _reg("lyrics_track_change_transition", "Track Change Transition", "Lyrics", "Animation",
             "How lyrics transition when the track changes", ["track change", "transition"], advanced=True)

        adv.add_layout(adv_form)
        c_l.addWidget(adv)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_lyrics_sync(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        lbl = QLabel("Synchronization", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        # Global offset
        lbl_sync = QLabel("Global Timing Offset (milliseconds):", card)
        lbl_sync.setStyleSheet("font-size: 11px; font-weight: 600; color: #8A8D9B;")
        c_l.addWidget(lbl_sync)

        self.sld_sync = ValueSlider(-5000, 5000, 0, "ms", parent=card)
        self.sld_sync.valueChanged.connect(lambda v: self._set_setting("sync_offset_ms", v))
        c_l.addWidget(self.sld_sync)
        _reg("sync_offset_ms", "Global Sync Offset", "Lyrics", "Sync",
             "Global timing offset for lyric synchronization",
             ["sync", "offset", "timing", "delay", "lyrics sync"])

        # Nudge buttons
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

        # Advanced sync
        adv = CollapsibleSection("Advanced Synchronization", collapsed=True, parent=card)

        self.sw_auto_drift = ToggleSwitch("Automatic Drift Correction", parent=card)
        self.sw_auto_drift.toggled.connect(lambda v: self._set_setting("lyrics_auto_drift_correction", v))
        adv.add_widget(self.sw_auto_drift)
        _reg("lyrics_auto_drift_correction", "Auto Drift Correction", "Lyrics", "Sync",
             "Automatically compensate for playback drift", ["drift", "auto", "correction"], advanced=True)

        self.sw_lrc_offset = ToggleSwitch("Use LRC Metadata Offset", parent=card)
        self.sw_lrc_offset.toggled.connect(lambda v: self._set_setting("lyrics_lrc_metadata_offset", v))
        adv.add_widget(self.sw_lrc_offset)
        _reg("lyrics_lrc_metadata_offset", "LRC Metadata Offset", "Lyrics", "Sync",
             "Apply timing offset embedded in LRC file metadata", ["lrc", "metadata", "offset"], advanced=True)

        c_l.addWidget(adv)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_lyrics_behavior(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        lbl = QLabel("Overlay Behavior", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        self.sw_topmost = ToggleSwitch("Always on Top", parent=card)
        self.sw_topmost.toggled.connect(lambda v: self._set_setting("always_on_top", v))
        c_l.addWidget(self.sw_topmost)
        _reg("always_on_top", "Always on Top", "Lyrics", "Behavior",
             "Keep lyrics overlay above all desktop windows", ["topmost", "always on top", "above"])

        self.sw_click_thru = ToggleSwitch("Click-Through Mode", parent=card)
        self.sw_click_thru.toggled.connect(lambda v: self._set_setting("click_through", v))
        c_l.addWidget(self.sw_click_thru)
        _reg("click_through", "Click Through", "Lyrics", "Behavior",
             "Pass mouse clicks through to desktop/games", ["click through", "transparent", "mouse"])

        self.sw_exclude_cap = ToggleSwitch("Exclude from Screen Capture", parent=card)
        self.sw_exclude_cap.toggled.connect(lambda v: self._set_setting("exclude_from_capture", v))
        c_l.addWidget(self.sw_exclude_cap)
        _reg("exclude_from_capture", "Screen Capture Exclusion", "Lyrics", "Behavior",
             "Hide from OBS / Discord screen captures", ["capture", "obs", "discord", "screen", "exclude"])

        self.sw_auto_hide = ToggleSwitch("Auto-hide when paused", parent=card)
        self.sw_auto_hide.toggled.connect(lambda v: self._set_setting("auto_hide_on_pause", v))
        c_l.addWidget(self.sw_auto_hide)
        _reg("auto_hide_on_pause", "Auto Hide on Pause", "Lyrics", "Behavior",
             "Automatically hide lyrics when playback is paused", ["auto hide", "pause", "hide"])

        self.sw_hide_stop = ToggleSwitch("Hide when stopped", parent=card)
        self.sw_hide_stop.toggled.connect(lambda v: self._set_setting("lyrics_hide_on_stop", v))
        c_l.addWidget(self.sw_hide_stop)
        _reg("lyrics_hide_on_stop", "Hide on Stop", "Lyrics", "Behavior",
             "Hide overlay when media playback stops", ["hide", "stop"])

        form = QFormLayout()
        self.sld_hide_delay = ValueSlider(1, 30, 5, "sec", parent=card)
        self.sld_hide_delay.valueChanged.connect(lambda v: self._set_setting("auto_hide_delay_sec", v))
        form.addRow("Hide Timeout:", self.sld_hide_delay)
        _reg("auto_hide_delay_sec", "Hide Timeout", "Lyrics", "Behavior",
             "Seconds before auto-hiding", ["timeout", "delay", "seconds"])
        c_l.addLayout(form)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ 3: WALLPAPER — 8 Subsections                                       ║
    # ╚══════════════════════════════════════════════════════════════════════╝

    def _build_page_wallpaper(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # Top bar with Enable Switch (always visible)
        top_h = QHBoxLayout()
        lbl_t = QLabel("Wallpaper Studio", page)
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        self.sw_wallpaper = ToggleSwitch("Enable Dynamic Desktop Wallpaper", parent=page)
        self.sw_wallpaper.toggled.connect(lambda v: self._set_setting("wallpaper_enabled", v))
        top_h.addWidget(lbl_t)
        top_h.addStretch()
        top_h.addWidget(self.sw_wallpaper)
        layout.addLayout(top_h)

        # Interactive Canvas (always visible at top)
        self.wp_canvas = WallpaperPreviewWidget(page)
        self.wp_canvas.setFixedHeight(200)
        self.wp_canvas.vinyl_position_changed.connect(self._on_wp_pos_changed)
        self.wp_canvas.vinyl_size_changed.connect(self._on_wp_size_changed)
        layout.addWidget(self.wp_canvas)

        # Subsection tabs + stack
        tabs = SubSectionTabs(self.PAGE_SUBSECTIONS["Wallpaper"], parent=page)
        self._subsection_tabs["Wallpaper"] = tabs
        layout.addWidget(tabs)

        sub_stack = QStackedWidget(page)
        self._subsection_stacks["Wallpaper"] = sub_stack

        sub_stack.addWidget(self._build_wp_canvas())
        sub_stack.addWidget(self._build_wp_background())
        sub_stack.addWidget(self._build_wp_vinyl())
        sub_stack.addWidget(self._build_wp_text())
        sub_stack.addWidget(self._build_wp_lyrics())
        sub_stack.addWidget(self._build_wp_visualizer())
        sub_stack.addWidget(self._build_wp_layers())
        sub_stack.addWidget(self._build_wp_behavior())

        tabs.tabChanged.connect(sub_stack.setCurrentIndex)
        layout.addWidget(sub_stack, 1)
        return page

    def _build_wp_canvas(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        form = QFormLayout()
        self.cmb_wp_display = QComboBox(card)
        for opt in get_wallpaper_display_options():
            self.cmb_wp_display.addItem(opt)
        self.cmb_wp_display.currentTextChanged.connect(lambda v: self._set_setting("wallpaper_display_mode", v))
        form.addRow("Target Monitor:", self.cmb_wp_display)
        _reg("wallpaper_display_mode", "Target Monitor", "Wallpaper", "Canvas",
             "Which monitor to render the wallpaper on", ["monitor", "display", "screen"])

        self.sw_wp_guides = ToggleSwitch("Show Guides", parent=card)
        self.sw_wp_guides.toggled.connect(lambda v: self._set_setting("wallpaper_canvas_guides", v))
        self.sw_wp_grid = ToggleSwitch("Show Grid", parent=card)
        self.sw_wp_grid.toggled.connect(lambda v: self._set_setting("wallpaper_canvas_grid", v))
        self.sw_wp_snap = ToggleSwitch("Snap to Grid", parent=card)
        self.sw_wp_snap.toggled.connect(lambda v: self._set_setting("wallpaper_canvas_snap", v))
        self.sw_wp_coords = ToggleSwitch("Show Coordinates", parent=card)
        self.sw_wp_coords.toggled.connect(lambda v: self._set_setting("wallpaper_canvas_coordinates", v))

        c_l.addLayout(form)
        c_l.addWidget(self.sw_wp_guides)
        c_l.addWidget(self.sw_wp_grid)
        c_l.addWidget(self.sw_wp_snap)
        c_l.addWidget(self.sw_wp_coords)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_wp_background(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        form = QFormLayout()
        self.cmb_wp_type = QComboBox(card)
        self.cmb_wp_type.addItems(["static", "video"])
        self.cmb_wp_type.currentTextChanged.connect(lambda v: self._set_setting_and_update_visibility("wallpaper_type", v))
        form.addRow("Source Type:", self.cmb_wp_type)
        _reg("wallpaper_type", "Wallpaper Type", "Wallpaper", "Background",
             "Static image or video background", ["type", "image", "video", "static"])

        self.cmb_wp_scaling = QComboBox(card)
        self.cmb_wp_scaling.addItems(["fill", "fit", "stretch", "center"])
        self.cmb_wp_scaling.currentTextChanged.connect(self._on_wp_scaling_changed)
        form.addRow("Scaling Mode:", self.cmb_wp_scaling)
        _reg("wallpaper_scaling_mode", "Scaling Mode", "Wallpaper", "Background",
             "How the image fills the screen", ["scaling", "fill", "fit", "stretch", "center"])

        self.sld_wp_brightness = ValueSlider(0, 200, 100, "%", parent=card)
        self.sld_wp_brightness.valueChanged.connect(lambda v: self._set_setting("wallpaper_brightness", v))
        form.addRow("Brightness:", self.sld_wp_brightness)
        _reg("wallpaper_brightness", "Brightness", "Wallpaper", "Background",
             "Background brightness adjustment", ["brightness", "light", "dark"])

        self.sld_wp_blur = ValueSlider(0, 50, 0, "px", parent=card)
        self.sld_wp_blur.valueChanged.connect(lambda v: self._set_setting("wallpaper_blur", v))
        form.addRow("Blur:", self.sld_wp_blur)
        _reg("wallpaper_blur", "Background Blur", "Wallpaper", "Background",
             "Apply blur to the wallpaper background", ["blur", "gaussian"])

        c_l.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_wp_vinyl(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        # Presets
        top_h = QHBoxLayout()
        lbl = QLabel("Vinyl Record", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        top_h.addWidget(lbl)
        top_h.addStretch()
        preset = PresetSelector(WALLPAPER_PRESETS, parent=card)
        preset.presetSelected.connect(lambda n: self._apply_domain_preset("wallpaper", n))
        top_h.addWidget(preset)
        c_l.addLayout(top_h)

        # Alignment toolbar
        align_h = QHBoxLayout()
        btn_al = GlassButton("Align Left", parent=card)
        btn_al.clicked.connect(lambda: self._align_vinyl(0.20, None))
        btn_ac = GlassButton("Center", parent=card)
        btn_ac.clicked.connect(lambda: self._align_vinyl(0.50, 0.50))
        btn_ar = GlassButton("Align Right", parent=card)
        btn_ar.clicked.connect(lambda: self._align_vinyl(0.78, None))
        align_h.addWidget(btn_al)
        align_h.addWidget(btn_ac)
        align_h.addWidget(btn_ar)
        align_h.addStretch()
        c_l.addLayout(align_h)

        # Transform
        form = QFormLayout()
        self.sld_vinyl_size = ValueSlider(5, 60, 20, "%", parent=card)
        self.sld_vinyl_size.valueChanged.connect(lambda v: self._set_setting("wallpaper_vinyl_size", v / 100.0))
        form.addRow("Size:", self.sld_vinyl_size)
        _reg("wallpaper_vinyl_size", "Vinyl Size", "Wallpaper", "Vinyl",
             "Diameter of the vinyl record", ["vinyl", "size", "diameter", "record"])

        self.sld_vinyl_op = ValueSlider(0, 100, 100, "%", parent=card)
        self.sld_vinyl_op.valueChanged.connect(lambda v: self._set_setting("wallpaper_vinyl_opacity", v))
        form.addRow("Opacity:", self.sld_vinyl_op)
        _reg("wallpaper_vinyl_opacity", "Vinyl Opacity", "Wallpaper", "Vinyl",
             "Transparency of the vinyl record", ["vinyl", "opacity", "transparency"])

        self.sld_vinyl_speed = ValueSlider(1, 60, 12, "s/rev", parent=card)
        self.sld_vinyl_speed.valueChanged.connect(lambda v: self._set_setting("wallpaper_rotation_speed", float(v)))
        form.addRow("Rotation Speed:", self.sld_vinyl_speed)
        _reg("wallpaper_rotation_speed", "Rotation Speed", "Wallpaper", "Vinyl",
             "Seconds per full revolution", ["rotation", "speed", "spin", "rpm"])
        c_l.addLayout(form)

        # Advanced Vinyl
        adv = CollapsibleSection("Advanced Vinyl", collapsed=True, parent=card)

        self.sw_vinyl_shadow = ToggleSwitch("Shadow", parent=card)
        self.sw_vinyl_shadow.toggled.connect(lambda v: self._set_setting("wallpaper_vinyl_shadow", v))
        adv.add_widget(self.sw_vinyl_shadow)
        _reg("wallpaper_vinyl_shadow", "Vinyl Shadow", "Wallpaper", "Vinyl",
             "Drop shadow behind the vinyl record", ["vinyl", "shadow"], advanced=True)

        self.sw_vinyl_glow = ToggleSwitch("Glow", parent=card)
        self.sw_vinyl_glow.toggled.connect(lambda v: self._set_setting("wallpaper_vinyl_glow", v))
        adv.add_widget(self.sw_vinyl_glow)
        _reg("wallpaper_vinyl_glow", "Vinyl Glow", "Wallpaper", "Vinyl",
             "Luminous glow around the vinyl record", ["vinyl", "glow", "neon"], advanced=True)

        self.sw_vinyl_reactive = ToggleSwitch("Audio Reactive", parent=card)
        self.sw_vinyl_reactive.toggled.connect(lambda v: self._set_setting_and_update_visibility("wallpaper_vinyl_audio_reactive", v))
        adv.add_widget(self.sw_vinyl_reactive)
        _reg("wallpaper_vinyl_audio_reactive", "Audio Reactivity", "Wallpaper", "Vinyl",
             "Make vinyl respond to music beats", ["vinyl", "audio", "reactive", "beat", "bass"], advanced=True)

        self._vinyl_reactive_controls = QWidget(card)
        vr_form = QFormLayout(self._vinyl_reactive_controls)
        vr_form.setContentsMargins(16, 0, 0, 0)
        self.sld_vinyl_bass = ValueSlider(0, 100, 50, "%", parent=card)
        self.sld_vinyl_bass.valueChanged.connect(lambda v: self._set_setting("wallpaper_vinyl_bass_response", v))
        vr_form.addRow("Bass Response:", self.sld_vinyl_bass)
        _reg("wallpaper_vinyl_bass_response", "Bass Response", "Wallpaper", "Vinyl",
             "How strongly vinyl reacts to bass frequencies",
             ["bass", "response", "reactivity"], depends_on="wallpaper_vinyl_audio_reactive", advanced=True)
        adv.add_widget(self._vinyl_reactive_controls)

        c_l.addWidget(adv)
        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_wp_text(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        lbl = QLabel("Title & Artist Text", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        self.sw_wp_title = ToggleSwitch("Show Title", parent=card)
        self.sw_wp_title.toggled.connect(lambda v: self._set_setting("wallpaper_show_title", v))
        c_l.addWidget(self.sw_wp_title)
        _reg("wallpaper_show_title", "Show Title", "Wallpaper", "Text",
             "Display the song title on the wallpaper", ["title", "show", "visibility"])

        self.sw_wp_artist = ToggleSwitch("Show Artist", parent=card)
        self.sw_wp_artist.toggled.connect(lambda v: self._set_setting("wallpaper_show_artist", v))
        c_l.addWidget(self.sw_wp_artist)
        _reg("wallpaper_show_artist", "Show Artist", "Wallpaper", "Text",
             "Display the artist name on the wallpaper", ["artist", "show", "visibility"])

        form = QFormLayout()
        self.cmb_wp_text_pos = QComboBox(card)
        self.cmb_wp_text_pos.addItems(["Below", "Above", "Left", "Right", "Hidden"])
        self.cmb_wp_text_pos.currentTextChanged.connect(lambda v: self._set_setting("wallpaper_text_position", v))
        form.addRow("Position:", self.cmb_wp_text_pos)
        _reg("wallpaper_text_position", "Text Position", "Wallpaper", "Text",
             "Where to display title and artist relative to vinyl", ["position", "text", "below", "above"])

        self.cmb_wp_text_align = QComboBox(card)
        self.cmb_wp_text_align.addItems(["Center", "Left", "Right"])
        self.cmb_wp_text_align.currentTextChanged.connect(lambda v: self._set_setting("wallpaper_text_alignment", v))
        form.addRow("Alignment:", self.cmb_wp_text_align)
        _reg("wallpaper_text_alignment", "Text Alignment", "Wallpaper", "Text",
             "Text alignment for title and artist", ["alignment", "text"])

        self.btn_wp_text_color = ColorSwatchButton("#FFFFFF", card)
        self.btn_wp_text_color.colorChanged.connect(lambda c: self._set_setting("wallpaper_text_color", c))
        form.addRow("Color:", self.btn_wp_text_color)
        _reg("wallpaper_text_color", "Text Color", "Wallpaper", "Text",
             "Color for wallpaper title and artist text", ["color", "text", "wallpaper"])

        c_l.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_wp_lyrics(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        self.sw_wp_lyrics = ToggleSwitch("Enable Lyrics on Wallpaper", parent=card)
        self.sw_wp_lyrics.toggled.connect(lambda v: self._set_setting("wallpaper_lyrics_enabled", v))
        c_l.addWidget(self.sw_wp_lyrics)
        _reg("wallpaper_lyrics_enabled", "Wallpaper Lyrics", "Wallpaper", "Lyrics",
             "Show lyrics overlay embedded in the wallpaper", ["lyrics", "wallpaper", "enable"])

        form = QFormLayout()
        self.sld_wp_lyrics_size = ValueSlider(10, 48, 18, "px", parent=card)
        self.sld_wp_lyrics_size.valueChanged.connect(lambda v: self._set_setting("wallpaper_lyrics_font_size", v))
        form.addRow("Font Size:", self.sld_wp_lyrics_size)

        self.sld_wp_lyrics_op = ValueSlider(0, 100, 100, "%", parent=card)
        self.sld_wp_lyrics_op.valueChanged.connect(lambda v: self._set_setting("wallpaper_lyrics_opacity", v))
        form.addRow("Opacity:", self.sld_wp_lyrics_op)
        c_l.addLayout(form)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_wp_visualizer(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        self.sw_wp_vis = ToggleSwitch("Enable Visualizer on Wallpaper", parent=card)
        self.sw_wp_vis.toggled.connect(lambda v: self._set_setting("wallpaper_visualizer_enabled", v))
        c_l.addWidget(self.sw_wp_vis)
        _reg("wallpaper_visualizer_enabled", "Wallpaper Visualizer", "Wallpaper", "Visualizer",
             "Embed an audio visualizer in the wallpaper", ["visualizer", "wallpaper", "embed"])

        form = QFormLayout()
        self.sld_wp_vis_op = ValueSlider(0, 100, 80, "%", parent=card)
        self.sld_wp_vis_op.valueChanged.connect(lambda v: self._set_setting("wallpaper_visualizer_opacity", v))
        form.addRow("Opacity:", self.sld_wp_vis_op)
        c_l.addLayout(form)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_wp_layers(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        lbl = QLabel("Layer Order (Top = Front)", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        self.list_layers = QListWidget(card)
        self.list_layers.setFixedHeight(200)
        self.list_layers.setStyleSheet("""
            QListWidget { background: rgba(24,28,38,0.65); border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px; padding: 4px; color: #FFFFFF; }
            QListWidget::item { padding: 6px 10px; border-radius: 6px; }
            QListWidget::item:selected { background: rgba(46,213,115,0.22); color: #2ED573; }
        """)
        for layer in reversed(self.working_settings.get("wallpaper_layer_order", [])):
            self.list_layers.addItem(layer)
        c_l.addWidget(self.list_layers)
        _reg("wallpaper_layer_order", "Layer Order", "Wallpaper", "Layers",
             "Z-order of wallpaper scene elements", ["layer", "order", "z-order", "stack"])

        btn_h = QHBoxLayout()
        btn_fwd = GlassButton("Bring Forward", parent=card)
        btn_fwd.clicked.connect(self._layer_move_up)
        btn_bck = GlassButton("Send Backward", parent=card)
        btn_bck.clicked.connect(self._layer_move_down)
        btn_h.addWidget(btn_fwd)
        btn_h.addWidget(btn_bck)
        btn_h.addStretch()
        c_l.addLayout(btn_h)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_wp_behavior(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        self.sw_wp_pause_battery = ToggleSwitch("Pause on Battery", parent=card)
        self.sw_wp_pause_battery.toggled.connect(lambda v: self._set_setting("wallpaper_pause_on_battery", v))
        c_l.addWidget(self.sw_wp_pause_battery)
        _reg("wallpaper_pause_on_battery", "Pause on Battery", "Wallpaper", "Behavior",
             "Pause wallpaper engine when on battery power", ["battery", "pause", "power"])

        self.sw_wp_pause_fs = ToggleSwitch("Pause on Fullscreen", parent=card)
        self.sw_wp_pause_fs.toggled.connect(lambda v: self._set_setting("wallpaper_pause_on_fullscreen", v))
        c_l.addWidget(self.sw_wp_pause_fs)
        _reg("wallpaper_pause_on_fullscreen", "Pause on Fullscreen", "Wallpaper", "Behavior",
             "Pause when a fullscreen app is active", ["fullscreen", "pause", "game"])

        form = QFormLayout()
        self.sld_wp_fps = ValueSlider(10, 60, 30, " FPS", parent=card)
        self.sld_wp_fps.valueChanged.connect(lambda v: self._set_setting("wallpaper_fps", v))
        form.addRow("Render FPS:", self.sld_wp_fps)
        _reg("wallpaper_fps", "Wallpaper FPS", "Wallpaper", "Behavior",
             "Frame rate for the wallpaper renderer", ["fps", "frame rate", "performance"])
        c_l.addLayout(form)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ 4: VISUALIZER — 8 Subsections                                      ║
    # ╚══════════════════════════════════════════════════════════════════════╝

    def _build_page_visualizer(self) -> QWidget:
        return self._build_subsection_page("Visualizer",
            self.PAGE_SUBSECTIONS["Visualizer"],
            [
                self._build_vis_preview,
                self._build_vis_audio,
                self._build_vis_bars,
                self._build_vis_color,
                self._build_vis_effects,
                self._build_vis_position,
                self._build_vis_game_overlay,
                self._build_vis_behavior,
            ]
        )

    def _build_vis_preview(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        top_h = QHBoxLayout()
        lbl = QLabel("Visualizer Preview", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        self.sw_vis_enable = ToggleSwitch("Enable Audio Visualizer", parent=card)
        self.sw_vis_enable.toggled.connect(lambda v: self._set_setting("visualizer_enabled", v))
        top_h.addWidget(lbl)
        top_h.addStretch()
        top_h.addWidget(self.sw_vis_enable)
        c_l.addLayout(top_h)
        _reg("visualizer_enabled", "Enable Visualizer", "Visualizer", "Preview",
             "Master toggle for the standalone audio visualizer", ["enable", "visualizer", "toggle"])

        # Preset
        preset = PresetSelector(VISUALIZER_PRESETS, parent=card)
        preset.presetSelected.connect(lambda n: self._apply_domain_preset("visualizer", n))
        c_l.addWidget(preset)

        self.vis_preview = VisualizerPreviewWidget(card)
        c_l.addWidget(self.vis_preview)

        mode_h = QHBoxLayout()
        self.seg_vis_preview = SegmentedSwitch([("play", "Demo Mode"), ("visualizer", "Live Audio Mode")], parent=card)
        self.seg_vis_preview.switched.connect(lambda idx: self.vis_preview.set_preview_mode("Live Audio" if idx == 1 else "Demo"))
        mode_h.addWidget(self.seg_vis_preview)
        mode_h.addStretch()
        c_l.addLayout(mode_h)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_vis_audio(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        lbl = QLabel("Audio Source & Processing", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        form = QFormLayout()
        self.sld_vis_sensitivity = ValueSlider(10, 200, 100, "%", parent=card)
        self.sld_vis_sensitivity.valueChanged.connect(lambda v: self._set_setting("visualizer_sensitivity", v))
        form.addRow("Sensitivity:", self.sld_vis_sensitivity)
        _reg("visualizer_sensitivity", "Sensitivity", "Visualizer", "Audio",
             "How responsive the visualizer is to audio", ["sensitivity", "responsive", "gain"])

        self.sld_vis_smooth = ValueSlider(0, 100, 75, "%", parent=card)
        self.sld_vis_smooth.valueChanged.connect(lambda v: self._set_setting("visualizer_smoothing", v))
        form.addRow("Smoothing:", self.sld_vis_smooth)
        _reg("visualizer_smoothing", "Smoothing", "Visualizer", "Audio",
             "Temporal smoothing of frequency data", ["smoothing", "smooth", "temporal"])

        c_l.addLayout(form)

        # Advanced DSP
        adv = CollapsibleSection("Advanced DSP", collapsed=True, parent=card)
        adv_form = QFormLayout()

        self.cmb_vis_fft = QComboBox(card)
        self.cmb_vis_fft.addItems(["512", "1024", "2048", "4096"])
        self.cmb_vis_fft.currentTextChanged.connect(lambda v: self._set_setting("visualizer_fft_size", int(v)))
        adv_form.addRow(TooltipLabel("FFT Size:", "Larger values give more frequency resolution\nbut slower response time.", card), self.cmb_vis_fft)
        _reg("visualizer_fft_size", "FFT Size", "Visualizer", "Audio",
             "FFT window size for frequency analysis", ["fft", "frequency", "analysis", "resolution"], advanced=True)

        self.cmb_vis_freq_scale = QComboBox(card)
        self.cmb_vis_freq_scale.addItems(["Logarithmic", "Linear"])
        self.cmb_vis_freq_scale.currentTextChanged.connect(lambda v: self._set_setting("visualizer_frequency_scale", v))
        adv_form.addRow(TooltipLabel("Frequency Scale:", "Logarithmic matches human hearing.\nLinear gives equal spacing.", card), self.cmb_vis_freq_scale)
        _reg("visualizer_frequency_scale", "Frequency Scale", "Visualizer", "Audio",
             "How frequencies are distributed across bars", ["frequency", "scale", "logarithmic", "linear"], advanced=True)

        self.sld_vis_noise = ValueSlider(-100, 0, -60, "dB", parent=card)
        self.sld_vis_noise.valueChanged.connect(lambda v: self._set_setting("visualizer_noise_floor", v))
        adv_form.addRow(TooltipLabel("Noise Floor:", "Signals below this level are ignored.\nLower = more sensitive.", card), self.sld_vis_noise)
        _reg("visualizer_noise_floor", "Noise Floor", "Visualizer", "Audio",
             "Minimum signal level threshold", ["noise", "floor", "threshold", "gate"], advanced=True)

        adv.add_layout(adv_form)
        c_l.addWidget(adv)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_vis_bars(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        form = QFormLayout()
        self.cmb_vis_style = QComboBox(card)
        self.cmb_vis_style.addItems(["Pill Bars", "Standard Bars", "Square Bar"])
        self.cmb_vis_style.currentTextChanged.connect(self._on_vis_style_changed)
        form.addRow("Bar Style:", self.cmb_vis_style)
        _reg("visualizer_style", "Bar Style", "Visualizer", "Bars",
             "Visual shape of the frequency bars", ["style", "pill", "bar", "shape"])

        self.sld_vis_bars = ValueSlider(8, 128, 32, " bars", parent=card)
        self.sld_vis_bars.valueChanged.connect(self._on_vis_bars_changed)
        form.addRow("Bar Count:", self.sld_vis_bars)
        _reg("visualizer_bar_count", "Bar Count", "Visualizer", "Bars",
             "Number of frequency bars displayed", ["bar count", "bars", "number"])

        self.sw_vis_auto_bars = ToggleSwitch("Auto Bar Count", parent=card)
        self.sw_vis_auto_bars.toggled.connect(lambda v: self._set_setting("visualizer_auto_bar_count", v))
        c_l.addLayout(form)
        c_l.addWidget(self.sw_vis_auto_bars)
        _reg("visualizer_auto_bar_count", "Auto Bar Count", "Visualizer", "Bars",
             "Automatically calculate bar count from window size", ["auto", "bar count", "automatic"])

        self.sw_vis_mirror = ToggleSwitch("Mirror", parent=card)
        self.sw_vis_mirror.toggled.connect(lambda v: self._set_setting("visualizer_mirror", v))
        c_l.addWidget(self.sw_vis_mirror)
        _reg("visualizer_mirror", "Mirror", "Visualizer", "Bars",
             "Mirror the bar display", ["mirror", "symmetry", "flip"])

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_vis_color(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        form = QFormLayout()
        self.cmb_vis_color_mode = QComboBox(card)
        self.cmb_vis_color_mode.addItems(["Solid", "Gradient", "Album Accent", "Active Lyric Color"])
        self.cmb_vis_color_mode.currentTextChanged.connect(lambda v: self._set_setting("visualizer_color_mode", v))
        form.addRow("Color Mode:", self.cmb_vis_color_mode)
        _reg("visualizer_color_mode", "Color Mode", "Visualizer", "Color",
             "How the visualizer bars are colored", ["color", "mode", "gradient", "solid"])

        self.btn_vis_color = ColorSwatchButton("#FFFFFF", card)
        self.btn_vis_color.colorChanged.connect(lambda c: self._set_setting("visualizer_color", c))
        form.addRow("Solid Color:", self.btn_vis_color)
        _reg("visualizer_color", "Visualizer Color", "Visualizer", "Color",
             "Solid color for the visualizer bars", ["color", "solid", "visualizer"])

        c_l.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_vis_effects(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        self.sw_vis_glow = ToggleSwitch("Glow Effect", parent=card)
        self.sw_vis_glow.toggled.connect(lambda v: self._set_setting_and_update_visibility("visualizer_glow_enabled", v))
        c_l.addWidget(self.sw_vis_glow)
        _reg("visualizer_glow_enabled", "Glow Effect", "Visualizer", "Effects",
             "Add a glow around the visualizer bars", ["glow", "effect", "luminous"])

        self._vis_glow_controls = QWidget(card)
        vg_form = QFormLayout(self._vis_glow_controls)
        vg_form.setContentsMargins(16, 0, 0, 0)
        self.sld_vis_glow_r = ValueSlider(2, 30, 8, "px", parent=card)
        self.sld_vis_glow_r.valueChanged.connect(lambda v: self._set_setting("visualizer_glow_radius", v))
        vg_form.addRow("Radius:", self.sld_vis_glow_r)
        _reg("visualizer_glow_radius", "Glow Radius", "Visualizer", "Effects",
             "Size of the glow effect", ["glow", "radius", "size"],
             depends_on="visualizer_glow_enabled", advanced=True)
        c_l.addWidget(self._vis_glow_controls)

        self.sw_vis_shadow = ToggleSwitch("Shadow", parent=card)
        self.sw_vis_shadow.toggled.connect(lambda v: self._set_setting("visualizer_shadow_enabled", v))
        c_l.addWidget(self.sw_vis_shadow)
        _reg("visualizer_shadow_enabled", "Visualizer Shadow", "Visualizer", "Effects",
             "Drop shadow on visualizer bars", ["shadow", "visualizer"])

        self.sw_vis_reflection = ToggleSwitch("Reflection", parent=card)
        self.sw_vis_reflection.toggled.connect(lambda v: self._set_setting("visualizer_reflection_enabled", v))
        c_l.addWidget(self.sw_vis_reflection)
        _reg("visualizer_reflection_enabled", "Reflection", "Visualizer", "Effects",
             "Mirror reflection effect below bars", ["reflection", "mirror", "effect"])

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_vis_position(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        lbl = QLabel("Position & Window", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        # Position presets
        pos_h = QHBoxLayout()
        for pos_name in ["Free", "Top", "Bottom", "Left", "Right"]:
            btn = GlassButton(pos_name, parent=card)
            btn.clicked.connect(lambda _, p=pos_name: self._set_setting("visualizer_position_preset", p))
            pos_h.addWidget(btn)
        pos_h.addStretch()
        c_l.addLayout(pos_h)
        _reg("visualizer_position_preset", "Position", "Visualizer", "Position",
             "Quick position preset for the visualizer", ["position", "top", "bottom", "left", "right"])

        form = QFormLayout()
        self.sld_vis_op = ValueSlider(0, 100, 100, "%", parent=card)
        self.sld_vis_op.valueChanged.connect(lambda v: self._set_setting("visualizer_opacity", v))
        form.addRow("Opacity:", self.sld_vis_op)
        _reg("visualizer_opacity", "Visualizer Opacity", "Visualizer", "Position",
             "Transparency of the visualizer window", ["opacity", "visualizer", "transparency"])

        c_l.addLayout(form)

        self.sw_vis_topmost = ToggleSwitch("Always on Top", parent=card)
        self.sw_vis_topmost.toggled.connect(lambda v: self._set_setting("visualizer_always_on_top", v))
        c_l.addWidget(self.sw_vis_topmost)
        _reg("visualizer_always_on_top", "Visualizer Always on Top", "Visualizer", "Position",
             "Keep visualizer above all windows", ["topmost", "always on top", "visualizer"])

        self.sw_vis_click_thru = ToggleSwitch("Click Through", parent=card)
        self.sw_vis_click_thru.toggled.connect(lambda v: self._set_setting("visualizer_click_through", v))
        c_l.addWidget(self.sw_vis_click_thru)
        _reg("visualizer_click_through", "Visualizer Click Through", "Visualizer", "Position",
             "Pass clicks through the visualizer window", ["click through", "visualizer", "mouse"])

        self.sw_vis_excl_cap = ToggleSwitch("Exclude from Screen Capture", parent=card)
        self.sw_vis_excl_cap.toggled.connect(lambda v: self._set_setting("visualizer_exclude_from_capture", v))
        c_l.addWidget(self.sw_vis_excl_cap)
        _reg("visualizer_exclude_from_capture", "Visualizer Capture Exclusion", "Visualizer", "Position",
             "Hide from OBS/Discord captures", ["capture", "exclude", "obs", "visualizer"])

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_vis_game_overlay(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        lbl = QLabel("Game Overlay Mode", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        form = QFormLayout()
        self.cmb_vis_overlay = QComboBox(card)
        self.cmb_vis_overlay.addItems(["Normal", "Game Overlay"])
        self.cmb_vis_overlay.currentTextChanged.connect(lambda v: self._set_setting_and_update_visibility("visualizer_overlay_mode", v))
        form.addRow("Mode:", self.cmb_vis_overlay)
        _reg("visualizer_overlay_mode", "Overlay Mode", "Visualizer", "Game Overlay",
             "Switch between normal desktop and game overlay HUD",
             ["game overlay", "overlay", "hud", "gaming"])

        self.cmb_vis_overlay_screen = QComboBox(card)
        self.cmb_vis_overlay_screen.addItems(["Active Game Monitor", "Primary Monitor", "Monitor 1", "Monitor 2"])
        self.cmb_vis_overlay_screen.currentTextChanged.connect(lambda v: self._set_setting("visualizer_overlay_screen", v))
        form.addRow("Target Screen:", self.cmb_vis_overlay_screen)
        _reg("visualizer_overlay_screen", "Game Overlay Monitor", "Visualizer", "Game Overlay",
             "Which monitor to display the game overlay on", ["monitor", "screen", "game overlay"])

        self.cmb_vis_overlay_pos = QComboBox(card)
        self.cmb_vis_overlay_pos.addItems(["Top", "Bottom", "Left", "Right"])
        self.cmb_vis_overlay_pos.currentTextChanged.connect(lambda v: self._set_setting("visualizer_overlay_position", v))
        form.addRow("Position:", self.cmb_vis_overlay_pos)
        _reg("visualizer_overlay_position", "Game Overlay Position", "Visualizer", "Game Overlay",
             "Edge position for the game overlay HUD", ["position", "game overlay"])

        self.sld_vis_overlay_margin = ValueSlider(0, 60, 15, "px", parent=card)
        self.sld_vis_overlay_margin.valueChanged.connect(lambda v: self._set_setting("visualizer_overlay_margin", v))
        form.addRow("Margin:", self.sld_vis_overlay_margin)
        _reg("visualizer_overlay_margin", "Game Overlay Margin", "Visualizer", "Game Overlay",
             "Edge margin for game overlay positioning", ["margin", "game overlay", "spacing"])

        c_l.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_vis_behavior(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(8)

        self.sw_vis_pause_pause = ToggleSwitch("Pause when media paused", parent=card)
        self.sw_vis_pause_pause.toggled.connect(lambda v: self._set_setting("visualizer_pause_on_media_pause", v))
        c_l.addWidget(self.sw_vis_pause_pause)
        _reg("visualizer_pause_on_media_pause", "Pause on Media Pause", "Visualizer", "Behavior",
             "Pause visualizer when playback is paused", ["pause", "media", "visualizer"])

        self.sw_vis_hide_stop = ToggleSwitch("Hide when stopped", parent=card)
        self.sw_vis_hide_stop.toggled.connect(lambda v: self._set_setting("visualizer_hide_on_stop", v))
        c_l.addWidget(self.sw_vis_hide_stop)
        _reg("visualizer_hide_on_stop", "Hide on Stop", "Visualizer", "Behavior",
             "Hide visualizer when media stops", ["hide", "stop", "visualizer"])

        form = QFormLayout()
        self.sld_vis_fps = ValueSlider(15, 120, 60, " FPS", parent=card)
        self.sld_vis_fps.valueChanged.connect(lambda v: self._set_setting("visualizer_fps", v))
        form.addRow("FPS:", self.sld_vis_fps)
        _reg("visualizer_fps", "Visualizer FPS", "Visualizer", "Behavior",
             "Frame rate for the visualizer renderer", ["fps", "frame rate", "visualizer"])
        c_l.addLayout(form)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ 5: APPEARANCE — 5 Subsections                                      ║
    # ╚══════════════════════════════════════════════════════════════════════╝

    def _build_page_appearance(self) -> QWidget:
        return self._build_subsection_page("Appearance",
            self.PAGE_SUBSECTIONS["Appearance"],
            [
                self._build_app_theme,
                self._build_app_glass,
                self._build_app_accent,
                self._build_app_background,
                self._build_app_motion,
            ]
        )

    def _build_app_theme(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        lbl = QLabel("Theme Mode", card)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        c_l.addWidget(lbl)

        form = QFormLayout()
        self.cmb_theme_mode = QComboBox(card)
        self.cmb_theme_mode.addItems(["Dynamic Album Accent", "Manual Accent", "Neutral Dark"])
        self.cmb_theme_mode.currentTextChanged.connect(lambda v: self._set_setting("theme_mode", v))
        form.addRow("Accent Mode:", self.cmb_theme_mode)
        _reg("theme_mode", "Theme Mode", "Appearance", "Theme",
             "How the UI accent color is determined",
             ["theme", "accent", "dynamic", "manual", "dark"])
        c_l.addLayout(form)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_app_glass(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        form = QFormLayout()
        self.sld_glass = ValueSlider(20, 100, 75, "%", parent=card)
        self.sld_glass.valueChanged.connect(lambda v: self._set_setting("glass_intensity", v))
        form.addRow("Glass Intensity:", self.sld_glass)
        _reg("glass_intensity", "Glass Intensity", "Appearance", "Glass",
             "Overall opacity/intensity of the glass UI material",
             ["glass", "intensity", "opacity", "material"])

        self.sld_glass_blur = ValueSlider(0, 50, 20, "px", parent=card)
        self.sld_glass_blur.valueChanged.connect(lambda v: self._set_setting("glass_blur", v))
        form.addRow("Blur:", self.sld_glass_blur)
        _reg("glass_blur", "Glass Blur", "Appearance", "Glass",
             "Background blur strength for glass panels", ["glass", "blur"])

        c_l.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_app_accent(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        form = QFormLayout()
        self.btn_manual_accent = ColorSwatchButton("#1DB954", card)
        self.btn_manual_accent.colorChanged.connect(lambda col: self._set_setting("manual_accent_color", col))
        form.addRow("Manual Accent Color:", self.btn_manual_accent)
        _reg("manual_accent_color", "Manual Accent Color", "Appearance", "Accent",
             "Custom accent color when in Manual Accent mode",
             ["accent", "color", "manual", "custom"])
        c_l.addLayout(form)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_app_background(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        form = QFormLayout()
        self.cmb_bg_style = QComboBox(card)
        self.cmb_bg_style.addItems(["Cosmic Nebula", "Album Glow", "Minimal Dark", "Solid"])
        self.cmb_bg_style.currentTextChanged.connect(lambda v: self._set_setting("background_style", v))
        form.addRow("Background Style:", self.cmb_bg_style)
        _reg("background_style", "Background Style", "Appearance", "Background",
             "Visual style for the settings window background",
             ["background", "nebula", "glow", "atmosphere"])
        c_l.addLayout(form)

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    def _build_app_motion(self) -> QWidget:
        scroll, content, layout = _make_scroll_page()
        card = GlassCard(radius=14, elevated=False, parent=content)
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(14, 12, 14, 12)
        c_l.setSpacing(10)

        form = QFormLayout()
        self.cmb_anim_intensity = QComboBox(card)
        self.cmb_anim_intensity.addItems(["Subtle", "Standard", "Expressive", "Off"])
        self.cmb_anim_intensity.currentTextChanged.connect(lambda v: self._set_setting("animation_intensity", v))
        form.addRow("Animation Intensity:", self.cmb_anim_intensity)
        _reg("animation_intensity", "Animation Intensity", "Appearance", "Motion",
             "Global animation intensity level",
             ["animation", "intensity", "subtle", "expressive", "motion"])
        c_l.addLayout(form)

        self.sw_reduced_motion = ToggleSwitch("Reduced Motion (disable large animated transitions)", parent=card)
        self.sw_reduced_motion.toggled.connect(lambda v: self._set_setting("reduced_motion", v))
        c_l.addWidget(self.sw_reduced_motion)
        _reg("reduced_motion", "Reduced Motion", "Appearance", "Motion",
             "Minimize animations for accessibility",
             ["reduced motion", "accessibility", "animations", "disable"])

        layout.addWidget(card)
        layout.addStretch()
        return scroll

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ 6: BEHAVIOR — Card-grouped (no subsection tabs)                    ║
    # ╚══════════════════════════════════════════════════════════════════════╝

    def _build_page_behavior(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        # TRAY
        tray_card = GlassCard(radius=14, elevated=False, parent=content)
        tc_l = QVBoxLayout(tray_card)
        tc_l.setContentsMargins(14, 12, 14, 12)
        tc_l.setSpacing(8)
        lbl_tray = QLabel("TRAY & CLOSE", tray_card)
        lbl_tray.setStyleSheet("font-size: 10px; font-weight: 800; color: #8A8D9B; letter-spacing: 1px;")
        tc_l.addWidget(lbl_tray)

        form_t = QFormLayout()
        self.cmb_close_act = QComboBox(tray_card)
        self.cmb_close_act.addItems(["Minimize to Tray", "Hide Window", "Quit App"])
        self.cmb_close_act.currentTextChanged.connect(lambda v: self._set_setting("close_action", v))
        form_t.addRow("Close Action:", self.cmb_close_act)
        _reg("close_action", "Close Action", "Behavior", "Tray",
             "What happens when the studio window is closed",
             ["close", "tray", "minimize", "quit"])
        tc_l.addLayout(form_t)

        self.sw_tray_icon = ToggleSwitch("Show Tray Icon", parent=tray_card)
        self.sw_tray_icon.toggled.connect(lambda v: self._set_setting("show_tray_icon", v))
        tc_l.addWidget(self.sw_tray_icon)
        _reg("show_tray_icon", "Show Tray Icon", "Behavior", "Tray",
             "Show Lyrune icon in the system tray", ["tray", "icon", "system tray"])

        layout.addWidget(tray_card)

        # STARTUP
        start_card = GlassCard(radius=14, elevated=False, parent=content)
        sc_l = QVBoxLayout(start_card)
        sc_l.setContentsMargins(14, 12, 14, 12)
        sc_l.setSpacing(8)
        lbl_start = QLabel("STARTUP", start_card)
        lbl_start.setStyleSheet("font-size: 10px; font-weight: 800; color: #8A8D9B; letter-spacing: 1px;")
        sc_l.addWidget(lbl_start)

        self.sw_start_windows = ToggleSwitch("Start with Windows", parent=start_card)
        self.sw_start_windows.toggled.connect(lambda v: self._set_setting("start_with_windows", v))
        sc_l.addWidget(self.sw_start_windows)
        _reg("start_with_windows", "Start with Windows", "Behavior", "Startup",
             "Launch Lyrune automatically when Windows starts",
             ["startup", "windows", "boot", "autostart"])

        self.sw_restore_state = ToggleSwitch("Restore Previous State", parent=start_card)
        self.sw_restore_state.toggled.connect(lambda v: self._set_setting("startup_restore_state", v))
        sc_l.addWidget(self.sw_restore_state)
        _reg("startup_restore_state", "Restore State", "Behavior", "Startup",
             "Restore previous window positions and enabled features",
             ["restore", "state", "previous", "remember"])

        layout.addWidget(start_card)

        # POWER
        power_card = GlassCard(radius=14, elevated=False, parent=content)
        pc_l = QVBoxLayout(power_card)
        pc_l.setContentsMargins(14, 12, 14, 12)
        pc_l.setSpacing(8)
        lbl_pwr = QLabel("POWER", power_card)
        lbl_pwr.setStyleSheet("font-size: 10px; font-weight: 800; color: #8A8D9B; letter-spacing: 1px;")
        pc_l.addWidget(lbl_pwr)

        self.sw_pwr_wp = ToggleSwitch("Pause Wallpaper on Battery", parent=power_card)
        self.sw_pwr_wp.toggled.connect(lambda v: self._set_setting("power_pause_wallpaper_on_battery", v))
        pc_l.addWidget(self.sw_pwr_wp)
        _reg("power_pause_wallpaper_on_battery", "Pause Wallpaper on Battery", "Behavior", "Power",
             "Pause wallpaper engine when on battery power", ["battery", "wallpaper", "power"])

        self.sw_pwr_vis = ToggleSwitch("Pause Visualizer on Battery", parent=power_card)
        self.sw_pwr_vis.toggled.connect(lambda v: self._set_setting("power_pause_visualizer_on_battery", v))
        pc_l.addWidget(self.sw_pwr_vis)
        _reg("power_pause_visualizer_on_battery", "Pause Visualizer on Battery", "Behavior", "Power",
             "Pause visualizer when on battery power", ["battery", "visualizer", "power"])

        self.sw_pwr_fs = ToggleSwitch("Pause on Fullscreen", parent=power_card)
        self.sw_pwr_fs.toggled.connect(lambda v: self._set_setting("power_pause_on_fullscreen", v))
        pc_l.addWidget(self.sw_pwr_fs)
        _reg("power_pause_on_fullscreen", "Pause on Fullscreen", "Behavior", "Power",
             "Pause when a fullscreen application is active", ["fullscreen", "pause", "game"])

        layout.addWidget(power_card)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ 7–10: SHORTCUTS / PERFORMANCE / DIAGNOSTICS / ADVANCED             ║
    # ╚══════════════════════════════════════════════════════════════════════╝

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
            QTableWidget { background: rgba(24,28,38,0.65); border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px; color: #FFFFFF; }
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
            self.table_shortcuts.setItem(row, 0, QTableWidgetItem(item["name"]))
            self.table_shortcuts.setItem(row, 1, QTableWidgetItem(val))
            if k_id in conflicts:
                si = QTableWidgetItem("⚠️ Conflict")
                si.setForeground(QColor("#FF4757"))
            else:
                si = QTableWidgetItem("✓ Active")
                si.setForeground(QColor("#2ED573"))
            self.table_shortcuts.setItem(row, 2, si)

    def _build_page_performance(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

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

        form = QFormLayout()
        self.cmb_power_prof = QComboBox(card)
        self.cmb_power_prof.addItems(["High Performance (60 FPS)", "Balanced (30 FPS)", "Battery Saver (15 FPS)"])
        self.cmb_power_prof.currentTextChanged.connect(lambda v: self._set_setting("power_profile", v))
        form.addRow("Power Profile:", self.cmb_power_prof)
        _reg("power_profile", "Power Profile", "Performance", "General",
             "Global power profile for rendering", ["power", "profile", "battery", "fps"])

        self.sld_preview_fps = ValueSlider(15, 120, 60, " FPS", parent=card)
        self.sld_preview_fps.valueChanged.connect(lambda v: self._set_setting("preview_fps", v))
        form.addRow("Studio Preview FPS:", self.sld_preview_fps)
        _reg("preview_fps", "Studio Preview FPS", "Performance", "General",
             "Frame rate for studio preview panels", ["preview", "fps"])

        c_l.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return page

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

        self.txt_logs = QTextEdit(card)
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setFixedHeight(260)
        self.txt_logs.setStyleSheet("""
            QTextEdit { background: rgba(10,13,20,0.85); border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px; color: #A0A5B5; font-family: 'Consolas', monospace; font-size: 11px; padding: 8px; }
        """)
        self._refresh_logs()
        c_l.addWidget(self.txt_logs)

        log_act_h = QHBoxLayout()
        btn_ref = GlassButton("Refresh Logs", parent=card)
        btn_ref.clicked.connect(self._refresh_logs)
        btn_clr = GlassButton("Clear Logs", parent=card)
        btn_clr.clicked.connect(self._clear_logs)
        log_act_h.addWidget(btn_ref)
        log_act_h.addWidget(btn_clr)
        log_act_h.addStretch()
        c_l.addLayout(log_act_h)

        layout.addWidget(card)
        layout.addStretch()
        return page

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

        # Settings Registry Stats
        reg_lbl = QLabel(f"Settings Registry: {SETTINGS_REGISTRY.count} registered controls", card)
        reg_lbl.setStyleSheet("font-size: 11px; color: #525666; margin-top: 10px;")
        c_l.addWidget(reg_lbl)

        lbl_about = QLabel(f"Lyrune Studio v2.0.0  •  Qt 6.8  •  Python {platform.python_version()}", card)
        lbl_about.setStyleSheet("font-size: 11px; color: #525666; margin-top: 14px;")
        c_l.addWidget(lbl_about)

        layout.addWidget(card)
        layout.addStretch()
        return page

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ STATE BINDINGS & HANDLERS                                           ║
    # ╚══════════════════════════════════════════════════════════════════════╝

    def _set_setting(self, key: str, value: Any):
        self._record_transaction()
        self.working_settings[key] = value
        self._update_unsaved_indicator()

    def _set_setting_and_update_visibility(self, key: str, value: Any):
        """Set a setting and update contextual visibility of dependent controls."""
        self._set_setting(key, value)
        self._update_contextual_visibility()

    def _update_contextual_visibility(self):
        """Show/hide and enable/disable controls based on current setting values."""
        s = self.working_settings

        # Shadow controls
        if hasattr(self, '_shadow_controls'):
            self._shadow_controls.setVisible(s.get("shadow_enabled", False))

        # Glow controls
        if hasattr(self, '_glow_controls'):
            self._glow_controls.setVisible(s.get("lyrics_glow_enabled", False))

        # Vinyl reactive controls
        if hasattr(self, '_vinyl_reactive_controls'):
            self._vinyl_reactive_controls.setVisible(s.get("wallpaper_vinyl_audio_reactive", False))

        # Visualizer glow controls
        if hasattr(self, '_vis_glow_controls'):
            self._vis_glow_controls.setVisible(s.get("visualizer_glow_enabled", False))

        # Visualizer bar count manual slider enabled state
        if hasattr(self, 'sld_vis_bars'):
            self.sld_vis_bars.setEnabled(not s.get("visualizer_auto_bar_count", True))

        # Theme accent manual picker enabled state
        if hasattr(self, 'btn_manual_accent'):
            self.btn_manual_accent.setEnabled(s.get("theme_mode", "") == "Manual Accent")

        # Context font size enabled state
        if hasattr(self, 'sld_ctx_size'):
            self.sld_ctx_size.setEnabled(s.get("lyrics_context_font_mode", "") == "Custom")

    def _apply_domain_preset(self, domain: str, preset_name: str):
        """Apply a domain-specific preset and update UI."""
        self._record_transaction()
        presets_map = {"lyrics": LYRICS_PRESETS, "wallpaper": WALLPAPER_PRESETS, "visualizer": VISUALIZER_PRESETS}
        presets = presets_map.get(domain, {})
        if preset_name in presets:
            self.working_settings.update(presets[preset_name])
            self._load_working_settings_to_ui()
            self._update_unsaved_indicator()
            log_event(f"🎨 [Studio] Applied {domain} preset: {preset_name}")

    def _reset_section_ui(self, prefix: str):
        """Reset all settings with the given prefix to defaults and refresh UI."""
        self._record_transaction()
        for key, default_val in DEFAULT_SETTINGS.items():
            if key.startswith(prefix):
                self.working_settings[key] = default_val
        self._load_working_settings_to_ui()
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

    def _layer_move_up(self):
        row = self.list_layers.currentRow()
        if row > 0:
            item = self.list_layers.takeItem(row)
            self.list_layers.insertItem(row - 1, item)
            self.list_layers.setCurrentRow(row - 1)
            self._save_layer_order()

    def _layer_move_down(self):
        row = self.list_layers.currentRow()
        if 0 <= row < self.list_layers.count() - 1:
            item = self.list_layers.takeItem(row)
            self.list_layers.insertItem(row + 1, item)
            self.list_layers.setCurrentRow(row + 1)
            self._save_layer_order()

    def _save_layer_order(self):
        order = [self.list_layers.item(i).text() for i in range(self.list_layers.count())]
        order.reverse()  # List shows top=front, settings stores bottom-first
        self._set_setting("wallpaper_layer_order", order)

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

        # Media
        self.cmb_media_src.setCurrentText(s.get("selected_media_source", "Auto-Detect"))
        self.sw_prefer_playing.setChecked(s.get("prefer_playing_session", True))

        # Lyrics — Content
        self.cmb_view_mode.setCurrentText(s.get("lyrics_view_mode", "Multi-line"))
        self.sld_context.setValue(s.get("context_lines", 2))
        self.sld_max_lines.setValue(s.get("lyrics_max_lines", 8))
        self.cmb_unsynced.setCurrentText(s.get("lyrics_unsynced_behavior", "Show static"))
        self.cmb_no_lyrics.setCurrentText(s.get("lyrics_no_lyrics_behavior", "Show message"))
        self.sw_song_info.setChecked(s.get("show_song_info", True))

        # Lyrics — Typography
        self.cmb_font.setCurrentFont(QFont(s.get("font_family", "Segoe UI")))
        self.sld_font_size.setValue(s.get("font_size", 24))
        self.sw_font_bold.setChecked(s.get("font_bold", True))
        self.sw_font_italic.setChecked(s.get("lyrics_active_font_italic", False))
        self.cmb_ctx_font_mode.setCurrentText(s.get("lyrics_context_font_mode", "Use Active Line Settings"))
        self.sld_ctx_size.setValue(s.get("lyrics_context_font_size", 18))
        self.sld_line_height.setValue(int(s.get("lyrics_line_height", 1.4) * 100))
        self.cmb_case.setCurrentText(s.get("lyrics_case_transform", "None"))

        # Lyrics — Layout
        self.cmb_align_h.setCurrentText(s.get("text_align", "Center"))
        self.cmb_align_v.setCurrentText(s.get("lyrics_alignment_v", "Center"))
        self.sld_width.setValue(s.get("window_width", 800))
        self.sld_height.setValue(s.get("window_height", 220))
        self.sw_auto_resize.setChecked(s.get("auto_resize_height", True))
        self.sld_padding.setValue(s.get("lyrics_padding", 12))
        self.sw_snap.setChecked(s.get("snap_to_corners", True))
        self.sw_lock.setChecked(s.get("lock_position", False))

        # Lyrics — Appearance
        self.btn_active_color.setColor(s.get("text_color", "#FFFFFF"))
        self.btn_ctx_color.setColor(s.get("lyrics_context_color", "#888888"))
        self.btn_bg_color.setColor(s.get("bg_color", "#000000"))
        self.cmb_color_mode.setCurrentText(s.get("lyrics_color_mode", "Manual"))
        self.sld_active_op.setValue(s.get("active_line_opacity", 100))
        self.sld_ctx_op.setValue(s.get("context_line_opacity", 45))
        self.sld_bg_op.setValue(s.get("bg_opacity", 0))
        self.sw_shadow.setChecked(s.get("shadow_enabled", True))
        self.sld_shadow_blur.setValue(s.get("shadow_blur", 8))
        self.btn_shadow_color.setColor(s.get("shadow_color", "#000000"))
        self.sw_outline.setChecked(s.get("active_text_outline", True))
        self.sw_glow.setChecked(s.get("lyrics_glow_enabled", False))
        self.sld_glow_radius.setValue(s.get("lyrics_glow_radius", 12))
        self.btn_glow_color.setColor(s.get("lyrics_glow_color", "#2ED573"))

        # Lyrics — Animation
        self.cmb_anim_preset.setCurrentText(s.get("lyrics_animation_preset", "Smooth"))
        self.sld_anim_speed.setValue(s.get("animation_speed_ms", 400))
        self.sw_reduced_motion_lyrics.setChecked(s.get("lyrics_reduced_motion", False))
        self.cmb_easing.setCurrentText(s.get("lyrics_scroll_easing", "OutCubic"))
        self.cmb_track_trans.setCurrentText(s.get("lyrics_track_change_transition", "Fade"))

        # Lyrics — Sync
        self.sld_sync.setValue(s.get("sync_offset_ms", 0))
        self.sw_auto_drift.setChecked(s.get("lyrics_auto_drift_correction", False))
        self.sw_lrc_offset.setChecked(s.get("lyrics_lrc_metadata_offset", True))

        # Lyrics — Behavior
        self.sw_topmost.setChecked(s.get("always_on_top", True))
        self.sw_click_thru.setChecked(s.get("click_through", False))
        self.sw_exclude_cap.setChecked(s.get("exclude_from_capture", False))
        self.sw_auto_hide.setChecked(s.get("auto_hide_on_pause", False))
        self.sw_hide_stop.setChecked(s.get("lyrics_hide_on_stop", True))
        self.sld_hide_delay.setValue(s.get("auto_hide_delay_sec", 5))

        # Wallpaper
        self.sw_wallpaper.setChecked(s.get("wallpaper_enabled", False))
        self.cmb_wp_display.setCurrentText(s.get("wallpaper_display_mode", "Primary Display"))
        self.cmb_wp_type.setCurrentText(s.get("wallpaper_type", "static"))
        self.cmb_wp_scaling.setCurrentText(s.get("wallpaper_scaling_mode", "fill"))
        self.sld_wp_brightness.setValue(s.get("wallpaper_brightness", 100))
        self.sld_wp_blur.setValue(s.get("wallpaper_blur", 0))
        self.sld_vinyl_size.setValue(int(s.get("wallpaper_vinyl_size", 0.20) * 100))
        self.sld_vinyl_op.setValue(s.get("wallpaper_vinyl_opacity", 100))
        self.sld_vinyl_speed.setValue(int(s.get("wallpaper_rotation_speed", 12.0)))
        self.sw_vinyl_shadow.setChecked(s.get("wallpaper_vinyl_shadow", False))
        self.sw_vinyl_glow.setChecked(s.get("wallpaper_vinyl_glow", False))
        self.sw_vinyl_reactive.setChecked(s.get("wallpaper_vinyl_audio_reactive", False))
        self.sld_vinyl_bass.setValue(s.get("wallpaper_vinyl_bass_response", 50))
        self.sw_wp_title.setChecked(s.get("wallpaper_show_title", True))
        self.sw_wp_artist.setChecked(s.get("wallpaper_show_artist", True))
        self.cmb_wp_text_pos.setCurrentText(s.get("wallpaper_text_position", "Below"))
        self.cmb_wp_text_align.setCurrentText(s.get("wallpaper_text_alignment", "Center"))
        self.btn_wp_text_color.setColor(s.get("wallpaper_text_color", "#FFFFFF"))
        self.sw_wp_lyrics.setChecked(s.get("wallpaper_lyrics_enabled", False))
        self.sw_wp_vis.setChecked(s.get("wallpaper_visualizer_enabled", False))
        self.sw_wp_pause_battery.setChecked(s.get("wallpaper_pause_on_battery", False))
        self.sw_wp_pause_fs.setChecked(s.get("wallpaper_pause_on_fullscreen", False))
        self.sld_wp_fps.setValue(s.get("wallpaper_fps", 30))

        # Visualizer
        self.sw_vis_enable.setChecked(s.get("visualizer_enabled", False))
        self.sld_vis_sensitivity.setValue(s.get("visualizer_sensitivity", 100))
        self.sld_vis_smooth.setValue(s.get("visualizer_smoothing", 75))
        self.cmb_vis_fft.setCurrentText(str(s.get("visualizer_fft_size", 1024)))
        self.cmb_vis_freq_scale.setCurrentText(s.get("visualizer_frequency_scale", "Logarithmic"))
        self.sld_vis_noise.setValue(s.get("visualizer_noise_floor", -60))
        self.cmb_vis_style.setCurrentText(s.get("visualizer_style", "Pill Bars"))
        self.sld_vis_bars.setValue(s.get("visualizer_bar_count", 32))
        self.sw_vis_auto_bars.setChecked(s.get("visualizer_auto_bar_count", True))
        self.sw_vis_mirror.setChecked(s.get("visualizer_mirror", False))
        self.cmb_vis_color_mode.setCurrentText(s.get("visualizer_color_mode", "Solid"))
        self.btn_vis_color.setColor(s.get("visualizer_color", "#FFFFFF"))
        self.sw_vis_glow.setChecked(s.get("visualizer_glow_enabled", False))
        self.sld_vis_glow_r.setValue(s.get("visualizer_glow_radius", 8))
        self.sw_vis_shadow.setChecked(s.get("visualizer_shadow_enabled", False))
        self.sw_vis_reflection.setChecked(s.get("visualizer_reflection_enabled", False))
        self.sld_vis_op.setValue(s.get("visualizer_opacity", 100))
        self.sw_vis_topmost.setChecked(s.get("visualizer_always_on_top", True))
        self.sw_vis_click_thru.setChecked(s.get("visualizer_click_through", False))
        self.sw_vis_excl_cap.setChecked(s.get("visualizer_exclude_from_capture", False))
        self.cmb_vis_overlay.setCurrentText(s.get("visualizer_overlay_mode", "Normal"))
        self.cmb_vis_overlay_screen.setCurrentText(s.get("visualizer_overlay_screen", "Active Game Monitor"))
        self.cmb_vis_overlay_pos.setCurrentText(s.get("visualizer_overlay_position", "Bottom"))
        self.sld_vis_overlay_margin.setValue(s.get("visualizer_overlay_margin", 15))
        self.sw_vis_pause_pause.setChecked(s.get("visualizer_pause_on_media_pause", True))
        self.sw_vis_hide_stop.setChecked(s.get("visualizer_hide_on_stop", False))
        self.sld_vis_fps.setValue(s.get("visualizer_fps", 60))

        # Appearance
        self.cmb_theme_mode.setCurrentText(s.get("theme_mode", "Dynamic Album Accent"))
        self.sld_glass.setValue(s.get("glass_intensity", 75))
        self.sld_glass_blur.setValue(s.get("glass_blur", 20))
        self.btn_manual_accent.setColor(s.get("manual_accent_color", "#1DB954"))
        self.cmb_bg_style.setCurrentText(s.get("background_style", "Cosmic Nebula"))
        self.cmb_anim_intensity.setCurrentText(s.get("animation_intensity", "Standard"))
        self.sw_reduced_motion.setChecked(s.get("reduced_motion", False))

        # Behavior
        self.cmb_close_act.setCurrentText(s.get("close_action", "Minimize to Tray"))
        self.sw_tray_icon.setChecked(s.get("show_tray_icon", True))
        self.sw_start_windows.setChecked(s.get("start_with_windows", False))
        self.sw_restore_state.setChecked(s.get("startup_restore_state", True))
        self.sw_pwr_wp.setChecked(s.get("power_pause_wallpaper_on_battery", False))
        self.sw_pwr_vis.setChecked(s.get("power_pause_visualizer_on_battery", False))
        self.sw_pwr_fs.setChecked(s.get("power_pause_on_fullscreen", False))

        # Performance
        self.cmb_power_prof.setCurrentText(s.get("power_profile", "Balanced"))
        self.sld_preview_fps.setValue(s.get("preview_fps", 60))

        # Canvas + Visualizer Preview
        cfg = WallpaperConfig.from_settings(s)
        self.wp_canvas.set_config(cfg)
        self.vis_preview.update_style(s)
        self._populate_shortcuts_table()
        self._update_contextual_visibility()

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║ SETTINGS SEARCH (Ctrl+K / Ctrl+F)                                  ║
    # ╚══════════════════════════════════════════════════════════════════════╝

    def _open_settings_search(self):
        dlg = SettingsSearchDialog(parent=self)
        dlg.settingSelected.connect(self._navigate_to_setting)
        dlg.move(self.x() + (self.width() - dlg.width()) // 2, self.y() + 80)
        dlg.show()

    def _navigate_to_setting(self, setting_id: str):
        """Deep navigation: switch page → subsection → scroll to control."""
        meta = SETTINGS_REGISTRY.get_by_id(setting_id)
        if not meta:
            return

        # 1. Switch to correct top-level page
        page_map = {
            "Home": 0, "Media": 1, "Lyrics": 2, "Wallpaper": 3, "Visualizer": 4,
            "Appearance": 5, "Behavior": 6, "Shortcuts": 7, "Performance": 8,
            "Diagnostics": 9, "Advanced": 10
        }
        page_idx = page_map.get(meta.page, 0)
        self._switch_nav_page(page_idx)

        # 2. Switch to correct subsection tab
        if meta.page in self.PAGE_SUBSECTIONS:
            subsections = self.PAGE_SUBSECTIONS[meta.page]
            if meta.section in subsections:
                tab_idx = subsections.index(meta.section)
                if meta.page in self._subsection_tabs:
                    self._subsection_tabs[meta.page].set_active(tab_idx)
                if meta.page in self._subsection_stacks:
                    self._subsection_stacks[meta.page].setCurrentIndex(tab_idx)

        log_event(f"[Studio] Navigated to setting: {meta.page} → {meta.section} → {meta.name}")

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
