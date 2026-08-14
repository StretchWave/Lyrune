import os
import re
import platform
import sys
import math
import time
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QTimer, QRectF, QPointF
from PyQt6.QtGui import QFont, QColor, QKeySequence, QMouseEvent, QPainter, QBrush, QPen, QLinearGradient
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QPushButton, QComboBox, QFontComboBox, QTextEdit, QCheckBox, QListWidget, QListWidgetItem, QStackedWidget,
    QScrollArea, QFrame, QApplication, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView
)

from lyrune.ui_theme import (
    PALETTE, DARK_THEME_STYLESHEET, get_icon, get_app_icon, ToggleSwitch, ValueSlider, ColorSwatchButton, KeycapWidget
)
from lyrune.settings_manager import SettingsManager, PRESETS
from lyrune.logger import AppLogger
from lyrune.animation_engine import LyricsRenderer
from lyrune.lrclib_client import LRCLibClient
from lyrune.visualizer import BarVisualizer, AudioData


class VisualizerPreviewWidget(QWidget):
    """
    Live interactive preview canvas for the visualizer inside SettingsDialog.
    Runs simulated musical frequencies at 60 FPS to demonstrate current shape,
    gradient, spacing, bar width, and opacity live.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(105)
        self.setMinimumWidth(260)
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

        bg_color = QColor(PALETTE.surface_elevated)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(QColor(PALETTE.border), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

        draw_rect = self.rect().adjusted(10, 10, -10, -10)
        self.renderer.resize(draw_rect.width(), draw_rect.height())
        self.renderer.paint(painter, draw_rect)


class GradientPreviewBar(QWidget):
    """Interactive visual gradient preview strip."""
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

        if not self.stops:
            return

        grad = QLinearGradient(self.rect().left(), 0, self.rect().right(), 0)
        for s in self.stops:
            p = max(0.0, min(1.0, float(s.get("pos", 0.0))))
            c = QColor(s.get("color", "#FFFFFF"))
            grad.setColorAt(p, c)

        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(PALETTE.border), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)


class GradientStopRow(QWidget):
    """
    A single gradient stop editor row:
    Position Slider (0-100%) + Color Swatch Button + Delete Button.
    """
    changed = pyqtSignal()
    deleteRequested = pyqtSignal()

    def __init__(self, pos: float, color: str, can_delete: bool = True, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        pos_pct = int(round(pos * 100))
        self.slider = ValueSlider(0, 100, pos_pct, "%", self)
        self.slider.valueChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(QLabel("Stop Pos:", self))
        layout.addWidget(self.slider, 1)

        self.btn_color = ColorSwatchButton(color, self)
        self.btn_color.colorChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.btn_color)

        self.btn_delete = QPushButton(self)
        self.btn_delete.setFixedSize(26, 26)
        self.btn_delete.setIcon(get_icon("close", color=PALETTE.text_secondary))
        self.btn_delete.setToolTip("Remove Gradient Stop")
        self.btn_delete.setEnabled(can_delete)
        self.btn_delete.clicked.connect(self.deleteRequested.emit)
        layout.addWidget(self.btn_delete)

    def get_data(self) -> Dict[str, Any]:
        return {
            "pos": self.slider.value() / 100.0,
            "color": self.btn_color.color()
        }

    def set_data(self, pos: float, color: str):
        self.slider.setValue(int(round(pos * 100)))
        self.btn_color.setColor(color)


class GradientEditorCard(QGroupBox):
    """Full gradient editing card with interactive preview bar, stops table, add/remove, and presets."""
    gradientChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Gradient Color Stops", parent)
        self.card_layout = QVBoxLayout(self)
        self.card_layout.setContentsMargins(10, 10, 10, 10)
        self.card_layout.setSpacing(8)

        self.preview_bar = GradientPreviewBar(self)
        self.card_layout.addWidget(self.preview_bar)

        self.stops_container = QWidget(self)
        self.stops_layout = QVBoxLayout(self.stops_container)
        self.stops_layout.setContentsMargins(0, 0, 0, 0)
        self.stops_layout.setSpacing(4)
        self.card_layout.addWidget(self.stops_container)

        self._rows: List[GradientStopRow] = []

        actions_layout = QHBoxLayout()
        self.btn_add_stop = QPushButton("+ Add Color Stop", self)
        self.btn_add_stop.setObjectName("btn_secondary")
        self.btn_add_stop.clicked.connect(self._add_stop_clicked)
        actions_layout.addWidget(self.btn_add_stop)

        actions_layout.addStretch(1)

        self.presets = {
            "Spotify Glow": [{"pos": 0.0, "color": "#1DB954"}, {"pos": 1.0, "color": "#00F2FE"}],
            "Sunset": [{"pos": 0.0, "color": "#FF512F"}, {"pos": 0.5, "color": "#DD2476"}, {"pos": 1.0, "color": "#8A2387"}],
            "Cyber Neon": [{"pos": 0.0, "color": "#FF007F"}, {"pos": 0.5, "color": "#7928CA"}, {"pos": 1.0, "color": "#00DFD8"}],
            "Electric Fire": [{"pos": 0.0, "color": "#FF416C"}, {"pos": 1.0, "color": "#FF4B2B"}],
        }

        for name, p_stops in self.presets.items():
            p_btn = QPushButton(name, self)
            p_btn.setObjectName("btn_ghost")
            p_btn.clicked.connect(lambda _, s=p_stops: self.set_stops(s))
            actions_layout.addWidget(p_btn)

        self.card_layout.addLayout(actions_layout)

    def set_stops(self, stops: List[Dict[str, Any]]):
        for r in self._rows:
            r.setParent(None)
            r.deleteLater()
        self._rows.clear()

        sorted_stops = sorted(stops, key=lambda s: float(s.get("pos", 0.0)))
        can_del = len(sorted_stops) > 2

        for item in sorted_stops:
            row = GradientStopRow(item.get("pos", 0.0), item.get("color", "#FFFFFF"), can_delete=can_del, parent=self.stops_container)
            row.changed.connect(self._on_row_changed)
            row.deleteRequested.connect(lambda r=row: self._delete_row(r))
            self.stops_layout.addWidget(row)
            self._rows.append(row)

        self._update_preview()
        self.gradientChanged.emit()

    def get_stops(self) -> List[Dict[str, Any]]:
        raw = [r.get_data() for r in self._rows]
        return sorted(raw, key=lambda s: s["pos"])

    def _on_row_changed(self):
        self._update_preview()
        self.gradientChanged.emit()

    def _update_preview(self):
        stops = self.get_stops()
        self.preview_bar.set_stops(stops)
        can_del = len(self._rows) > 2
        for r in self._rows:
            r.btn_delete.setEnabled(can_del)

    def _add_stop_clicked(self):
        current_stops = self.get_stops()
        if len(current_stops) >= 8:
            return
        new_pos = 0.5
        if len(current_stops) >= 2:
            new_pos = (current_stops[-2]["pos"] + current_stops[-1]["pos"]) / 2.0
        current_stops.append({"pos": new_pos, "color": "#00DFD8"})
        self.set_stops(current_stops)

    def _delete_row(self, row: GradientStopRow):
        if len(self._rows) <= 2:
            return
        if row in self._rows:
            self._rows.remove(row)
            row.setParent(None)
            row.deleteLater()
            self._update_preview()
            self.gradientChanged.emit()


class CustomTitleBar(QWidget):
    """Sleek frameless title bar with integrated Now Playing preview widget & window controls."""
    minimizeClicked = pyqtSignal()
    closeClicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("customTitleBar")
        self.setFixedHeight(42)

        self._drag_position = QPoint()
        self._is_dragging = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(10)

        # Left: App Icon & Title
        left_layout = QHBoxLayout()
        left_layout.setSpacing(8)

        icon_label = QLabel(self)
        icon_label.setPixmap(get_app_icon().pixmap(20, 20))
        left_layout.addWidget(icon_label)

        title_label = QLabel("Lyrune", self)
        title_label.setStyleSheet(f"font-weight: 700; font-size: 11pt; color: {PALETTE.text_primary};")
        left_layout.addWidget(title_label)

        subtitle_label = QLabel("Settings", self)
        subtitle_label.setStyleSheet(f"font-weight: 400; font-size: 10pt; color: {PALETTE.text_secondary};")
        left_layout.addWidget(subtitle_label)

        layout.addLayout(left_layout)
        layout.addStretch(1)

        # Center/Right: Integrated Now Playing Floating Pill
        self.now_playing_pill = QFrame(self)
        self.now_playing_pill.setStyleSheet(
            f"background-color: {PALETTE.surface_elevated};"
            f" border: 1px solid {PALETTE.border};"
            f" border-radius: 12px;"
            f" padding: 2px 10px;"
        )
        pill_layout = QHBoxLayout(self.now_playing_pill)
        pill_layout.setContentsMargins(6, 2, 8, 2)
        pill_layout.setSpacing(6)

        pill_icon = QLabel(self.now_playing_pill)
        pill_icon.setPixmap(get_icon("preview", color=PALETTE.accent).pixmap(14, 14))
        pill_layout.addWidget(pill_icon)

        self.pill_text = QLabel("Now Playing Preview", self.now_playing_pill)
        self.pill_text.setStyleSheet(f"font-size: 8.5pt; font-weight: 500; color: {PALETTE.text_primary};")
        pill_layout.addWidget(self.pill_text)

        layout.addWidget(self.now_playing_pill)
        layout.addStretch(1)

        # Far Right: Window Control Buttons (Minimize, Close)
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(4)

        self.btn_min = QPushButton(self)
        self.btn_min.setFixedSize(28, 28)
        self.btn_min.setIcon(get_icon("minimize", color=PALETTE.text_secondary))
        self.btn_min.setToolTip("Minimize")
        self.btn_min.clicked.connect(self.minimizeClicked.emit)
        controls_layout.addWidget(self.btn_min)

        self.btn_close = QPushButton(self)
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setIcon(get_icon("close", color=PALETTE.text_secondary))
        self.btn_close.setToolTip("Close")
        self.btn_close.clicked.connect(self.closeClicked.emit)
        controls_layout.addWidget(self.btn_close)

        layout.addLayout(controls_layout)

    def set_now_playing(self, text: str):
        self.pill_text.setText(text)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_position = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._is_dragging = False


class ManualSearchDialog(QDialog):
    """Dialog for manual lyric searching & track binding."""
    def __init__(self, lrclib_client: LRCLibClient, initial_artist: str = "", initial_title: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.lrclib = lrclib_client
        self.selected_result = None

        self.setWindowTitle("Manual Lyric Search")
        self.setFixedSize(540, 420)
        self.setStyleSheet(DARK_THEME_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Search Form inputs
        form_layout = QHBoxLayout()
        self.artist_input = QLineEdit(initial_artist, self)
        self.artist_input.setPlaceholderText("Artist Name...")
        form_layout.addWidget(self.artist_input)

        self.title_input = QLineEdit(initial_title, self)
        self.title_input.setPlaceholderText("Track Title...")
        form_layout.addWidget(self.title_input)

        self.btn_search = QPushButton("Search", self)
        self.btn_search.setObjectName("btn_primary")
        self.btn_search.setIcon(get_icon("search", color=PALETTE.bg))
        self.btn_search.clicked.connect(self._do_search)
        form_layout.addWidget(self.btn_search)

        layout.addLayout(form_layout)

        # Results List Table
        self.results_table = QTableWidget(0, 3, self)
        self.results_table.setHorizontalHeaderLabels(["Track Title", "Artist", "Type"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.results_table)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_select = QPushButton("Use Selected Lyrics", self)
        self.btn_select.setObjectName("btn_primary")
        self.btn_select.setIcon(get_icon("check", color=PALETTE.bg))
        self.btn_select.clicked.connect(self._on_select)
        btn_layout.addWidget(self.btn_select)

        layout.addLayout(btn_layout)

        if initial_title:
            self._do_search()

    def _do_search(self):
        artist = self.artist_input.text().strip()
        title = self.title_input.text().strip()
        if not title and not artist:
            return

        results = self.lrclib.search_lyrics(artist=artist, title=title)
        self.results_table.setRowCount(0)
        self._results_data = results

        for i, item in enumerate(results):
            self.results_table.insertRow(i)
            self.results_table.setItem(i, 0, QTableWidgetItem(item.get('trackName', '')))
            self.results_table.setItem(i, 1, QTableWidgetItem(item.get('artistName', '')))
            ltype = "Synced (LRC)" if item.get('syncedLyrics') else ("Plain Text" if item.get('plainLyrics') else "None")
            self.results_table.setItem(i, 2, QTableWidgetItem(ltype))

    def _on_select(self):
        row = self.results_table.currentRow()
        if row >= 0 and hasattr(self, '_results_data') and row < len(self._results_data):
            self.selected_result = self._results_data[row]
            self.accept()


class SettingsDialog(QDialog):
    """
    Completely revamped Settings & Customization dialog featuring:
    - Custom frameless title bar with integrated Now Playing preview
    - Deep charcoal slate & Spotify Green palette
    - Left vertical sidebar navigation
    - Dedicated Preview Canvas card
    - Modern custom widgets (ToggleSwitch, ValueSlider, ColorSwatchButton, KeycapWidget)
    - Collapsible bottom Live Logs drawer
    - Sticky footer
    """
    settings_changed = pyqtSignal(dict)

    def __init__(self, settings_manager: SettingsManager, player: Optional[Any] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.player = player or (getattr(parent, 'player', None) if parent else None)
        self.working_settings = dict(settings_manager.settings)
        self._is_initializing = True
        self._log_connected = False

        self.setObjectName("settingsRoot")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        self.resize(780, 680)
        self.setMinimumSize(680, 560)
        self.setStyleSheet(DARK_THEME_STYLESHEET)
        self.setWindowIcon(get_app_icon())

        self._init_ui()
        self._load_current_values()

        self._is_initializing = False
        self._update_preview()

        # Connect logger signal to append live entries
        try:
            AppLogger.instance().log_signal.connect(self._append_log_entry)
            self._log_connected = True
        except Exception:
            pass
        self._load_log_history()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Custom Title Bar
        self.title_bar = CustomTitleBar(self)
        self.title_bar.minimizeClicked.connect(self._minimize_to_taskbar)
        self.title_bar.closeClicked.connect(self.reject)
        root_layout.addWidget(self.title_bar)

        # 2. Main Middle Container (Sidebar + Content Area)
        middle_widget = QWidget(self)
        middle_layout = QHBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)

        # --- Left Vertical Sidebar Navigation ---
        self.sidebar_nav = QListWidget(self)
        self.sidebar_nav.setObjectName("sidebarNav")
        self.sidebar_nav.setFixedWidth(180)

        self._sidebar_items = [
            ("appearance", "Appearance"),
            ("visualizer", "Visualizer"),
            ("typography", "Typography"),
            ("behavior", "Behavior && Source"),
            ("animations", "Animations"),
            ("shortcuts", "Shortcuts"),
            ("logs", "Advanced && Cache"),
        ]

        for key, label in self._sidebar_items:
            item = QListWidgetItem(get_icon(key, color=PALETTE.text_secondary), f"  {label}")
            self.sidebar_nav.addItem(item)

        self.sidebar_nav.currentRowChanged.connect(self._on_sidebar_changed)
        middle_layout.addWidget(self.sidebar_nav)

        # --- Right Main Content Area ---
        right_container = QWidget(self)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(10)

        # Top Preview Canvas Card
        preview_box = QGroupBox("Preview Canvas", right_container)
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(10, 10, 10, 10)

        self.preview_container = QWidget(preview_box)
        self.preview_container.setFixedHeight(95)
        container_layout = QVBoxLayout(self.preview_container)
        container_layout.setContentsMargins(4, 4, 4, 4)

        self.preview_renderer = LyricsRenderer(self.preview_container)
        self.preview_renderer.set_lines([
            "Kono mama zutto zutto",
            "Yubikiri genman hora demo fuitara",
            "Shinunoga e-wa anata to ireba"
        ])
        self.preview_renderer.set_active_index(1)

        self.preview_sub = QLabel('Fujii Kaze - Shinunoga E-Wa', self.preview_container)
        self.preview_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_sub.setStyleSheet(f"color: {PALETTE.text_secondary}; font-size: 10px; font-style: italic;")

        container_layout.addWidget(self.preview_renderer, 1)
        container_layout.addWidget(self.preview_sub)
        preview_layout.addWidget(self.preview_container)
        right_layout.addWidget(preview_box)

        # Stacked Pages
        self.pages_stack = QStackedWidget(right_container)

        self.appearance_page = QWidget()
        self._init_appearance_page()
        self.pages_stack.addWidget(self._wrap_in_scroll_area(self.appearance_page))

        self.visualizer_page = QWidget()
        self._init_visualizer_page()
        self.pages_stack.addWidget(self._wrap_in_scroll_area(self.visualizer_page))

        self.typography_page = QWidget()
        self._init_typography_page()
        self.pages_stack.addWidget(self._wrap_in_scroll_area(self.typography_page))

        self.behavior_page = QWidget()
        self._init_behavior_page()
        self.pages_stack.addWidget(self._wrap_in_scroll_area(self.behavior_page))

        self.animations_page = QWidget()
        self._init_animations_page()
        self.pages_stack.addWidget(self._wrap_in_scroll_area(self.animations_page))

        self.shortcuts_page = QWidget()
        self._init_shortcuts_page()
        self.pages_stack.addWidget(self._wrap_in_scroll_area(self.shortcuts_page))

        self.advanced_page = QWidget()
        self._init_advanced_page()
        self.pages_stack.addWidget(self._wrap_in_scroll_area(self.advanced_page))

        right_layout.addWidget(self.pages_stack, 1)
        middle_layout.addWidget(right_container, 1)
        root_layout.addWidget(middle_widget, 1)

        # 3. Collapsible Bottom Live Logs Drawer
        self._init_logs_drawer(root_layout)

        # 4. Sticky Footer Action Bar
        self._init_sticky_footer(root_layout)

        self.sidebar_nav.setCurrentRow(0)

    def _wrap_in_scroll_area(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    def _on_sidebar_changed(self, index: int):
        if 0 <= index < len(self._sidebar_items):
            self.pages_stack.setCurrentIndex(index)
            for i in range(self.sidebar_nav.count()):
                key, label = self._sidebar_items[i]
                color = PALETTE.accent if i == index else PALETTE.text_secondary
                self.sidebar_nav.item(i).setIcon(get_icon(key, color=color))

    # --- Page 0: Appearance ---
    def _init_appearance_page(self):
        layout = QVBoxLayout(self.appearance_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # Theme Presets
        preset_group = QGroupBox("Theme Presets", self.appearance_page)
        preset_layout = QHBoxLayout(preset_group)
        self.preset_combo = QComboBox(self)
        self.preset_combo.addItem("Select Preset...")
        self.preset_combo.addItems(list(PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._on_preset_combo_changed)
        preset_layout.addWidget(self.preset_combo, 1)
        layout.addWidget(preset_group)

        # Color Palette
        colors_group = QGroupBox("Color Palette", self.appearance_page)
        colors_form = QFormLayout(colors_group)

        self.btn_text_color = ColorSwatchButton("#FFFFFF", self)
        self.btn_text_color.colorChanged.connect(self._on_color_swatch_changed)
        colors_form.addRow("Text Color:", self.btn_text_color)

        self.btn_bg_color = ColorSwatchButton("#000000", self)
        self.btn_bg_color.colorChanged.connect(self._on_color_swatch_changed)
        colors_form.addRow("Background Color:", self.btn_bg_color)

        self.btn_shadow_color = ColorSwatchButton("#000000", self)
        self.btn_shadow_color.colorChanged.connect(self._on_color_swatch_changed)
        colors_form.addRow("Drop Shadow Color:", self.btn_shadow_color)
        layout.addWidget(colors_group)

        # Opacity & Visual Effects
        effects_group = QGroupBox("Opacity && Contour Effects", self.appearance_page)
        effects_form = QFormLayout(effects_group)

        self.opacity_slider = ValueSlider(0, 100, 0, "%", self)
        self.opacity_slider.valueChanged.connect(self._on_control_changed)
        effects_form.addRow("Background Opacity:", self.opacity_slider)

        self.active_opacity_slider = ValueSlider(10, 100, 100, "%", self)
        self.active_opacity_slider.valueChanged.connect(self._on_active_opacity_changed)
        effects_form.addRow("Active Line Opacity:", self.active_opacity_slider)

        self.context_opacity_slider = ValueSlider(0, 100, 45, "%", self)
        self.context_opacity_slider.valueChanged.connect(self._on_control_changed)
        effects_form.addRow("Context Line Opacity:", self.context_opacity_slider)

        self.shadow_blur_slider = ValueSlider(0, 30, 8, " px", self)
        self.shadow_blur_slider.valueChanged.connect(self._on_control_changed)
        effects_form.addRow("Shadow Blur Radius:", self.shadow_blur_slider)

        self.link_opacity_switch = ToggleSwitch("Link Active && Context Line Opacities", self)
        self.link_opacity_switch.toggled.connect(self._on_control_changed)
        effects_form.addRow("", self.link_opacity_switch)

        self.active_outline_switch = ToggleSwitch("High-Contrast Text Contour Outline", self)
        self.active_outline_switch.toggled.connect(self._on_control_changed)
        effects_form.addRow("", self.active_outline_switch)

        self.border_switch = ToggleSwitch("Overlay Window Border", self)
        self.border_switch.toggled.connect(self._on_control_changed)
        effects_form.addRow("", self.border_switch)

        self.adaptive_color_switch = ToggleSwitch("Smart Contrast Color Inversion", self)
        self.adaptive_color_switch.toggled.connect(self._on_control_changed)
        effects_form.addRow("", self.adaptive_color_switch)

        self.shadow_switch = ToggleSwitch("Drop Shadow Effect", self)
        self.shadow_switch.toggled.connect(self._on_control_changed)
        effects_form.addRow("", self.shadow_switch)

        layout.addWidget(effects_group)

    # --- Page 1: Visualizer Studio ---
    def _init_visualizer_page(self):
        layout = QVBoxLayout(self.visualizer_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # 1. Style & Shape
        style_group = QGroupBox("Visualizer Style && Shape", self.visualizer_page)
        style_form = QFormLayout(style_group)

        self.vis_enable_switch = ToggleSwitch("Enable Floating Visualizer Window", self)
        self.vis_enable_switch.toggled.connect(self._on_control_changed)
        style_form.addRow("", self.vis_enable_switch)

        self.vis_style_combo = QComboBox(self)
        self.vis_style_combo.addItems(["Pill Bars", "Standard Bars"])
        self.vis_style_combo.currentTextChanged.connect(self._on_control_changed)
        style_form.addRow("Visualizer Style:", self.vis_style_combo)

        self.vis_shape_combo = QComboBox(self)
        self.vis_shape_combo.addItems(["Pill", "Rounded Bar", "Square Bar"])
        self.vis_shape_combo.currentTextChanged.connect(self._on_vis_shape_changed)
        style_form.addRow("Element Shape:", self.vis_shape_combo)

        self.vis_corner_radius_slider = ValueSlider(0, 20, 4, " px", self)
        self.vis_corner_radius_slider.valueChanged.connect(self._on_control_changed)
        self.vis_corner_radius_row_label = QLabel("Corner Radius:", self)
        style_form.addRow(self.vis_corner_radius_row_label, self.vis_corner_radius_slider)

        layout.addWidget(style_group)

        # 2. Live Visualizer Preview Canvas
        preview_card = QGroupBox("Live Visualizer Preview", self.visualizer_page)
        preview_card_layout = QVBoxLayout(preview_card)
        preview_card_layout.setContentsMargins(8, 8, 8, 8)
        self.vis_preview = VisualizerPreviewWidget(preview_card)
        preview_card_layout.addWidget(self.vis_preview)
        layout.addWidget(preview_card)

        # 3. Color & Gradients
        color_group = QGroupBox("Color && Multi-Stop Gradients", self.visualizer_page)
        color_form = QFormLayout(color_group)

        self.vis_color_mode_combo = QComboBox(self)
        self.vis_color_mode_combo.addItems(["Solid", "Gradient", "Active Lyric Color"])
        self.vis_color_mode_combo.currentTextChanged.connect(self._on_vis_color_mode_changed)
        color_form.addRow("Color Mode:", self.vis_color_mode_combo)

        self.btn_vis_color = ColorSwatchButton("#FFFFFF", self)
        self.btn_vis_color.colorChanged.connect(self._on_vis_color_changed)
        self.vis_solid_color_label = QLabel("Solid Bar Color:", self)
        color_form.addRow(self.vis_solid_color_label, self.btn_vis_color)

        self.vis_grad_dir_combo = QComboBox(self)
        self.vis_grad_dir_combo.addItems(["Follow Visualizer", "Fixed Horizontal", "Fixed Vertical", "Reverse"])
        self.vis_grad_dir_combo.currentTextChanged.connect(self._on_control_changed)
        self.vis_grad_dir_label = QLabel("Gradient Direction:", self)
        color_form.addRow(self.vis_grad_dir_label, self.vis_grad_dir_combo)

        self.gradient_editor = GradientEditorCard(self.visualizer_page)
        self.gradient_editor.gradientChanged.connect(self._on_control_changed)
        color_form.addRow(self.gradient_editor)

        layout.addWidget(color_group)

        # 4. Dimensions & Bar Density
        size_group = QGroupBox("Dimensions && Bar Density", self.visualizer_page)
        size_form = QFormLayout(size_group)

        self.vis_width_slider = ValueSlider(80, 1000, 320, " px", self)
        self.vis_width_slider.valueChanged.connect(self._on_control_changed)
        size_form.addRow("Logical Length:", self.vis_width_slider)

        self.vis_height_slider = ValueSlider(24, 250, 64, " px", self)
        self.vis_height_slider.valueChanged.connect(self._on_control_changed)
        size_form.addRow("Logical Thickness:", self.vis_height_slider)

        self.vis_bar_width_slider = ValueSlider(1, 30, 4, " px", self)
        self.vis_bar_width_slider.valueChanged.connect(self._on_control_changed)
        size_form.addRow("Bar / Pill Width:", self.vis_bar_width_slider)

        self.vis_bar_spacing_slider = ValueSlider(0, 20, 3, " px", self)
        self.vis_bar_spacing_slider.valueChanged.connect(self._on_control_changed)
        size_form.addRow("Bar Spacing:", self.vis_bar_spacing_slider)

        self.vis_max_height_slider = ValueSlider(20, 100, 100, "%", self)
        self.vis_max_height_slider.valueChanged.connect(self._on_control_changed)
        size_form.addRow("Max Bar Height:", self.vis_max_height_slider)

        self.vis_auto_bar_switch = ToggleSwitch("Automatic Bar Count (adapts density to window length)", self)
        self.vis_auto_bar_switch.toggled.connect(self._on_vis_auto_bar_toggled)
        size_form.addRow("", self.vis_auto_bar_switch)

        self.vis_manual_bar_slider = ValueSlider(4, 128, 32, " bars", self)
        self.vis_manual_bar_slider.valueChanged.connect(self._on_control_changed)
        self.vis_manual_bar_label = QLabel("Exact Bar Count:", self)
        size_form.addRow(self.vis_manual_bar_label, self.vis_manual_bar_slider)

        layout.addWidget(size_group)

        # 5. Position Presets
        pos_group = QGroupBox("Position && Edge Attachment", self.visualizer_page)
        pos_layout = QVBoxLayout(pos_group)

        pos_btn_layout = QHBoxLayout()
        for preset in ["Free", "Top", "Bottom", "Left", "Right"]:
            btn = QPushButton(preset, self)
            btn.setObjectName("btn_ghost" if preset != "Bottom" else "btn_secondary")
            btn.clicked.connect(lambda _, p=preset: self._on_vis_preset_clicked(p))
            pos_btn_layout.addWidget(btn)
        pos_layout.addLayout(pos_btn_layout)

        pos_form = QFormLayout()
        self.vis_orientation_combo = QComboBox(self)
        self.vis_orientation_combo.addItems(["Bottom", "Top", "Left", "Right", "Free"])
        self.vis_orientation_combo.currentTextChanged.connect(self._on_vis_orientation_changed)
        pos_form.addRow("Current Orientation Preset:", self.vis_orientation_combo)
        pos_layout.addLayout(pos_form)
        layout.addWidget(pos_group)

        # 6. Behavior & Dynamics
        vis_beh_group = QGroupBox("Behavior && Window Dynamics", self.visualizer_page)
        vis_beh_form = QFormLayout(vis_beh_group)

        self.vis_opacity_slider = ValueSlider(10, 100, 100, "%", self)
        self.vis_opacity_slider.valueChanged.connect(self._on_control_changed)
        vis_beh_form.addRow("Overall Visualizer Opacity:", self.vis_opacity_slider)

        self.vis_sensitivity_slider = ValueSlider(10, 200, 100, "%", self)
        self.vis_sensitivity_slider.valueChanged.connect(self._on_control_changed)
        vis_beh_form.addRow("Audio Sensitivity:", self.vis_sensitivity_slider)

        self.vis_smoothing_slider = ValueSlider(10, 95, 75, "%", self)
        self.vis_smoothing_slider.valueChanged.connect(self._on_control_changed)
        vis_beh_form.addRow("Animation Smoothing:", self.vis_smoothing_slider)

        self.vis_click_through_switch = ToggleSwitch("Click-Through Mode (Mouse clicks pass through)", self)
        self.vis_click_through_switch.toggled.connect(self._on_control_changed)
        vis_beh_form.addRow("", self.vis_click_through_switch)

        self.vis_top_switch = ToggleSwitch("Keep Visualizer Always on Top", self)
        self.vis_top_switch.toggled.connect(self._on_control_changed)
        vis_beh_form.addRow("", self.vis_top_switch)

        self.vis_exclude_capture_switch = ToggleSwitch("Exclude Visualizer from OBS / Discord Screen Capture", self)
        self.vis_exclude_capture_switch.toggled.connect(self._on_control_changed)
        vis_beh_form.addRow("", self.vis_exclude_capture_switch)
        layout.addWidget(vis_beh_group)

        # 7. Reset Visualizer Settings
        reset_layout = QHBoxLayout()
        reset_layout.addStretch(1)
        self.btn_reset_vis = QPushButton("Reset Visualizer Settings", self)
        self.btn_reset_vis.setObjectName("btn_secondary")
        self.btn_reset_vis.setIcon(get_icon("refresh", color=PALETTE.text_secondary))
        self.btn_reset_vis.clicked.connect(self._on_reset_visualizer_clicked)
        reset_layout.addWidget(self.btn_reset_vis)
        layout.addLayout(reset_layout)

    def _on_vis_shape_changed(self, shape_text: str):
        is_rounded = shape_text == "Rounded Bar"
        self.vis_corner_radius_slider.setVisible(is_rounded)
        self.vis_corner_radius_row_label.setVisible(is_rounded)
        self._on_control_changed()

    def _on_vis_color_mode_changed(self, mode_text: str):
        is_solid = mode_text == "Solid"
        is_grad = mode_text == "Gradient"
        self.btn_vis_color.setVisible(is_solid)
        self.vis_solid_color_label.setVisible(is_solid)
        self.gradient_editor.setVisible(is_grad)
        self.vis_grad_dir_combo.setVisible(is_grad)
        self.vis_grad_dir_label.setVisible(is_grad)
        self._on_control_changed()

    def _on_vis_auto_bar_toggled(self, checked: bool):
        self.vis_manual_bar_slider.setEnabled(not checked)
        self.vis_manual_bar_label.setEnabled(not checked)
        self._on_control_changed()

    def _on_vis_preset_clicked(self, preset: str):
        self.vis_orientation_combo.setCurrentText(preset)
        parent_widget = self.parent()
        if parent_widget and hasattr(parent_widget, 'visualizer_manager'):
            parent_widget.visualizer_manager.set_preset_position(preset)
            self._on_control_changed()

    def _on_vis_orientation_changed(self, text: str):
        self._on_control_changed()

    def _on_vis_color_changed(self, color_hex: str):
        self.working_settings["visualizer_color"] = color_hex
        self._on_control_changed()

    def _on_reset_visualizer_clicked(self):
        defaults = self.settings_manager.reset_visualizer_settings()
        self.working_settings.update(defaults)
        self._load_current_values()
        self._on_control_changed()
        AppLogger.instance().log("🔄 [Visualizer] Visualizer settings reset to defaults.", force=True)

    # --- Page 2: Typography ---
    def _init_typography_page(self):
        layout = QVBoxLayout(self.typography_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        type_group = QGroupBox("Font && Formatting", self.typography_page)
        form = QFormLayout(type_group)

        self.font_combo = QFontComboBox(self)
        self.font_combo.currentFontChanged.connect(self._on_control_changed)
        form.addRow("Font Family:", self.font_combo)

        self.font_size_slider = ValueSlider(12, 48, 24, " pt", self)
        self.font_size_slider.valueChanged.connect(self._on_control_changed)
        form.addRow("Font Size:", self.font_size_slider)

        self.bold_switch = ToggleSwitch("Bold Typography", self)
        self.bold_switch.toggled.connect(self._on_control_changed)
        form.addRow("", self.bold_switch)

        self.align_combo = QComboBox(self)
        self.align_combo.addItems(["Left", "Center", "Right"])
        self.align_combo.currentTextChanged.connect(self._on_control_changed)
        form.addRow("Text Alignment:", self.align_combo)

        self.show_info_switch = ToggleSwitch("Show Song Title && Artist Sub-label", self)
        self.show_info_switch.toggled.connect(self._on_control_changed)
        form.addRow("", self.show_info_switch)

        layout.addWidget(type_group)

    # --- Page 2: Behavior & Source ---
    def _init_behavior_page(self):
        layout = QVBoxLayout(self.behavior_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        source_group = QGroupBox("Target Media Source Window", self.behavior_page)
        source_layout = QHBoxLayout(source_group)
        self.source_combo = QComboBox(self)
        self.source_combo.currentIndexChanged.connect(self._on_source_combo_changed)
        source_layout.addWidget(self.source_combo, 1)

        self.btn_refresh_sources = QPushButton("Refresh", self)
        self.btn_refresh_sources.setIcon(get_icon("refresh"))
        self.btn_refresh_sources.clicked.connect(self._refresh_media_sources)
        source_layout.addWidget(self.btn_refresh_sources)
        layout.addWidget(source_group)

        behavior_group = QGroupBox("Overlay Behavior", self.behavior_page)
        form = QFormLayout(behavior_group)

        self.top_switch = ToggleSwitch("Keep Window Always on Top", self)
        self.top_switch.toggled.connect(self._on_control_changed)
        form.addRow("", self.top_switch)

        self.lock_switch = ToggleSwitch("Lock Position (Prevent Mouse Dragging)", self)
        self.lock_switch.toggled.connect(self._on_control_changed)
        form.addRow("", self.lock_switch)

        self.click_through_switch = ToggleSwitch("Click-Through Mode (Mouse clicks pass through)", self)
        self.click_through_switch.toggled.connect(self._on_control_changed)
        form.addRow("", self.click_through_switch)

        self.exclude_capture_switch = ToggleSwitch("Exclude Overlay from OBS / Discord Screen Capture", self)
        self.exclude_capture_switch.toggled.connect(self._on_control_changed)
        form.addRow("", self.exclude_capture_switch)

        self.auto_hide_switch = ToggleSwitch("Auto-Hide Overlay when Media is Paused or Stopped", self)
        self.auto_hide_switch.toggled.connect(self._on_control_changed)
        form.addRow("", self.auto_hide_switch)

        self.auto_resize_switch = ToggleSwitch("Auto-adapt Window Height to Fit Lyrics", self)
        self.auto_resize_switch.toggled.connect(self._on_control_changed)
        form.addRow("", self.auto_resize_switch)

        self.snap_corners_switch = ToggleSwitch("Snap to Screen Borders && Corners when Dragged Near Edges", self)
        self.snap_corners_switch.toggled.connect(self._on_control_changed)
        form.addRow("", self.snap_corners_switch)

        self.context_lines_slider = ValueSlider(0, 5, 2, " lines", self)
        self.context_lines_slider.valueChanged.connect(self._on_control_changed)
        form.addRow("Context Lines (Before && After):", self.context_lines_slider)

        self.sync_offset_slider = ValueSlider(-5000, 5000, 0, " ms", self)
        self.sync_offset_slider.valueChanged.connect(self._on_control_changed)
        form.addRow("Global Sync Offset Nudge:", self.sync_offset_slider)

        layout.addWidget(behavior_group)

    # --- Page 3: Animations ---
    def _init_animations_page(self):
        layout = QVBoxLayout(self.animations_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        anim_group = QGroupBox("Spotify Line Scroll Animation", self.animations_page)
        form = QFormLayout(anim_group)

        self.anim_speed_slider = ValueSlider(100, 800, 400, " ms", self)
        self.anim_speed_slider.valueChanged.connect(self._on_control_changed)
        form.addRow("Scroll Transition Duration:", self.anim_speed_slider)

        layout.addWidget(anim_group)

    # --- Page 4: Shortcuts ---
    def _init_shortcuts_page(self):
        layout = QVBoxLayout(self.shortcuts_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        sc_group = QGroupBox("Global Hotkey Shortcuts", self.shortcuts_page)
        form = QFormLayout(sc_group)

        self.keycap_toggle = KeycapWidget("Ctrl+H", self)
        self.keycap_toggle.keySequenceChanged.connect(self._on_control_changed)
        form.addRow("Toggle Lyrics Visibility:", self.keycap_toggle)

        self.keycap_vis_toggle = KeycapWidget("Ctrl+Shift+V", self)
        self.keycap_vis_toggle.keySequenceChanged.connect(self._on_control_changed)
        form.addRow("Toggle Visualizer Visibility:", self.keycap_vis_toggle)

        self.keycap_refresh = KeycapWidget("Ctrl+R", self)
        self.keycap_refresh.keySequenceChanged.connect(self._on_control_changed)
        form.addRow("Reload / Refresh Lyrics:", self.keycap_refresh)

        self.keycap_minus = KeycapWidget("Ctrl+Left", self)
        self.keycap_minus.keySequenceChanged.connect(self._on_control_changed)
        form.addRow("Nudge Timing Earlier (-250ms):", self.keycap_minus)

        self.keycap_plus = KeycapWidget("Ctrl+Right", self)
        self.keycap_plus.keySequenceChanged.connect(self._on_control_changed)
        form.addRow("Nudge Timing Later (+250ms):", self.keycap_plus)

        layout.addWidget(sc_group)

    # --- Page 5: Advanced & Cache ---
    def _init_advanced_page(self):
        layout = QVBoxLayout(self.advanced_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # Cache Card
        cache_group = QGroupBox("Disk Cache Management", self.advanced_page)
        cache_layout = QVBoxLayout(cache_group)

        self.cache_count_label = QLabel("Loading cache status...", self)
        cache_layout.addWidget(self.cache_count_label)

        btn_clear_cache = QPushButton("Clear All Disk Caches", self)
        btn_clear_cache.setIcon(get_icon("clear"))
        btn_clear_cache.clicked.connect(self._clear_disk_cache)
        cache_layout.addWidget(btn_clear_cache)
        layout.addWidget(cache_group)

        # Manual Search Card
        search_group = QGroupBox("Manual Lyric Correction", self.advanced_page)
        search_layout = QVBoxLayout(search_group)

        search_info = QLabel("Manually search LRCLIB database and bind custom lyrics to the active song.", self)
        search_info.setWordWrap(True)
        search_layout.addWidget(search_info)

        btn_manual_search = QPushButton("Search Lyrics Database...", self)
        btn_manual_search.setIcon(get_icon("search"))
        btn_manual_search.clicked.connect(self._open_manual_search)
        search_layout.addWidget(btn_manual_search)
        layout.addWidget(search_group)

        self._refresh_cache_count()

    def _refresh_cache_count(self):
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".lyrics_cache")
        count = len(os.listdir(cache_dir)) if os.path.exists(cache_dir) else 0
        self.cache_count_label.setText(f"Cached Songs on Disk: {count} JSON files")

    def _clear_disk_cache(self):
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".lyrics_cache")
        if os.path.exists(cache_dir):
            for f in os.listdir(cache_dir):
                if f.endswith(".json"):
                    try:
                        os.remove(os.path.join(cache_dir, f))
                    except Exception:
                        pass
        self._refresh_cache_count()
        AppLogger.instance().log("🧹 [Cache Cleared] All disk caches successfully purged.", force=True)

    def _open_manual_search(self):
        parent_widget = self.parent()
        client = getattr(parent_widget, 'lrclib', None) or LRCLibClient()
        artist = getattr(parent_widget, 'current_song_artist', '')
        title = getattr(parent_widget, 'current_song_title', '')

        dlg = ManualSearchDialog(client, initial_artist=artist, initial_title=title, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_result:
            res = dlg.selected_result
            synced = res.get('syncedLyrics') or ""
            plain = res.get('plainLyrics') or ""
            if parent_widget and hasattr(parent_widget, '_on_lyrics_fetched'):
                parent_widget._on_lyrics_fetched(res.get('artistName', artist), res.get('trackName', title), synced, plain)
                AppLogger.instance().log(f"🎯 [Manual Bind] Bound manual lyrics for '{artist} - {title}'", force=True)

    # 3. Collapsible Bottom Live Logs Drawer
    def _init_logs_drawer(self, parent_layout: QVBoxLayout):
        self.drawer_container = QWidget(self)
        drawer_layout = QVBoxLayout(self.drawer_container)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        drawer_layout.setSpacing(0)

        # Drawer Toggle Header Button
        self.btn_toggle_drawer = QPushButton("Console && Diagnostics Log (Show)", self.drawer_container)
        self.btn_toggle_drawer.setCheckable(True)
        self.btn_toggle_drawer.setIcon(get_icon("logs", color=PALETTE.accent))
        self.btn_toggle_drawer.setStyleSheet(
            f"background-color: {PALETTE.surface};"
            f" color: {PALETTE.text_secondary};"
            f" border-top: 1px solid {PALETTE.border};"
            f" border-bottom: none;"
            f" border-left: none;"
            f" border-right: none;"
            f" font-weight: 600;"
            f" font-size: 9pt;"
            f" padding: 6px 14px;"
            f" text-align: left;"
        )
        self.btn_toggle_drawer.toggled.connect(self._toggle_logs_drawer)
        drawer_layout.addWidget(self.btn_toggle_drawer)

        # Collapsible Content Frame
        self.drawer_content = QFrame(self.drawer_container)
        self.drawer_content.setFixedHeight(180)
        self.drawer_content.hide()
        content_layout = QVBoxLayout(self.drawer_content)
        content_layout.setContentsMargins(10, 8, 10, 8)
        content_layout.setSpacing(6)

        self.log_text_edit = QTextEdit(self.drawer_content)
        self.log_text_edit.setObjectName("logConsole")
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setPlaceholderText("Real-time diagnostic logs will appear here...")
        content_layout.addWidget(self.log_text_edit)

        # Bottom Bar Buttons
        tools_layout = QHBoxLayout()
        self.auto_scroll_check = QCheckBox("Auto-scroll", self.drawer_content)
        self.auto_scroll_check.setChecked(True)
        tools_layout.addWidget(self.auto_scroll_check)
        tools_layout.addStretch()

        btn_clear = QPushButton("Clear", self.drawer_content)
        btn_clear.setIcon(get_icon("clear"))
        btn_clear.clicked.connect(self.log_text_edit.clear)
        tools_layout.addWidget(btn_clear)

        btn_copy = QPushButton("Copy Logs", self.drawer_content)
        btn_copy.setIcon(get_icon("copy"))
        btn_copy.clicked.connect(self._copy_logs_to_clipboard)
        tools_layout.addWidget(btn_copy)

        btn_diag = QPushButton("Copy Diagnostics", self.drawer_content)
        btn_diag.setIcon(get_icon("info"))
        btn_diag.clicked.connect(self._copy_diagnostics)
        tools_layout.addWidget(btn_diag)

        content_layout.addLayout(tools_layout)
        drawer_layout.addWidget(self.drawer_content)
        parent_layout.addWidget(self.drawer_container)

    def _toggle_logs_drawer(self, checked: bool):
        if checked:
            self.drawer_content.show()
            self.btn_toggle_drawer.setText("Console && Diagnostics Log (Hide)")
        else:
            self.drawer_content.hide()
            self.btn_toggle_drawer.setText("Console && Diagnostics Log (Show)")

    # 4. Sticky Footer Action Bar
    def _init_sticky_footer(self, parent_layout: QVBoxLayout):
        footer_frame = QFrame(self)
        footer_frame.setObjectName("stickyFooter")
        footer_frame.setFixedHeight(50)
        footer_layout = QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(14, 8, 14, 8)

        self.btn_reset = QPushButton("Reset Defaults", footer_frame)
        self.btn_reset.setObjectName("btn_ghost")
        self.btn_reset.clicked.connect(self._on_reset)
        footer_layout.addWidget(self.btn_reset)

        footer_layout.addStretch()

        # Standard Windows action order: Apply → Cancel → OK (primary rightmost)
        self.btn_apply = QPushButton("Apply", footer_frame)
        self.btn_apply.setIcon(get_icon("save"))
        self.btn_apply.clicked.connect(self._on_apply)
        footer_layout.addWidget(self.btn_apply)

        self.btn_cancel = QPushButton("Cancel", footer_frame)
        self.btn_cancel.setIcon(get_icon("close"))
        self.btn_cancel.clicked.connect(self.reject)
        footer_layout.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton("OK", footer_frame)
        self.btn_ok.setObjectName("btn_primary")
        self.btn_ok.setIcon(get_icon("check", color=PALETTE.bg))
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_ok)
        footer_layout.addWidget(self.btn_ok)

        parent_layout.addWidget(footer_frame)

    # --- Data Loading & Event Handlers ---
    def _refresh_media_sources(self):
        player = self.player or (getattr(self.parent(), 'player', None) if self.parent() else None)
        if not player:
            try:
                from lyrune.spotify_player import SpotifyPlayer
                player = SpotifyPlayer()
            except Exception:
                player = None

        if player and hasattr(player, 'get_available_media_sources'):
            sessions = player.get_available_media_sources()
        elif player and hasattr(player, 'get_active_media_sessions'):
            sessions = player.get_active_media_sessions()
        else:
            sessions = [{'name': "Auto-Detect Active Player", 'id': "Auto-Detect"}]

        selected_id = self.working_settings.get("selected_media_source", "Auto-Detect")

        self.source_combo.blockSignals(True)
        self.source_combo.clear()

        selected_index = 0
        for idx, item in enumerate(sessions):
            clean_name = item.get('name', 'Unknown')
            target_id = item.get('id', clean_name)

            lower_name = clean_name.lower()
            lower_id = target_id.lower()

            if "spotify" in lower_name or "spotify" in lower_id:
                icon = get_icon("music")
            elif any(b in lower_name or b in lower_id for b in ["browser", "chrome", "brave", "edge", "firefox", "opera"]):
                icon = get_icon("browser")
            else:
                icon = get_icon("auto_detect")

            self.source_combo.addItem(icon, clean_name, target_id)
            if target_id == selected_id or clean_name == selected_id:
                selected_index = idx

        self.source_combo.setCurrentIndex(selected_index)
        self.source_combo.blockSignals(False)

    def _on_source_combo_changed(self, index: int):
        self._on_control_changed()

    def _on_preset_combo_changed(self, preset_name: str):
        if preset_name in PRESETS:
            preset = PRESETS[preset_name]
            self.working_settings.update(preset)
            self._load_current_values()
            self._update_preview()

    def _on_color_swatch_changed(self, color_hex: str):
        # Sync color widget values back into working_settings so preset
        # switches don't discard the user's color picks.
        self.working_settings["text_color"] = self.btn_text_color.color()
        self.working_settings["bg_color"] = self.btn_bg_color.color()
        self.working_settings["shadow_color"] = self.btn_shadow_color.color()
        self._update_preview()

    def _on_active_opacity_changed(self, value: int):
        if getattr(self, '_is_initializing', False):
            return
        if self.link_opacity_switch.isChecked():
            # Scale context line opacity proportionally with active opacity
            proportional_context = int(45 * (value / 100.0))
            self.context_opacity_slider.setValue(max(0, min(100, proportional_context)))
        self._update_preview()

    def _on_control_changed(self):
        self._update_preview()
        if not getattr(self, '_is_initializing', False):
            s = self._gather_settings()
            self.working_settings.update(s)
            parent_widget = self.parent()
            if parent_widget and hasattr(parent_widget, 'visualizer_manager'):
                parent_widget.visualizer_manager.apply_settings(s)
            if hasattr(self, 'vis_preview'):
                self.vis_preview.update_style(s)

    def _load_current_values(self):
        s = self.working_settings
        self.font_combo.setCurrentFont(QFont(s.get("font_family", "Segoe UI")))
        self.font_size_slider.setValue(s.get("font_size", 24))
        self.bold_switch.setChecked_silent(s.get("font_bold", True))
        self.align_combo.setCurrentText(s.get("text_align", "Center"))
        self.show_info_switch.setChecked_silent(s.get("show_song_info", True))

        self.btn_text_color.setColor(s.get("text_color", "#FFFFFF"))
        self.btn_bg_color.setColor(s.get("bg_color", "#000000"))
        self.btn_shadow_color.setColor(s.get("shadow_color", "#000000"))

        self.opacity_slider.setValue(s.get("bg_opacity", 0))
        self.active_opacity_slider.setValue(s.get("active_line_opacity", 100))
        self.context_opacity_slider.setValue(s.get("context_line_opacity", 45))
        self.shadow_blur_slider.setValue(s.get("shadow_blur", 8))

        self.link_opacity_switch.setChecked_silent(s.get("link_opacity_levels", True))
        self.active_outline_switch.setChecked_silent(s.get("active_text_outline", True))
        self.border_switch.setChecked_silent(s.get("border_enabled", False))
        self.adaptive_color_switch.setChecked_silent(s.get("adaptive_color", False))
        self.shadow_switch.setChecked_silent(s.get("shadow_enabled", True))

        self.top_switch.setChecked_silent(s.get("always_on_top", True))
        self.lock_switch.setChecked_silent(s.get("lock_position", False))
        self.click_through_switch.setChecked_silent(s.get("click_through", False))
        self.exclude_capture_switch.setChecked_silent(s.get("exclude_from_capture", False))
        self.auto_hide_switch.setChecked_silent(s.get("auto_hide_on_pause", False))
        self.auto_resize_switch.setChecked_silent(s.get("auto_resize_height", True))
        self.snap_corners_switch.setChecked_silent(s.get("snap_to_corners", True))

        self.context_lines_slider.setValue(s.get("context_lines", 2))
        self.sync_offset_slider.setValue(s.get("sync_offset_ms", 0))
        self.anim_speed_slider.setValue(s.get("animation_speed_ms", 400))

        self.keycap_toggle.setKeySequence(QKeySequence(s.get("shortcut_toggle_overlay", "Ctrl+H")))
        self.keycap_vis_toggle.setKeySequence(QKeySequence(s.get("shortcut_toggle_visualizer", "Ctrl+Shift+V")))
        self.keycap_refresh.setKeySequence(QKeySequence(s.get("shortcut_refresh", "Ctrl+R")))
        self.keycap_minus.setKeySequence(QKeySequence(s.get("shortcut_nudge_minus", "Ctrl+Left")))
        self.keycap_plus.setKeySequence(QKeySequence(s.get("shortcut_nudge_plus", "Ctrl+Right")))

        # Visualizer Studio settings loading
        self.vis_enable_switch.setChecked_silent(s.get("visualizer_enabled", True))
        self.vis_style_combo.setCurrentText(s.get("visualizer_style", "Pill Bars"))

        shape = s.get("visualizer_shape", "Pill")
        self.vis_shape_combo.setCurrentText(shape)
        self.vis_corner_radius_slider.setValue(s.get("visualizer_corner_radius", 4))
        self._on_vis_shape_changed(shape)

        self.vis_orientation_combo.setCurrentText(s.get("visualizer_orientation", "Bottom").capitalize())
        self.vis_width_slider.setValue(s.get("visualizer_width", 320))
        self.vis_height_slider.setValue(s.get("visualizer_height", 64))
        self.vis_bar_width_slider.setValue(s.get("visualizer_bar_width", 4))
        self.vis_bar_spacing_slider.setValue(s.get("visualizer_bar_spacing", 3))
        self.vis_max_height_slider.setValue(s.get("visualizer_max_height", 100))

        auto_bars = s.get("visualizer_auto_bar_count", True)
        self.vis_auto_bar_switch.setChecked_silent(auto_bars)
        self.vis_manual_bar_slider.setValue(s.get("visualizer_bar_count", 32))
        self._on_vis_auto_bar_toggled(auto_bars)

        color_mode = s.get("visualizer_color_mode", "Solid")
        self.vis_color_mode_combo.setCurrentText(color_mode)
        self.btn_vis_color.setColor(s.get("visualizer_color", "#FFFFFF"))

        stops = s.get("visualizer_gradient_stops", [
            {"pos": 0.0, "color": "#FF4D8D"},
            {"pos": 0.5, "color": "#8B5CF6"},
            {"pos": 1.0, "color": "#3B82F6"}
        ])
        self.gradient_editor.set_stops(stops)
        self.vis_grad_dir_combo.setCurrentText(s.get("visualizer_gradient_direction", "Follow Visualizer"))
        self._on_vis_color_mode_changed(color_mode)

        self.vis_opacity_slider.setValue(s.get("visualizer_opacity", 100))
        self.vis_sensitivity_slider.setValue(s.get("visualizer_sensitivity", 100))
        self.vis_smoothing_slider.setValue(s.get("visualizer_smoothing", 75))
        self.vis_click_through_switch.setChecked_silent(s.get("visualizer_click_through", False))
        self.vis_top_switch.setChecked_silent(s.get("visualizer_always_on_top", True))
        self.vis_exclude_capture_switch.setChecked_silent(s.get("visualizer_exclude_from_capture", False))

        if hasattr(self, 'vis_preview'):
            self.vis_preview.update_style(s)

        self._refresh_media_sources()

    def _update_preview(self):
        if getattr(self, '_is_initializing', False):
            return

        s = self._gather_settings()
        self.preview_sub.setVisible(s["show_song_info"])

        qbg = QColor(s["bg_color"])
        alpha = int((s["bg_opacity"] / 100.0) * 255)
        rgba_str = f"rgba({qbg.red()}, {qbg.green()}, {qbg.blue()}, {alpha / 255.0:.2f})"

        border_css = f"border: 1px solid {PALETTE.border};" if s.get("border_enabled") else "border: none;"
        self.preview_container.setStyleSheet(f"background-color: {rgba_str}; border-radius: 8px; {border_css}")
        self.preview_renderer.update_style(s)

        if hasattr(self, 'vis_preview'):
            self.vis_preview.update_style(s)

        # Update Now Playing pill title
        parent_widget = self.parent()
        if parent_widget and hasattr(parent_widget, 'current_song_title') and parent_widget.current_song_title:
            self.title_bar.set_now_playing(f"{parent_widget.current_song_artist} - {parent_widget.current_song_title}")

    def _gather_settings(self) -> Dict[str, Any]:
        selected_source_id = self.source_combo.currentData()
        return {
            "font_family": self.font_combo.currentFont().family(),
            "font_size": self.font_size_slider.value(),
            "font_bold": self.bold_switch.isChecked(),
            "text_align": self.align_combo.currentText(),
            "show_song_info": self.show_info_switch.isChecked(),
            "text_color": self.btn_text_color.color(),
            "bg_color": self.btn_bg_color.color(),
            "bg_opacity": self.opacity_slider.value(),
            "link_opacity_levels": self.link_opacity_switch.isChecked(),
            "active_line_opacity": self.active_opacity_slider.value(),
            "context_line_opacity": self.context_opacity_slider.value(),
            "active_text_outline": self.active_outline_switch.isChecked(),
            "border_enabled": self.border_switch.isChecked(),
            "adaptive_color": self.adaptive_color_switch.isChecked(),
            "shadow_enabled": self.shadow_switch.isChecked(),
            "shadow_color": self.btn_shadow_color.color(),
            "shadow_blur": self.shadow_blur_slider.value(),
            "always_on_top": self.top_switch.isChecked(),
            "lock_position": self.lock_switch.isChecked(),
            "click_through": self.click_through_switch.isChecked(),
            "exclude_from_capture": self.exclude_capture_switch.isChecked(),
            "auto_hide_on_pause": self.auto_hide_switch.isChecked(),
            "context_lines": self.context_lines_slider.value(),
            "auto_resize_height": self.auto_resize_switch.isChecked(),
            "snap_to_corners": self.snap_corners_switch.isChecked(),
            "selected_media_source": selected_source_id or "Auto-Detect",
            "sync_offset_ms": self.sync_offset_slider.value(),
            "animation_speed_ms": self.anim_speed_slider.value(),
            "shortcut_toggle_overlay": self.keycap_toggle.keySequence().toString(),
            "shortcut_toggle_visualizer": self.keycap_vis_toggle.keySequence().toString(),
            "shortcut_refresh": self.keycap_refresh.keySequence().toString(),
            "shortcut_nudge_minus": self.keycap_minus.keySequence().toString(),
            "shortcut_nudge_plus": self.keycap_plus.keySequence().toString(),

            # Standalone Visualizer settings
            "visualizer_enabled": self.vis_enable_switch.isChecked(),
            "visualizer_style": self.vis_style_combo.currentText(),
            "visualizer_shape": self.vis_shape_combo.currentText(),
            "visualizer_corner_radius": self.vis_corner_radius_slider.value(),
            "visualizer_auto_bar_count": self.vis_auto_bar_switch.isChecked(),
            "visualizer_bar_count": self.vis_manual_bar_slider.value(),
            "visualizer_orientation": self.vis_orientation_combo.currentText().upper(),
            "visualizer_snap_edge": self.vis_orientation_combo.currentText().upper() if self.vis_orientation_combo.currentText() != "Free" else "NONE",
            "visualizer_width": self.vis_width_slider.value(),
            "visualizer_height": self.vis_height_slider.value(),
            "visualizer_opacity": self.vis_opacity_slider.value(),
            "visualizer_color": self.btn_vis_color.color(),
            "visualizer_color_mode": self.vis_color_mode_combo.currentText(),
            "visualizer_gradient_stops": self.gradient_editor.get_stops(),
            "visualizer_gradient_direction": self.vis_grad_dir_combo.currentText(),
            "visualizer_bar_width": self.vis_bar_width_slider.value(),
            "visualizer_bar_spacing": self.vis_bar_spacing_slider.value(),
            "visualizer_max_height": self.vis_max_height_slider.value(),
            "visualizer_sensitivity": self.vis_sensitivity_slider.value(),
            "visualizer_smoothing": self.vis_smoothing_slider.value(),
            "visualizer_click_through": self.vis_click_through_switch.isChecked(),
            "visualizer_always_on_top": self.vis_top_switch.isChecked(),
            "visualizer_exclude_from_capture": self.vis_exclude_capture_switch.isChecked(),
        }

    def _on_apply(self):
        new_settings = self._gather_settings()
        shortcuts = [
            new_settings.get("shortcut_toggle_overlay"),
            new_settings.get("shortcut_toggle_visualizer"),
            new_settings.get("shortcut_refresh"),
            new_settings.get("shortcut_nudge_minus"),
            new_settings.get("shortcut_nudge_plus"),
        ]
        non_empty = [sc for sc in shortcuts if sc]
        if len(non_empty) != len(set(non_empty)):
            AppLogger.instance().log("⚠️ [Shortcut Conflict Warning] Duplicate global hotkeys detected! Please assign distinct shortcuts.", force=True)

        self.working_settings.update(new_settings)
        self.settings_manager.update(new_settings)
        self.settings_changed.emit(new_settings)

    def _on_ok(self):
        self._on_apply()
        self.accept()

    def _on_reset(self):
        defaults = self.settings_manager.reset_to_defaults()
        self.working_settings = dict(defaults)
        self._load_current_values()
        self._update_preview()
        self.settings_changed.emit(defaults)

    # --- Logs & Diagnostics Helpers ---
    def _load_log_history(self):
        self.log_text_edit.clear()
        for timestamp, message in AppLogger.instance().history:
            self._append_log_entry(timestamp, message)

    def _append_log_entry(self, timestamp: str, message: str):
        clean_msg = re.sub(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F600-\U0001F6FF]', '', message).strip()
        color = PALETTE.success
        level_tag = "[INFO]"
        if any(kw in message for kw in ["ERROR", "Exception", "No lyrics", "failed", "⚠️", "❌"]) or "failed" in message.lower():
            color = PALETTE.error
            level_tag = "[ERROR]"
        elif any(kw in message for kw in ["Selected", "Track Changed", "Match", "🎯"]):
            color = PALETTE.info
            level_tag = "[MATCH]"
        elif "LRCLib" in message or "🌐" in message:
            color = PALETTE.info
            level_tag = "[NETWORK]"
        elif "📌" in message or "NOTICE" in message:
            color = PALETTE.warning
            level_tag = "[NOTICE]"

        html_entry = (
            f'<span style="color: {PALETTE.text_secondary}; font-family: monospace;">[{timestamp}]</span> '
            f'<b style="color: {color}; font-family: monospace;">{level_tag}</b> '
            f'<span style="color: {PALETTE.text_primary};">{clean_msg}</span>'
        )
        self.log_text_edit.append(html_entry)

        if self.auto_scroll_check.isChecked():
            sb = self.log_text_edit.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _copy_logs_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.log_text_edit.toPlainText())

    def _copy_diagnostics(self):
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".lyrics_cache")
        cached_count = len(os.listdir(cache_dir)) if os.path.exists(cache_dir) else 0
        diag = [
            "==================================================",
            " Lyrune System Diagnostic Report",
            "==================================================",
            f"OS Platform: {platform.system()} {platform.release()} ({platform.version()})",
            f"Python Version: {sys.version.split()[0]}",
            f"PyQt6 Version: {getattr(__import__('PyQt6.QtCore', fromlist=['PYQT_VERSION_STR']), 'PYQT_VERSION_STR', '6.x')}",
            f"Selected Target Source: {self.working_settings.get('selected_media_source', 'Auto-Detect')}",
            f"Always on Top: {self.working_settings.get('always_on_top', True)}",
            f"Click-Through Mode: {self.working_settings.get('click_through', False)}",
            f"Screen Capture Exclusion: {self.working_settings.get('exclude_from_capture', False)}",
            f"Cached Songs (Disk): {cached_count} files",
            f"Recent Log Buffer Size: {len(AppLogger.instance().history)} entries",
            "==================================================",
            " Visualizer & Audio DSP Engine:",
            "==================================================",
        ]

        parent_widget = self.parent()
        vis_diag = {}
        if parent_widget and hasattr(parent_widget, 'visualizer_manager'):
            vis_diag = parent_widget.visualizer_manager.get_audio_diagnostics()

        diag.extend([
            f"Visualizer Enabled: {self.working_settings.get('visualizer_enabled', True)}",
            f"Visualizer Style: {vis_diag.get('active_style', 'Bars')}",
            f"Audio Capture Source: {vis_diag.get('source_type', 'WASAPI Loopback' if sys.platform == 'win32' else 'Linux Loopback')}",
            f"Audio Stream Capturing: {vis_diag.get('is_capturing', False)}",
            f"Audio Sample Rate: {vis_diag.get('sample_rate', 48000)} Hz",
            f"FFT Analysis Window: {vis_diag.get('fft_size', 2048)} samples (~42.6 ms)",
            f"Frequency Resolution: 25 Hz - 16000 Hz ({vis_diag.get('bar_count', 32)} Log Bands)",
            f"Live Audio RMS Level: {vis_diag.get('rms', 0.0):.4f}",
            f"Live Audio Peak Level: {vis_diag.get('peak', 0.0):.4f}",
            "==================================================",
            "Recent Log History:",
            "==================================================",
        ])
        for ts, msg in list(AppLogger.instance().history)[-25:]:
            diag.append(f"[{ts}] {msg}")

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(diag))
        AppLogger.instance().log("📋 [Diagnostics] System diagnostic report copied to clipboard!", force=True)

    def _disconnect_logger(self):
        if self._log_connected:
            try:
                AppLogger.instance().log_signal.disconnect(self._append_log_entry)
                self._log_connected = False
            except Exception:
                pass

    def _minimize_to_taskbar(self):
        """Minimizes the frameless settings window cleanly to the OS Taskbar."""
        self.setWindowState(Qt.WindowState.WindowMinimized)

    def showEvent(self, event):
        """Ensure native Windows style flags WS_MINIMIZEBOX, WS_SYSMENU & WS_EX_APPWINDOW are set on HWND for taskbar minimization."""
        super().showEvent(event)
        if sys.platform == "win32" and self.winId():
            try:
                import ctypes
                hwnd = int(self.winId())
                GWL_STYLE = -16
                GWL_EXSTYLE = -20
                WS_MINIMIZEBOX = 0x00020000
                WS_SYSMENU = 0x00080000
                WS_EX_APPWINDOW = 0x00040000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX | WS_SYSMENU)
                exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle | WS_EX_APPWINDOW)
            except Exception:
                pass

    def reject(self):
        self._disconnect_logger()
        super().reject()

    def accept(self):
        self._disconnect_logger()
        super().accept()
