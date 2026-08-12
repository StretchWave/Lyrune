from dataclasses import dataclass
from typing import Optional, List
from PyQt6.QtGui import QIcon, QColor, QPixmap, QPainter, QBrush, QPen, QFont, QKeySequence
from PyQt6.QtCore import QSize, Qt, pyqtSignal, QRectF, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtWidgets import (
    QWidget, QCheckBox, QSlider, QHBoxLayout, QLabel, QPushButton, QColorDialog,
    QKeySequenceEdit, QVBoxLayout, QFrame
)
import qtawesome as qta


@dataclass(frozen=True)
class Palette:
    bg: str = "#0F1015"               # Deep charcoal slate
    surface: str = "#16181F"          # Sidebar & Cards
    surface_elevated: str = "#1F222B" # Inputs & Selectors
    border: str = "#262933"           # Subtle 1px borders
    border_subtle: str = "#1E2028"
    text_primary: str = "#F0F1F5"
    text_secondary: str = "#8A8D9B"
    text_disabled: str = "#4E515E"
    accent: str = "#1DB954"           # Spotify Soft Neon Green
    accent_hover: str = "#1ED760"
    accent_pressed: str = "#169C46"
    accent_muted: str = "rgba(29, 185, 84, 0.15)"
    success: str = "#1DB954"
    warning: str = "#F2A93B"
    error: str = "#E5484D"
    info: str = "#38BDF8"


PALETTE = Palette()

ICONS = {
    # Tabs & Sections
    "typography": "ph.text-t",
    "appearance": "ph.palette",
    "behavior": "ph.sliders-horizontal",
    "animations": "ph.wave-sine",
    "shortcuts": "ph.keyboard",
    "logs": "ph.file-text",

    # Actions
    "save": "ph.floppy-disk",
    "check": "ph.check",
    "reset": "ph.arrow-counter-clockwise",
    "refresh": "ph.arrows-clockwise",
    "search": "ph.magnifying-glass",
    "preview": "ph.play",
    "clear": "ph.trash",
    "copy": "ph.copy",

    # Diagnostics / Status
    "info": "ph.info",
    "warning": "ph.warning",
    "error": "ph.x-circle",
    "success": "ph.check-circle",
    "notice": "ph.terminal-window",
    "target": "ph.crosshair-simple",

    # Controls & Menus
    "settings": "ph.gear-six",
    "eye": "ph.eye",
    "eye_off": "ph.eye-slash",
    "pin": "ph.push-pin",
    "pin_fill": "ph.push-pin-fill",
    "lock": "ph.lock-simple",
    "lock_open": "ph.lock-simple-open",
    "exit": "ph.sign-out",
    "close": "ph.x",
    "minimize": "ph.minus",
    "maximize": "ph.square",

    # Sources
    "browser": "ph.globe",
    "music": "ph.music-notes",
    "auto_detect": "ph.crosshair-simple",

    # Features
    "link": "ph.link",
    "contour": "ph.bounding-box",
    "adaptive": "ph.sliders-horizontal",
    "hint": "ph.lightbulb",
}


def get_icon(
    name_or_key: str,
    color: Optional[str] = None,
    color_active: Optional[str] = None,
    scale_factor: float = 1.0
) -> QIcon:
    """
    Returns a crisp qtawesome vector QIcon.
    If name_or_key is a key in ICONS dict, resolves it to the Phosphor glyph name.
    """
    icon_name = ICONS.get(name_or_key, name_or_key)
    base_color = color or PALETTE.text_secondary
    kwargs = {"color": base_color, "scale_factor": scale_factor}
    if color_active:
        kwargs["color_active"] = color_active
    try:
        return qta.icon(icon_name, **kwargs)
    except Exception:
        return QIcon()


def create_swatch_icon(hex_color: str, size: int = 16) -> QIcon:
    """Generates a small solid circle swatch QIcon for theme preset menus."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(hex_color))
    painter.setPen(QColor(PALETTE.border))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


# ==============================================================================
# Modern Custom UI Components (De-AI Native Desktop Aesthetic)
# ==============================================================================

class ToggleSwitch(QWidget):
    """Modern animated pill toggle switch replacing standard checkboxes."""
    toggled = pyqtSignal(bool)

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._text = text
        self._checked = False
        self._thumb_position = 0.0

        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Ensure label text is not clipped
        if text:
            from PyQt6.QtGui import QFontMetrics
            fm = QFontMetrics(QFont("Segoe UI", 9))
            self.setMinimumWidth(36 + 16 + fm.horizontalAdvance(text))

        self._anim = QPropertyAnimation(self, b"thumb_position", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    @pyqtProperty(float)
    def thumb_position(self) -> float:
        return self._thumb_position

    @thumb_position.setter
    def thumb_position(self, pos: float):
        self._thumb_position = pos
        self.update()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self._anim.stop()
            self._anim.setEndValue(1.0 if checked else 0.0)
            self._anim.start()
            self.toggled.emit(checked)
            self.update()

    def setChecked_silent(self, checked: bool):
        """Sets checked state without emitting toggled signal."""
        self._checked = checked
        self._thumb_position = 1.0 if checked else 0.0
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_w, track_h = 36, 18
        track_x, track_y = 0, (self.height() - track_h) // 2

        # Draw track
        bg_col = QColor(PALETTE.accent) if self._checked else QColor(PALETTE.surface_elevated)
        border_col = QColor(PALETTE.accent_hover) if self._checked else QColor(PALETTE.border)
        painter.setBrush(QBrush(bg_col))
        painter.setPen(QPen(border_col, 1))
        painter.drawRoundedRect(QRectF(track_x, track_y, track_w, track_h), track_h / 2, track_h / 2)

        # Draw thumb
        thumb_r = 6
        thumb_margin = 3
        thumb_min_x = track_x + thumb_margin + thumb_r
        thumb_max_x = track_x + track_w - thumb_margin - thumb_r
        thumb_x = thumb_min_x + self._thumb_position * (thumb_max_x - thumb_min_x)
        thumb_y = track_y + track_h / 2

        thumb_col = QColor("#0F1015") if self._checked else QColor(PALETTE.text_primary)
        painter.setBrush(QBrush(thumb_col))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(thumb_x - thumb_r, thumb_y - thumb_r, thumb_r * 2, thumb_r * 2))

        # Draw label text
        if self._text:
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor(PALETTE.text_primary))
            painter.drawText(track_w + 10, self.height() // 2 + 4, self._text)

        painter.end()


class ValueSlider(QWidget):
    """Custom slider with an attached numerical value bubble/chip."""
    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        min_val: int = 0,
        max_val: int = 100,
        default_val: int = 50,
        suffix: str = "",
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._suffix = suffix

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(min_val, max_val)
        self.slider.setValue(default_val)
        layout.addWidget(self.slider, 1)

        self.bubble = QLabel(f"{default_val}{suffix}", self)
        self.bubble.setFixedWidth(54)
        self.bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bubble.setStyleSheet(
            f"background-color: {PALETTE.surface_elevated};"
            f" color: {PALETTE.accent};"
            f" font-weight: 600;"
            f" font-size: 9pt;"
            f" border: 1px solid {PALETTE.border};"
            f" border-radius: 4px;"
            f" padding: 2px 4px;"
        )
        layout.addWidget(self.bubble)

        self.slider.valueChanged.connect(self._on_value_changed)

    def _on_value_changed(self, val: int):
        self.bubble.setText(f"{val}{self._suffix}")
        self.valueChanged.emit(val)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, val: int):
        self.slider.setValue(val)
        self.bubble.setText(f"{val}{self._suffix}")

    def setRange(self, min_val: int, max_val: int):
        self.slider.setRange(min_val, max_val)


class ColorSwatchButton(QPushButton):
    """Visual color swatch widget opening native QColorDialog."""
    colorChanged = pyqtSignal(str)

    def __init__(self, color_hex: str = "#FFFFFF", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color_hex = color_hex
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self._update_style()
        self.clicked.connect(self._pick_color)

    def color(self) -> str:
        return self._color_hex

    def setColor(self, hex_code: str):
        self._color_hex = hex_code
        self._update_style()

    def _update_style(self):
        self.setIcon(create_swatch_icon(self._color_hex, 16))
        self.setText(f" {self._color_hex.upper()}")
        self.setStyleSheet(
            f"background-color: {PALETTE.surface_elevated};"
            f" color: {PALETTE.text_primary};"
            f" border: 1px solid {PALETTE.border};"
            f" border-radius: 4px;"
            f" padding: 4px 10px;"
            f" font-family: monospace;"
            f" font-weight: 600;"
        )

    def _pick_color(self):
        col = QColorDialog.getColor(QColor(self._color_hex), self, "Select Color")
        if col.isValid():
            self.setColor(col.name())
            self.colorChanged.emit(self._color_hex)


class KeycapWidget(QWidget):
    """Physical keyboard keycap visual recorder widget."""
    keySequenceChanged = pyqtSignal(QKeySequence)

    def __init__(self, key_str: str = "Ctrl+H", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._key_sequence = QKeySequence(key_str)
        self._is_recording = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.container = QWidget(self)
        self.caps_layout = QHBoxLayout(self.container)
        self.caps_layout.setContentsMargins(0, 0, 0, 0)
        self.caps_layout.setSpacing(4)
        layout.addWidget(self.container)

        self.btn_record = QPushButton("Change", self)
        self.btn_record.setFixedWidth(70)
        self.btn_record.clicked.connect(self._toggle_recording)
        layout.addWidget(self.btn_record)

        self._render_keycaps()

    def keySequence(self) -> QKeySequence:
        return self._key_sequence

    def setKeySequence(self, seq: QKeySequence):
        self._key_sequence = seq
        self._render_keycaps()

    def _toggle_recording(self):
        self._is_recording = not self._is_recording
        if self._is_recording:
            self.btn_record.setText("Press key...")
            self.btn_record.setStyleSheet(f"color: {PALETTE.accent}; border-color: {PALETTE.accent};")
            self.setFocus()
        else:
            self.btn_record.setText("Change")
            self.btn_record.setStyleSheet("")

    def keyPressEvent(self, event):
        if not self._is_recording:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return

        modifiers = int(event.modifiers())
        new_seq = QKeySequence(modifiers | key)
        self._key_sequence = new_seq
        self._is_recording = False
        self.btn_record.setText("Change")
        self.btn_record.setStyleSheet("")
        self._render_keycaps()
        self.keySequenceChanged.emit(self._key_sequence)

    def _render_keycaps(self):
        # Clear existing keycap pills
        while self.caps_layout.count():
            item = self.caps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        seq_str = self._key_sequence.toString()
        if not seq_str:
            lbl = QLabel("None", self)
            lbl.setStyleSheet(f"color: {PALETTE.text_disabled}; font-style: italic;")
            self.caps_layout.addWidget(lbl)
            return

        tokens = seq_str.split("+")
        for token in tokens:
            cap = QLabel(token.strip(), self)
            cap.setStyleSheet(
                f"background: {PALETTE.surface_elevated};"
                f" color: {PALETTE.accent};"
                f" font-weight: 700;"
                f" font-family: monospace;"
                f" border: 1px solid {PALETTE.border};"
                f" border-bottom: 2px solid {PALETTE.border};"
                f" border-radius: 4px;"
                f" padding: 3px 8px;"
            )
            self.caps_layout.addWidget(cap)


DARK_THEME_STYLESHEET = f"""
QDialog, QWidget#settingsRoot {{
    background-color: {PALETTE.bg};
    color: {PALETTE.text_primary};
    font-family: 'Segoe UI Variable', 'Segoe UI', 'Inter', sans-serif;
    font-size: 10pt;
}}

/* Custom Title Bar */
QWidget#customTitleBar {{
    background-color: {PALETTE.surface};
    border-bottom: 1px solid {PALETTE.border};
}}

/* Scroll Area */
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}

/* Sidebar Navigation */
QListWidget#sidebarNav {{
    background-color: {PALETTE.surface};
    border-right: 1px solid {PALETTE.border};
    border-top: none;
    border-bottom: none;
    border-left: none;
    outline: none;
    padding: 8px 4px;
}}
QListWidget#sidebarNav::item {{
    color: {PALETTE.text_secondary};
    height: 38px;
    border-radius: 4px;
    margin: 2px 4px;
    padding-left: 10px;
    font-weight: 500;
}}
QListWidget#sidebarNav::item:hover {{
    background-color: {PALETTE.surface_elevated};
    color: {PALETTE.text_primary};
}}
QListWidget#sidebarNav::item:selected {{
    background-color: {PALETTE.surface_elevated};
    color: {PALETTE.accent};
    font-weight: 600;
    border-left: 3px solid {PALETTE.accent};
}}

/* Group Box & Cards */
QGroupBox {{
    background-color: {PALETTE.surface};
    border: 1px solid {PALETTE.border};
    border-radius: 6px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
    color: {PALETTE.text_primary};
    font-size: 9.5pt;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {PALETTE.text_secondary};
    background-color: {PALETTE.bg};
}}

/* Labels & Inputs */
QLabel {{
    color: {PALETTE.text_primary};
    font-size: 9.5pt;
}}

QSpinBox, QComboBox, QFontComboBox {{
    background-color: {PALETTE.surface_elevated};
    color: {PALETTE.text_primary};
    border: 1px solid {PALETTE.border};
    border-radius: 4px;
    padding: 5px 8px;
    min-height: 22px;
    selection-background-color: {PALETTE.accent_muted};
    selection-color: {PALETTE.accent};
}}
QSpinBox:hover, QComboBox:hover, QFontComboBox:hover {{
    border-color: {PALETTE.text_secondary};
}}
QSpinBox:focus, QComboBox:focus, QFontComboBox:focus {{
    border-color: {PALETTE.accent};
}}
QComboBox QAbstractItemView {{
    background-color: {PALETTE.surface};
    color: {PALETTE.text_primary};
    selection-background-color: {PALETTE.accent_muted};
    selection-color: {PALETTE.accent};
    border: 1px solid {PALETTE.border};
    border-radius: 4px;
    padding: 4px;
    outline: none;
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 4px;
    background: {PALETTE.border};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {PALETTE.accent};
    border: 2px solid {PALETTE.surface};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {PALETTE.accent_hover};
}}

/* Buttons */
QPushButton {{
    background-color: {PALETTE.surface_elevated};
    color: {PALETTE.text_primary};
    border: 1px solid {PALETTE.border};
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 9.5pt;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {PALETTE.surface};
    border-color: {PALETTE.accent};
    color: {PALETTE.text_primary};
}}
QPushButton:pressed {{
    background-color: {PALETTE.bg};
}}

QPushButton#btn_primary {{
    background-color: {PALETTE.accent};
    border: 1px solid {PALETTE.accent};
    color: {PALETTE.bg};
    font-weight: 600;
}}
QPushButton#btn_primary:hover {{
    background-color: {PALETTE.accent_hover};
    border-color: {PALETTE.accent_hover};
}}
QPushButton#btn_primary:pressed {{
    background-color: {PALETTE.accent_pressed};
}}

QPushButton#btn_ghost {{
    background: transparent;
    border: none;
    color: {PALETTE.text_secondary};
}}
QPushButton#btn_ghost:hover {{
    color: {PALETTE.error};
    text-decoration: underline;
}}

/* Log Console Text Edit */
QTextEdit#logConsole {{
    background-color: {PALETTE.surface};
    color: {PALETTE.text_primary};
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
    font-size: 9pt;
    border: 1px solid {PALETTE.border};
    border-radius: 4px;
    padding: 8px;
}}
"""


MENU_STYLESHEET = f"""
QMenu {{
    background-color: {PALETTE.surface};
    color: {PALETTE.text_primary};
    border: 1px solid {PALETTE.border};
    border-radius: 6px;
    padding: 6px;
    font-family: 'Segoe UI Variable', 'Segoe UI', 'Inter', sans-serif;
    font-size: 9.5pt;
}}
QMenu::item {{
    padding: 6px 24px 6px 10px;
    border-radius: 4px;
    color: {PALETTE.text_primary};
}}
QMenu::item:selected {{
    background-color: {PALETTE.accent_muted};
    color: {PALETTE.accent};
}}
QMenu::item:disabled {{
    color: {PALETTE.text_disabled};
}}
QMenu::icon {{
    padding-left: 6px;
}}
QMenu::separator {{
    height: 1px;
    background-color: {PALETTE.border};
    margin: 5px 6px;
}}
"""
