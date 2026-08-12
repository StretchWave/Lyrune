from typing import Dict, Any
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QFontComboBox, QSpinBox, QCheckBox, QComboBox, QPushButton,
    QSlider, QColorDialog, QGroupBox, QGraphicsDropShadowEffect, QTextEdit,
    QApplication, QScrollArea, QFrame, QKeySequenceEdit
)
from PyQt6.QtGui import QColor, QFont, QKeySequence

from settings_manager import PRESETS, DEFAULT_SETTINGS
from logger import AppLogger

DARK_THEME_STYLESHEET = """
QDialog {
    background-color: #0F172A;
    color: #F8FAFC;
    font-family: 'Segoe UI', system-ui, sans-serif;
}
QTabWidget::pane {
    border: 1px solid rgba(255, 255, 255, 0.08);
    background: #1E293B;
    border-radius: 10px;
}
QTabBar::tab {
    background: #0F172A;
    color: #94A3B8;
    padding: 8px 14px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
    font-size: 12px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background: #1E293B;
    color: #06B6D4;
    font-weight: bold;
    border-bottom: 2px solid #06B6D4;
}
QLabel {
    color: #E2E8F0;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid rgba(255, 255, 255, 0.08);
    background: rgba(30, 41, 59, 0.5);
    border-radius: 8px;
    margin-top: 12px;
    font-weight: bold;
    color: #06B6D4;
    font-size: 13px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QPushButton {
    background-color: #334155;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #475569;
    border-color: #06B6D4;
}
QPushButton#btn_primary {
    background-color: #2563EB;
    border-color: #3B82F6;
    font-weight: bold;
}
QPushButton#btn_primary:hover {
    background-color: #3B82F6;
}
QSpinBox, QComboBox, QFontComboBox {
    background-color: #1E293B;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 22px;
}
QComboBox QAbstractItemView {
    background-color: #0F172A;
    color: #F8FAFC;
    selection-background-color: #2563EB;
    selection-color: #FFFFFF;
    border: 1px solid #06B6D4;
    border-radius: 6px;
    padding: 4px;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #334155;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #06B6D4;
    border: 2px solid #F8FAFC;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #38BDF8;
}
QCheckBox {
    color: #E2E8F0;
    font-size: 13px;
    spacing: 8px;
}
QTextEdit {
    background-color: #020617;
    color: #38BDF8;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
}
QScrollArea {
    background: transparent;
    border: none;
}
"""


class SettingsDialog(QDialog):
    """
    Settings Window with Live Preview, Theme Presets, Media Source Selection, and Real-Time Logs.

    Improvements:
      - Fixed shrink/resize issue: scrollable tabs & flexible minimum size (380x420).
      - Fixed minimize bug: proper top-level taskbar window flags (Window | WindowMinMaxButtonsHint).
      - Granular Opacity Controls for Active Line and Context Lines with Master Link toggle.
      - Active Line Text Contour / Outline toggle.
      - Sleek Slate Dark Glassmorphism UI palette.
    """
    settings_changed = pyqtSignal(dict)

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.working_settings: Dict[str, Any] = dict(self.settings_manager.settings)

        self._is_initializing = True
        self._log_connected = False

        self._text_color = self.working_settings.get("text_color", "#FFFFFF")
        self._bg_color = self.working_settings.get("bg_color", "#000000")
        self._shadow_color = self.working_settings.get("shadow_color", "#000000")

        self.setWindowTitle("LyricScript Settings & Customization")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)
        self.resize(540, 620)
        self.setMinimumSize(380, 420)
        self.setStyleSheet(DARK_THEME_STYLESHEET)

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
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # --- Top Live Preview Box ---
        preview_box = QGroupBox("Live Preview", self)
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(15, 15, 15, 15)

        self.preview_container = QWidget(preview_box)
        self.preview_container.setFixedHeight(90)
        container_layout = QVBoxLayout(self.preview_container)
        container_layout.setContentsMargins(10, 10, 10, 10)

        self.preview_lyric = QLabel('Yubikiri genman hora demo fuitara', self.preview_container)
        self.preview_lyric.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.preview_sub = QLabel('🎵 Fujii Kaze - Shinunoga E-Wa', self.preview_container)
        self.preview_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_sub.setStyleSheet("color: #AAAAAA; font-size: 11px; font-style: italic;")

        container_layout.addWidget(self.preview_lyric)
        container_layout.addWidget(self.preview_sub)

        self.preview_shadow = QGraphicsDropShadowEffect(self.preview_container)
        self.preview_lyric.setGraphicsEffect(self.preview_shadow)

        preview_layout.addWidget(self.preview_container)
        main_layout.addWidget(preview_box)

        # --- Theme Presets Row ---
        presets_layout = QHBoxLayout()
        presets_label = QLabel("🎨 Theme Presets:", self)
        presets_label.setStyleSheet("font-weight: bold; color: #06B6D4;")
        presets_layout.addWidget(presets_label)

        self.preset_combo = QComboBox(self)
        self.preset_combo.addItem("Select Preset...")
        self.preset_combo.addItems(list(PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._on_preset_combo_changed)
        presets_layout.addWidget(self.preset_combo, 1)

        main_layout.addLayout(presets_layout)

        # --- Tabs ---
        self.tabs = QTabWidget(self)

        self.typography_tab = QWidget()
        self._init_typography_tab()
        self.tabs.addTab(self._wrap_in_scroll_area(self.typography_tab), " Typography")

        self.appearance_tab = QWidget()
        self._init_appearance_tab()
        self.tabs.addTab(self._wrap_in_scroll_area(self.appearance_tab), " Appearance")

        self.behavior_tab = QWidget()
        self._init_behavior_tab()
        self.tabs.addTab(self._wrap_in_scroll_area(self.behavior_tab), " Behavior & Source")

        self.animations_tab = QWidget()
        self._init_animations_tab()
        self.tabs.addTab(self._wrap_in_scroll_area(self.animations_tab), "✨ Animations")

        self.shortcuts_tab = QWidget()
        self._init_shortcuts_tab()
        self.tabs.addTab(self._wrap_in_scroll_area(self.shortcuts_tab), "⌨️ Shortcuts")

        # 6. Live Logs Tab
        self.logs_tab = QWidget()
        self._init_logs_tab()
        self.logs_tab_index = self.tabs.addTab(self._wrap_in_scroll_area(self.logs_tab), "📋 Live Logs")

        main_layout.addWidget(self.tabs)

        # --- Bottom Action Buttons ---
        btn_layout = QHBoxLayout()

        self.btn_reset = QPushButton("Reset Defaults", self)
        self.btn_reset.setStyleSheet("color: #FF6B6B; border-color: #662222;")
        self.btn_reset.clicked.connect(self._on_reset)
        btn_layout.addWidget(self.btn_reset)

        btn_layout.addStretch()

        self.btn_apply = QPushButton("Apply", self)
        self.btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(self.btn_apply)

        self.btn_ok = QPushButton("OK", self)
        self.btn_ok.setObjectName("btn_primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_ok)
        btn_layout.addWidget(self.btn_ok)

        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        main_layout.addLayout(btn_layout)

    def _wrap_in_scroll_area(self, inner_widget: QWidget) -> QWidget:
        """Wraps a tab widget inside a borderless QScrollArea to allow shrinking to any size."""
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner_widget)

        wrapper = QWidget()
        w_layout = QVBoxLayout(wrapper)
        w_layout.setContentsMargins(0, 0, 0, 0)
        w_layout.addWidget(scroll)
        return wrapper

    def _on_preset_combo_changed(self, name: str):
        if getattr(self, '_is_initializing', False) or not name or name == "Select Preset...":
            return
        self._apply_preset(name)


    def _init_typography_tab(self):
        layout = QFormLayout(self.typography_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        self.font_combo = QFontComboBox(self)
        self.font_combo.currentFontChanged.connect(self._on_control_changed)
        layout.addRow("Font Family:", self.font_combo)

        self.size_spin = QSpinBox(self)
        self.size_spin.setRange(10, 72)
        self.size_spin.valueChanged.connect(self._on_control_changed)
        layout.addRow("Font Size (pt):", self.size_spin)

        self.bold_check = QCheckBox("Bold Typography", self)
        self.bold_check.toggled.connect(self._on_control_changed)
        layout.addRow("", self.bold_check)

        self.align_combo = QComboBox(self)
        self.align_combo.addItems(["Left", "Center", "Right"])
        self.align_combo.currentTextChanged.connect(self._on_control_changed)
        layout.addRow("Text Alignment:", self.align_combo)

        self.show_info_check = QCheckBox("Show Song Title & Artist Sub-label", self)
        self.show_info_check.toggled.connect(self._on_control_changed)
        layout.addRow("", self.show_info_check)

    def _init_appearance_tab(self):
        layout = QFormLayout(self.appearance_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        self.btn_text_color = QPushButton("Choose Color...", self)
        self.btn_text_color.clicked.connect(self._pick_text_color)
        layout.addRow("Text Color:", self.btn_text_color)

        self.btn_bg_color = QPushButton("Choose Color...", self)
        self.btn_bg_color.clicked.connect(self._pick_bg_color)
        layout.addRow("Background Color:", self.btn_bg_color)

        self.btn_text_color = QPushButton("Choose Color...", self)
        self.btn_text_color.clicked.connect(self._pick_text_color)
        layout.addRow("Text Color:", self.btn_text_color)

        self.btn_bg_color = QPushButton("Choose Color...", self)
        self.btn_bg_color.clicked.connect(self._pick_bg_color)
        layout.addRow("Background Color:", self.btn_bg_color)

        bg_op_layout = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.opacity_slider.setRange(0, 100)
        self.opacity_label = QLabel("0%", self)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        bg_op_layout.addWidget(self.opacity_slider)
        bg_op_layout.addWidget(self.opacity_label)
        layout.addRow("Background Opacity:", bg_op_layout)

        # --- Line Opacities Group ---
        op_group = QGroupBox("Lyric Line Opacity & Contrast", self.appearance_tab)
        op_layout = QFormLayout(op_group)

        self.link_opacity_check = QCheckBox("🔗 Link Line Opacities (Scale context opacity with active line)", self)
        self.link_opacity_check.toggled.connect(self._on_control_changed)
        op_layout.addRow("", self.link_opacity_check)

        active_op_row = QHBoxLayout()
        self.active_opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.active_opacity_slider.setRange(10, 100)
        self.active_opacity_label = QLabel("100%", self)
        self.active_opacity_slider.valueChanged.connect(self._on_active_opacity_changed)
        active_op_row.addWidget(self.active_opacity_slider)
        active_op_row.addWidget(self.active_opacity_label)
        op_layout.addRow("Active Playing Line Opacity:", active_op_row)

        ctx_op_row = QHBoxLayout()
        self.context_opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.context_opacity_slider.setRange(0, 100)
        self.context_opacity_label = QLabel("45%", self)
        self.context_opacity_slider.valueChanged.connect(self._on_context_opacity_changed)
        ctx_op_row.addWidget(self.context_opacity_slider)
        ctx_op_row.addWidget(self.context_opacity_label)
        op_layout.addRow("Context Lines Opacity:", ctx_op_row)

        self.active_outline_check = QCheckBox("🔲 Text Contour / Border on Active Playing Line", self)
        self.active_outline_check.toggled.connect(self._on_control_changed)
        op_layout.addRow("", self.active_outline_check)

        layout.addRow(op_group)

        self.border_check = QCheckBox("Enable Glass Border (Subtle outline around overlay)", self)
        self.border_check.toggled.connect(self._on_control_changed)
        layout.addRow("", self.border_check)

        self.adaptive_color_check = QCheckBox("✨ Smart Per-Pixel Adaptive Contrast (Invert text over light/dark backgrounds)", self)
        self.adaptive_color_check.toggled.connect(self._on_control_changed)
        layout.addRow("", self.adaptive_color_check)

        self.shadow_check = QCheckBox("Enable Drop Shadow / Outline", self)
        self.shadow_check.toggled.connect(self._on_control_changed)
        layout.addRow("", self.shadow_check)

        self.btn_shadow_color = QPushButton("Choose Shadow Color...", self)
        self.btn_shadow_color.clicked.connect(self._pick_shadow_color)
        layout.addRow("Shadow Color:", self.btn_shadow_color)

        self.shadow_blur_spin = QSpinBox(self)
        self.shadow_blur_spin.setRange(0, 30)
        self.shadow_blur_spin.valueChanged.connect(self._on_control_changed)
        layout.addRow("Shadow Blur Radius:", self.shadow_blur_spin)

    def _init_behavior_tab(self):
        layout = QFormLayout(self.behavior_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # --- Manual Media Source Selector ---
        source_group = QGroupBox("Target Media Source Window", self.behavior_tab)
        source_layout = QVBoxLayout(source_group)

        source_row = QHBoxLayout()
        self.source_combo = QComboBox(self)
        self.source_combo.currentIndexChanged.connect(self._on_source_combo_changed)
        source_row.addWidget(self.source_combo, 1)

        self.btn_refresh_sources = QPushButton("🔄 Refresh", self)
        self.btn_refresh_sources.clicked.connect(self._refresh_media_sources)
        source_row.addWidget(self.btn_refresh_sources)

        source_layout.addLayout(source_row)
        layout.addRow(source_group)

        self.top_check = QCheckBox("Keep Window Always on Top", self)
        self.top_check.toggled.connect(self._on_control_changed)
        layout.addRow("", self.top_check)

        self.lock_check = QCheckBox("Lock Position (Prevent Mouse Dragging)", self)
        self.lock_check.toggled.connect(self._on_control_changed)
        layout.addRow("", self.lock_check)

        self.context_lines_spin = QSpinBox(self)
        self.context_lines_spin.setRange(0, 5)
        self.context_lines_spin.setValue(2)
        self.context_lines_spin.setToolTip("Number of context lyric lines shown before and after the active line (0 to 5).")
        self.context_lines_spin.valueChanged.connect(self._on_control_changed)
        layout.addRow("Context Lines (Before & After):", self.context_lines_spin)

        self.auto_resize_check = QCheckBox("Auto-adapt Window Height to Fit Lyrics", self)
        self.auto_resize_check.toggled.connect(self._on_control_changed)
        layout.addRow("", self.auto_resize_check)

        self.sync_offset_spin = QSpinBox(self)
        self.sync_offset_spin.setRange(-5000, 5000)
        self.sync_offset_spin.setSingleStep(100)
        self.sync_offset_spin.setSuffix(" ms")
        self.sync_offset_spin.setToolTip("Nudge lyric timing earlier (negative) or later (positive). Shortcuts: Ctrl+Left / Ctrl+Right.")
        self.sync_offset_spin.valueChanged.connect(self._on_control_changed)
        layout.addRow("Sync Offset Adjustment:", self.sync_offset_spin)

    def _init_animations_tab(self):
        layout = QFormLayout(self.animations_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # --- Spotify Scroll Animation Speed ---
        speed_group = QGroupBox("Spotify Scroll Animation", self.animations_tab)
        speed_layout = QFormLayout(speed_group)

        speed_row = QHBoxLayout()
        self.anim_speed_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.anim_speed_slider.setRange(100, 800)
        self.anim_speed_slider.setTickInterval(50)
        self.anim_speed_label = QLabel("400ms", self)
        self.anim_speed_slider.valueChanged.connect(self._on_anim_speed_changed)
        speed_row.addWidget(self.anim_speed_slider)
        speed_row.addWidget(self.anim_speed_label)
        speed_layout.addRow("Scroll Speed:", speed_row)

        layout.addRow(speed_group)

        # --- Preview Animation Button ---
        self.btn_preview_anim = QPushButton("▶ Preview Scroll Animation", self)
        self.btn_preview_anim.setObjectName("btn_primary")
        self.btn_preview_anim.clicked.connect(self._preview_animation)
        layout.addRow("", self.btn_preview_anim)

    def _init_shortcuts_tab(self):
        layout = QFormLayout(self.shortcuts_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(14)

        group = QGroupBox("Customizable Global Hotkeys", self.shortcuts_tab)
        g_layout = QFormLayout(group)
        g_layout.setSpacing(12)

        self.ks_toggle = QKeySequenceEdit(self)
        self.ks_toggle.editingFinished.connect(self._on_control_changed)
        g_layout.addRow("Show / Hide Lyrics Overlay:", self.ks_toggle)

        self.ks_refresh = QKeySequenceEdit(self)
        self.ks_refresh.editingFinished.connect(self._on_control_changed)
        g_layout.addRow("Refresh / Reload Lyrics:", self.ks_refresh)

        self.ks_nudge_minus = QKeySequenceEdit(self)
        self.ks_nudge_minus.editingFinished.connect(self._on_control_changed)
        g_layout.addRow("Sync Nudge Earlier (-250ms):", self.ks_nudge_minus)

        self.ks_nudge_plus = QKeySequenceEdit(self)
        self.ks_nudge_plus.editingFinished.connect(self._on_control_changed)
        g_layout.addRow("Sync Nudge Later (+250ms):", self.ks_nudge_plus)

        layout.addRow(group)

        info_label = QLabel(
            "💡 Click any key input field above and press your preferred shortcut key combination.\n"
            "   Pressing Backspace inside an input box clears the shortcut.",
            self.shortcuts_tab
        )
        info_label.setStyleSheet("color: #94A3B8; font-size: 11px; font-style: italic;")
        layout.addRow(info_label)

    def _on_anim_speed_changed(self, val: int):
        self.anim_speed_label.setText(f"{val}ms")
        self._on_control_changed()

    def _preview_animation(self):
        """Cycles the preview through 3 sample lyrics to demonstrate the animation."""
        import itertools
        samples = [
            "Yubikiri genman hora demo fuitara",
            "Shinunoga e-wa anata to ireba",
            "Kono mama zutto zutto hanasanaide",
        ]
        if not hasattr(self, '_preview_cycle'):
            self._preview_cycle = itertools.cycle(samples)
        next_lyric = next(self._preview_cycle)
        self.preview_lyric.setText(next_lyric)
        self._update_preview()

    def _on_source_combo_changed(self, index: int):
        if getattr(self, '_is_initializing', False) or index < 0:
            return
        selected_id = self.source_combo.itemData(index)
        if selected_id:
            self.working_settings["selected_media_source"] = selected_id

    def _refresh_media_sources(self):
        """
        Scans open media sessions and populates the source_combo dropdown.
        Uses async scan request on Windows (results arrive via signal).
        Falls back to sync for immediate display.
        """
        parent_widget = self.parent()
        if parent_widget and hasattr(parent_widget, 'player'):
            player = parent_widget.player
            # Get immediate sync results
            sources = player.get_available_media_sources()

            # Also request async scan for richer results
            player.request_source_scan()

            # Connect async results if worker thread available
            if player._worker_thread and not hasattr(self, '_sources_connected'):
                player._worker_thread.sources_scanned.connect(self._on_sources_scanned)
                self._sources_connected = True
        else:
            sources = [{'name': "✨ Auto-Detect (Active Session)", 'id': "Auto-Detect"}]

        self._populate_source_combo(sources)

    def _on_sources_scanned(self, sources: list):
        """Async callback when source scan completes on worker thread."""
        self._populate_source_combo(sources)

    def _populate_source_combo(self, sources: list):
        """Populates the source combo box with given source list."""
        self.source_combo.clear()
        selected_id = self.working_settings.get("selected_media_source", "Auto-Detect")
        selected_index = 0

        for idx, item in enumerate(sources):
            self.source_combo.addItem(item['name'], item['id'])
            if item['id'] == selected_id or item['name'] == selected_id:
                selected_index = idx

        self.source_combo.setCurrentIndex(selected_index)

    def _init_logs_tab(self):
        layout = QVBoxLayout(self.logs_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Log Header Notice
        status_label = QLabel("⚡ Real-time diagnostic console (Showing recent history).", self.logs_tab)
        status_label.setStyleSheet("color: #00F3FF; font-weight: bold; font-size: 11px;")
        layout.addWidget(status_label)

        # Console Text Display
        self.log_text_edit = QTextEdit(self.logs_tab)
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setPlaceholderText("Real-time media session detection & lyric sync logs will appear here...")
        layout.addWidget(self.log_text_edit)

        # Bottom Bar: Auto-scroll, Clear, Copy
        tools_layout = QHBoxLayout()
        self.auto_scroll_check = QCheckBox("Auto-scroll", self.logs_tab)
        self.auto_scroll_check.setChecked(True)
        tools_layout.addWidget(self.auto_scroll_check)

        tools_layout.addStretch()

        btn_clear = QPushButton("Clear Logs", self.logs_tab)
        btn_clear.clicked.connect(self.log_text_edit.clear)
        tools_layout.addWidget(btn_clear)

        btn_copy = QPushButton("Copy to Clipboard", self.logs_tab)
        btn_copy.clicked.connect(self._copy_logs_to_clipboard)
        tools_layout.addWidget(btn_copy)

        layout.addLayout(tools_layout)

    def _load_log_history(self):
        """Populates the log viewer with all stored rolling history entries."""
        self.log_text_edit.clear()
        for timestamp, message in AppLogger.instance().history:
            self._append_log_entry(timestamp, message)

    def _append_log_entry(self, timestamp: str, message: str):
        color = "#00FF66"
        if "ERROR" in message or "Exception" in message or "No lyrics" in message or "failed" in message.lower() or "⚠️" in message:
            color = "#FF6B6B"
        elif "Selected" in message or "Track Changed" in message or "Match" in message or "🎯" in message:
            color = "#00F3FF"
        elif "LRCLib" in message or "🌐" in message:
            color = "#FFD700"
        elif "📌" in message or "NOTICE" in message:
            color = "#FFA500"

        html_entry = f'<span style="color: #777788;">[{timestamp}]</span> <span style="color: {color};">{message}</span>'
        self.log_text_edit.append(html_entry)

        if self.auto_scroll_check.isChecked():
            sb = self.log_text_edit.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _copy_logs_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.log_text_edit.toPlainText())

    def _disconnect_logger(self):
        """Safely disconnect logger signal."""
        if self._log_connected:
            try:
                AppLogger.instance().log_signal.disconnect(self._append_log_entry)
            except Exception:
                pass
            self._log_connected = False

        # Disconnect async source scanner if connected
        if hasattr(self, '_sources_connected'):
            parent_widget = self.parent()
            if parent_widget and hasattr(parent_widget, 'player') and parent_widget.player._worker_thread:
                try:
                    parent_widget.player._worker_thread.sources_scanned.disconnect(self._on_sources_scanned)
                except Exception:
                    pass
            del self._sources_connected

    def closeEvent(self, event):
        self._disconnect_logger()
        super().closeEvent(event)

    def reject(self):
        self._disconnect_logger()
        super().reject()

    def _load_current_values(self):
        s = self.working_settings
        self.font_combo.setCurrentFont(QFont(s.get("font_family", "Segoe UI")))
        self.size_spin.setValue(s.get("font_size", 24))
        self.bold_check.setChecked(s.get("font_bold", True))
        self.align_combo.setCurrentText(s.get("text_align", "Center"))
        self.show_info_check.setChecked(s.get("show_song_info", True))

        self._text_color = s.get("text_color", "#FFFFFF")
        self._bg_color = s.get("bg_color", "#000000")
        self._shadow_color = s.get("shadow_color", "#000000")

        self._update_color_button(self.btn_text_color, self._text_color)
        self._update_color_button(self.btn_bg_color, self._bg_color)
        self._update_color_button(self.btn_shadow_color, self._shadow_color)

        opacity = s.get("bg_opacity", 0)
        self.opacity_slider.setValue(opacity)
        self.opacity_label.setText(f"{opacity}%")

        self.link_opacity_check.setChecked(s.get("link_opacity_levels", True))

        active_op = s.get("active_line_opacity", 100)
        self.active_opacity_slider.setValue(active_op)
        self.active_opacity_label.setText(f"{active_op}%")

        ctx_op = s.get("context_line_opacity", 45)
        self.context_opacity_slider.setValue(ctx_op)
        self.context_opacity_label.setText(f"{ctx_op}%")

        self.active_outline_check.setChecked(s.get("active_text_outline", True))
        self.border_check.setChecked(s.get("border_enabled", False))
        self.adaptive_color_check.setChecked(s.get("adaptive_color", False))
        self.shadow_check.setChecked(s.get("shadow_enabled", True))
        self.shadow_blur_spin.setValue(s.get("shadow_blur", 8))

        self.top_check.setChecked(s.get("always_on_top", True))
        self.lock_check.setChecked(s.get("lock_position", False))
        self.context_lines_spin.setValue(s.get("context_lines", 2))
        self.auto_resize_check.setChecked(s.get("auto_resize_height", True))
        self.sync_offset_spin.setValue(s.get("sync_offset_ms", 0))

        # Animation settings
        self.anim_speed_slider.setValue(s.get("animation_speed_ms", 400))
        self.anim_speed_label.setText(f"{s.get('animation_speed_ms', 400)}ms")

        # Shortcut settings
        self.ks_toggle.setKeySequence(QKeySequence(s.get("shortcut_toggle_overlay", "Ctrl+H")))
        self.ks_refresh.setKeySequence(QKeySequence(s.get("shortcut_refresh", "Ctrl+R")))
        self.ks_nudge_minus.setKeySequence(QKeySequence(s.get("shortcut_nudge_minus", "Ctrl+Left")))
        self.ks_nudge_plus.setKeySequence(QKeySequence(s.get("shortcut_nudge_plus", "Ctrl+Right")))

        self._refresh_media_sources()

    def _update_color_button(self, button: QPushButton, hex_color: str):
        button.setStyleSheet(
            f"background-color: {hex_color}; "
            f"color: {'#000000' if QColor(hex_color).lightness() > 128 else '#FFFFFF'}; "
            f"font-weight: bold; border: 1px solid #666;"
        )
        button.setText(hex_color.upper())

    def _on_opacity_changed(self, val: int):
        self.opacity_label.setText(f"{val}%")
        self._on_control_changed()

    def _on_active_opacity_changed(self, val: int):
        self.active_opacity_label.setText(f"{val}%")
        if getattr(self, 'link_opacity_check', None) and self.link_opacity_check.isChecked():
            # Master link UX: scale context opacity proportionally with active opacity
            linked_ctx = max(0, min(100, int(val * 0.45)))
            self.context_opacity_slider.blockSignals(True)
            self.context_opacity_slider.setValue(linked_ctx)
            self.context_opacity_label.setText(f"{linked_ctx}%")
            self.context_opacity_slider.blockSignals(False)
        self._on_control_changed()

    def _on_context_opacity_changed(self, val: int):
        self.context_opacity_label.setText(f"{val}%")
        self._on_control_changed()

    def _on_control_changed(self):
        if getattr(self, '_is_initializing', False):
            return
        self._update_preview()

    def _apply_preset(self, name: str):
        if name in PRESETS:
            preset = PRESETS[name]
            if "text_color" in preset:
                self._text_color = preset["text_color"]
                self._update_color_button(self.btn_text_color, self._text_color)
            if "bg_color" in preset:
                self._bg_color = preset["bg_color"]
                self._update_color_button(self.btn_bg_color, self._bg_color)
            if "bg_opacity" in preset:
                self.opacity_slider.setValue(preset["bg_opacity"])
            if "border_enabled" in preset:
                self.border_check.setChecked(preset["border_enabled"])
            if "shadow_enabled" in preset:
                self.shadow_check.setChecked(preset["shadow_enabled"])
            if "shadow_color" in preset:
                self._shadow_color = preset["shadow_color"]
                self._update_color_button(self.btn_shadow_color, self._shadow_color)
            if "shadow_blur" in preset:
                self.shadow_blur_spin.setValue(preset["shadow_blur"])
            if "font_bold" in preset:
                self.bold_check.setChecked(preset["font_bold"])
            if "context_lines" in preset:
                self.context_lines_spin.setValue(preset["context_lines"])
            self._update_preview()

    def _update_preview(self):
        if getattr(self, '_is_initializing', False):
            return

        s = self._gather_settings()

        font = QFont(s["font_family"], max(12, int(s["font_size"] * 0.6)), QFont.Weight.Bold if s["font_bold"] else QFont.Weight.Normal)
        self.preview_lyric.setFont(font)

        align_str = s["text_align"]
        if align_str == "Left":
            self.preview_lyric.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        elif align_str == "Right":
            self.preview_lyric.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            self.preview_lyric.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.preview_sub.setVisible(s["show_song_info"])

        qbg = QColor(s["bg_color"])
        alpha = int((s["bg_opacity"] / 100.0) * 255)
        rgba_str = f"rgba({qbg.red()}, {qbg.green()}, {qbg.blue()}, {alpha / 255.0:.2f})"

        border_css = "border: 1px solid rgba(255, 255, 255, 0.15);" if s.get("border_enabled") else "border: none;"
        self.preview_container.setStyleSheet(f"background-color: {rgba_str}; border-radius: 8px; {border_css}")
        self.preview_lyric.setStyleSheet(f"color: {s['text_color']}; background: transparent;")

        if s["shadow_enabled"]:
            self.preview_shadow.setEnabled(True)
            self.preview_shadow.setColor(QColor(s["shadow_color"]))
            self.preview_shadow.setBlurRadius(s["shadow_blur"])
            self.preview_shadow.setOffset(2, 2)
        else:
            self.preview_shadow.setEnabled(False)

    def _pick_text_color(self):
        col = QColorDialog.getColor(QColor(self._text_color), self, "Select Text Color")
        if col.isValid():
            self._text_color = col.name()
            self._update_color_button(self.btn_text_color, self._text_color)
            self._update_preview()

    def _pick_bg_color(self):
        col = QColorDialog.getColor(QColor(self._bg_color), self, "Select Background Color")
        if col.isValid():
            self._bg_color = col.name()
            self._update_color_button(self.btn_bg_color, self._bg_color)
            self._update_preview()

    def _pick_shadow_color(self):
        col = QColorDialog.getColor(QColor(self._shadow_color), self, "Select Shadow Color")
        if col.isValid():
            self._shadow_color = col.name()
            self._update_color_button(self.btn_shadow_color, self._shadow_color)
            self._update_preview()

    def _gather_settings(self) -> Dict[str, Any]:
        selected_source_id = self.source_combo.currentData() if self.source_combo.count() > 0 else "Auto-Detect"
        return {
            "font_family": self.font_combo.currentFont().family(),
            "font_size": self.size_spin.value(),
            "font_bold": self.bold_check.isChecked(),
            "text_align": self.align_combo.currentText(),
            "show_song_info": self.show_info_check.isChecked(),
            "text_color": self._text_color,
            "bg_color": self._bg_color,
            "bg_opacity": self.opacity_slider.value(),
            "link_opacity_levels": self.link_opacity_check.isChecked(),
            "active_line_opacity": self.active_opacity_slider.value(),
            "context_line_opacity": self.context_opacity_slider.value(),
            "active_text_outline": self.active_outline_check.isChecked(),
            "border_enabled": self.border_check.isChecked(),
            "adaptive_color": self.adaptive_color_check.isChecked(),
            "shadow_enabled": self.shadow_check.isChecked(),
            "shadow_color": self._shadow_color,
            "shadow_blur": self.shadow_blur_spin.value(),
            "always_on_top": self.top_check.isChecked(),
            "lock_position": self.lock_check.isChecked(),
            "context_lines": self.context_lines_spin.value(),
            "auto_resize_height": self.auto_resize_check.isChecked(),
            "selected_media_source": selected_source_id or "Auto-Detect",
            "sync_offset_ms": self.sync_offset_spin.value(),
            "animation_speed_ms": self.anim_speed_slider.value(),
            "shortcut_toggle_overlay": self.ks_toggle.keySequence().toString(),
            "shortcut_refresh": self.ks_refresh.keySequence().toString(),
            "shortcut_nudge_minus": self.ks_nudge_minus.keySequence().toString(),
            "shortcut_nudge_plus": self.ks_nudge_plus.keySequence().toString(),
        }

    def _on_apply(self):
        new_settings = self._gather_settings()
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
