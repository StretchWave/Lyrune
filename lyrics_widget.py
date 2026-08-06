import sys
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QPropertyAnimation, QEasingCurve,
    QParallelAnimationGroup, pyqtProperty
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QSizeGrip,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QMenu, QPushButton, QFrame, QSystemTrayIcon
)
from PyQt6.QtGui import (
    QFont, QColor, QAction, QActionGroup, QIcon, QPixmap, QPainter,
    QPen, QBrush, QShortcut, QKeySequence
)

from spotify_player import SpotifyPlayer
from lrclib_client import LRCLibClient, LyricsFetchWorker
from lrc_parser import LRCParser
from settings_manager import SettingsManager
from settings_dialog import SettingsDialog
from logger import log_event


def create_system_tray_icon() -> QIcon:
    """
    Generates a clean music note icon for the Windows System Tray.
    Uses actual drawing primitives instead of emoji (which renders as a blank square
    on many Windows systems because QPainter can't render emoji reliably).
    """
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Background circle
    painter.setBrush(QBrush(QColor("#007ACC")))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, 30, 30)

    # Draw a music note shape
    pen = QPen(QColor("#FFFFFF"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.setBrush(QBrush(QColor("#FFFFFF")))

    # Note head (filled ellipse)
    painter.drawEllipse(8, 18, 8, 6)
    # Stem
    painter.drawLine(16, 21, 16, 8)
    # Flag
    painter.drawLine(16, 8, 22, 12)
    painter.drawLine(16, 11, 22, 15)

    painter.end()
    return QIcon(pixmap)


class LyricsWidget(QWidget):
    """
    Desktop Lyrics Overlay Widget.

    Improvements over original:
      - Async lyrics fetching: HTTP requests run on a QThread, never blocking the GUI.
      - Loading/unsynced/synced display states with user feedback.
      - Debounced resize: batches dimension saves instead of per-pixel disk writes.
      - Hover only toggles the border CSS, doesn't re-apply all settings.
      - Saves/restores window position across restarts.
      - Proper drawn tray icon (no emoji rendering issues).
      - Ctrl+Shift+L keyboard shortcut to toggle visibility.
      - Paused-state logging throttled (no 20 Hz spam).
    """

    def __init__(self):
        super().__init__()

        # Core modules
        self.settings_mgr = SettingsManager()
        self.player = SpotifyPlayer()
        self.lrclib = LRCLibClient()
        self.parser = LRCParser()

        # Start dedicated background worker for Windows media polling
        self.player.start_worker_thread()

        # Track state
        self.current_track_id: Optional[str] = None
        self.current_song_title: str = ""
        self.current_song_artist: str = ""
        self.last_lyric_text: str = ""
        self.settings_dialog: Optional[SettingsDialog] = None
        self._is_hovered: bool = False
        self._is_dragging: bool = False
        self._drag_pos: QPoint = QPoint()

        # Async lyrics worker
        self._lyrics_worker: Optional[LyricsFetchWorker] = None
        self._pending_fetch_track: str = ""

        # Unsynced lyrics fallback
        self._unsynced_lyrics: str = ""

        # Resize debounce timer
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._save_window_dimensions)

        self._init_ui()
        self._init_system_tray()
        self._apply_settings(self.settings_mgr.settings)
        self._restore_window_position()
        self._init_timer()

    def _init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        w = self.settings_mgr.get("window_width", 800)
        h = self.settings_mgr.get("window_height", 160)
        self.resize(w, h)
        self.setMinimumSize(250, 70)

        # Outer Layout
        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.setContentsMargins(14, 12, 14, 12)
        self.outer_layout.setSpacing(8)

        # --- Lyrics Container Widget ---
        self.lyrics_container = QWidget(self)
        self.lyrics_container.setStyleSheet("background: transparent;")
        self.container_layout = QVBoxLayout(self.lyrics_container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(6)

        # --- Multi-Line Lyrics Layout ---
        self.prev_lyric_label = QLabel("", self.lyrics_container)
        self.prev_lyric_label.setWordWrap(True)
        self.container_layout.addWidget(self.prev_lyric_label)

        self.lyric_label = QLabel("Waiting for Spotify...", self.lyrics_container)
        self.lyric_label.setWordWrap(True)
        self.container_layout.addWidget(self.lyric_label)

        self.next_lyric_label = QLabel("", self.lyrics_container)
        self.next_lyric_label.setWordWrap(True)
        self.container_layout.addWidget(self.next_lyric_label)

        self.outer_layout.addWidget(self.lyrics_container)

        # --- Song Info Sub-Label ---
        self.sub_label = QLabel("", self)
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 12px; font-style: italic; background: transparent;")
        self.sub_label.setVisible(False)
        self.outer_layout.addWidget(self.sub_label)

        # Drop Shadow Effect for Active Line
        self.shadow_effect = QGraphicsDropShadowEffect(self.lyric_label)
        self.lyric_label.setGraphicsEffect(self.shadow_effect)

        # Smooth Opacity Transition Animation Effect on Container
        self._container_opacity = QGraphicsOpacityEffect(self.lyrics_container)
        self.lyrics_container.setGraphicsEffect(self._container_opacity)

        self._line_anim = QPropertyAnimation(self._container_opacity, b"opacity", self)
        self._line_anim.setDuration(240)
        self._line_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._last_active_index: int = -999

        # Size Grip
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("background: transparent;")
        self.outer_layout.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        # Keyboard shortcut: Ctrl+Shift+L to toggle visibility
        self._shortcut = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        self._shortcut.activated.connect(self._toggle_widget_visibility)

        # Keyboard shortcuts: Ctrl+Left (-250ms sync nudge) / Ctrl+Right (+250ms sync nudge)
        self._sc_nudge_minus = QShortcut(QKeySequence("Ctrl+Left"), self)
        self._sc_nudge_minus.activated.connect(lambda: self._nudge_sync_offset(-250))

        self._sc_nudge_plus = QShortcut(QKeySequence("Ctrl+Right"), self)
        self._sc_nudge_plus.activated.connect(lambda: self._nudge_sync_offset(250))

    def _nudge_sync_offset(self, delta_ms: int):
        """Nudges the lyric sync timing offset live by delta_ms."""
        current = self.settings_mgr.get("sync_offset_ms", 0)
        new_val = max(-5000, min(5000, current + delta_ms))
        self.settings_mgr.set("sync_offset_ms", new_val)
        log_event(f"⏱️ [Sync Nudge] Timing offset adjusted to {new_val}ms (delta: {delta_ms:+d}ms)", force=True)

    def _restore_window_position(self):
        """Restores saved window position, or centers on screen if off-screen/first launch."""
        x = self.settings_mgr.get("window_x", -1)
        y = self.settings_mgr.get("window_y", -1)
        screen_geo = QApplication.primaryScreen().availableGeometry()

        if x >= 0 and y >= 0 and screen_geo.contains(QPoint(x, y)):
            self.move(x, y)
        else:
            # Default to bottom-center of primary screen
            cx = (screen_geo.width() - self.width()) // 2
            cy = screen_geo.height() - self.height() - 100
            self.move(cx, cy)
            self.settings_mgr.set("window_x", cx)
            self.settings_mgr.set("window_y", cy)

    def _init_system_tray(self):
        """Initializes the Windows System Tray Icon & Context Menu."""
        self.tray_icon = QSystemTrayIcon(create_system_tray_icon(), self)
        self.tray_icon.setToolTip("LyricScript Desktop Widget")

        # System Tray Menu
        self.tray_menu = QMenu()

        self.action_settings = QAction("⚙️ Settings...", self)
        self.action_settings.triggered.connect(self._open_settings)
        self.tray_menu.addAction(self.action_settings)

        self.tray_menu.addSeparator()

        # Target Media Source Submenu
        self.source_menu = QMenu("🎵 Target Media Source", self.tray_menu)
        self.tray_menu.addMenu(self.source_menu)

        self.tray_menu.addSeparator()

        self.action_visible = QAction("👁️ Hide Lyrics Overlay", self)
        self.action_visible.triggered.connect(self._toggle_widget_visibility)
        self.tray_menu.addAction(self.action_visible)

        self.action_top = QAction("📌 Always on Top", self)
        self.action_top.setCheckable(True)
        self.action_top.setChecked(self.settings_mgr.get("always_on_top", True))
        self.action_top.triggered.connect(self._toggle_always_on_top)
        self.tray_menu.addAction(self.action_top)

        self.action_lock = QAction("🔒 Lock Position", self)
        self.action_lock.setCheckable(True)
        self.action_lock.setChecked(self.settings_mgr.get("lock_position", False))
        self.action_lock.triggered.connect(self._toggle_lock_position)
        self.tray_menu.addAction(self.action_lock)

        self.tray_menu.addSeparator()

        self.action_exit = QAction("❌ Exit", self)
        self.action_exit.triggered.connect(self._quit_application)
        self.tray_menu.addAction(self.action_exit)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        self.tray_icon.show()

    def _update_source_menu(self):
        """Populates the Target Media Source sub-menu with available sessions."""
        self.source_menu.clear()

        # Request async scan (results come via signal)
        # For the context menu we need immediate results, so use sync fallback
        sources = self.player.get_available_media_sources()

        # Also request an async scan for more complete results next time
        self.player.request_source_scan()

        selected_id = self.settings_mgr.get("selected_media_source", "Auto-Detect")

        group = QActionGroup(self)
        for item in sources:
            action = QAction(item['name'], self.source_menu)
            action.setCheckable(True)
            if item['id'] == selected_id or item['name'] == selected_id:
                action.setChecked(True)

            action.triggered.connect(lambda _, src_id=item['id']: self._set_target_source_from_tray(src_id))
            group.addAction(action)
            self.source_menu.addAction(action)

    def _set_target_source_from_tray(self, source_id: str):
        self.settings_mgr.set("selected_media_source", source_id)
        self.player.set_target_source(source_id)

    def _quit_application(self):
        """Safely stops worker thread and exits application."""
        # Save window position immediately before exit
        pos = self.pos()
        self.settings_mgr.settings["window_x"] = pos.x()
        self.settings_mgr.settings["window_y"] = pos.y()
        self.settings_mgr.save_immediate()

        if hasattr(self, 'player'):
            self.player.stop_worker_thread()
        QApplication.instance().quit()

    def closeEvent(self, event):
        # Save position on close
        pos = self.pos()
        self.settings_mgr.settings["window_x"] = pos.x()
        self.settings_mgr.settings["window_y"] = pos.y()
        self.settings_mgr.save_immediate()

        if hasattr(self, 'player'):
            self.player.stop_worker_thread()
        super().closeEvent(event)

    def _apply_settings(self, s: Dict[str, Any]):
        """Applies configuration settings to the widget UI."""
        target_src = s.get("selected_media_source", "Auto-Detect")
        self.player.set_target_source(target_src)

        always_top = s.get("always_on_top", True)
        current_flags = self.windowFlags()
        if always_top:
            self.setWindowFlags(current_flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(current_flags & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()

        if hasattr(self, 'action_top'):
            self.action_top.setChecked(always_top)

        locked = s.get("lock_position", False)
        if hasattr(self, 'action_lock'):
            self.action_lock.setChecked(locked)

        family = s.get("font_family", "Segoe UI")
        size = s.get("font_size", 24)
        bold = s.get("font_bold", True)

        font_active = QFont(family, size, QFont.Weight.Bold if bold else QFont.Weight.Normal)
        font_sub = QFont(family, max(10, int(size * 0.65)), QFont.Weight.Normal)

        self.lyric_label.setFont(font_active)
        self.prev_lyric_label.setFont(font_sub)
        self.next_lyric_label.setFont(font_sub)

        align_str = s.get("text_align", "Center")
        if align_str == "Left":
            align_flag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        elif align_str == "Right":
            align_flag = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        else:
            align_flag = Qt.AlignmentFlag.AlignCenter

        self.prev_lyric_label.setAlignment(align_flag)
        self.lyric_label.setAlignment(align_flag)
        self.next_lyric_label.setAlignment(align_flag)
        self.sub_label.setAlignment(align_flag)

        text_color = s.get("text_color", "#FFFFFF")
        bg_color = s.get("bg_color", "#000000")
        bg_opacity = s.get("bg_opacity", 0)

        qbg = QColor(bg_color)
        alpha = int((bg_opacity / 100.0) * 255)
        rgba_str = f"rgba({qbg.red()}, {qbg.green()}, {qbg.blue()}, {alpha / 255.0:.2f})"

        # Convert text color to 45% opacity for previous/next context lines
        qcol = QColor(text_color)
        sub_color_str = f"rgba({qcol.red()}, {qcol.green()}, {qcol.blue()}, 0.45)"

        self._update_widget_border(rgba_str)
        self.lyric_label.setStyleSheet(f"color: {text_color}; background: transparent; border: none; padding: 6px 12px;")
        self.prev_lyric_label.setStyleSheet(f"color: {sub_color_str}; background: transparent; border: none; padding: 4px 12px;")
        self.next_lyric_label.setStyleSheet(f"color: {sub_color_str}; background: transparent; border: none; padding: 4px 12px;")

        show_info = s.get("show_song_info", True)
        self.sub_label.setVisible(show_info and bool(self.current_song_title))

        shadow_enabled = s.get("shadow_enabled", True)
        if shadow_enabled:
            self.shadow_effect.setEnabled(True)
            self.shadow_effect.setColor(QColor(s.get("shadow_color", "#000000")))
            self.shadow_effect.setBlurRadius(s.get("shadow_blur", 8))
            self.shadow_effect.setOffset(2, 2)
        else:
            self.shadow_effect.setEnabled(False)

        # Cache the base style
        self._base_bg_rgba = rgba_str

    def _update_widget_border(self, bg_rgba: Optional[str] = None):
        """Sets clean widget background without any hover popup border."""
        if bg_rgba is None:
            bg_rgba = getattr(self, '_base_bg_rgba', 'transparent')
        self.setStyleSheet(f"background-color: {bg_rgba}; border-radius: 10px; border: none;")

    def _init_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_lyrics_loop)
        self.timer.start(50)

    def _update_lyrics_loop(self):
        """Main 50ms polling loop. Reads cached playback info and updates lyrics display."""
        if self._is_dragging:
            return

        info = self.player.get_playback_info()

        if not info['is_running'] or not info['title']:
            self._set_lyric_display("Waiting for Spotify...")
            if self.current_track_id is not None:
                # Track was lost
                self.current_track_id = None
                self.current_song_title = ""
                self.current_song_artist = ""
                self.sub_label.setVisible(False)
            return

        artist = info['artist'] or ""
        title = info['title'] or ""
        status = info['status']
        position = info['position']

        track_id = f"{artist} - {title}"

        if track_id != self.current_track_id:
            self.current_track_id = track_id
            self.current_song_title = title
            self.current_song_artist = artist

            show_info = self.settings_mgr.get("show_song_info", True)
            self.sub_label.setText(f"🎵 {artist} - {title}")
            self.sub_label.setVisible(show_info)

            log_event(f"🎵 [Song Identified] Identified next song: '{artist} - {title}'", force=True)
            self._on_song_changed(artist, title)

        if status == "Paused":
            # No repeated logging for paused state — throttled in logger
            return

        above_cnt = self.settings_mgr.get("context_lines_above", 1)
        below_cnt = self.settings_mgr.get("context_lines_below", 1)
        multi_enabled = self.settings_mgr.get("multi_line_enabled", True)

        if not multi_enabled:
            above_cnt = 0
            below_cnt = 0

        sync_offset_ms = self.settings_mgr.get("sync_offset_ms", 0)
        adjusted_position = max(0.0, position + (sync_offset_ms / 1000.0))

        if self.parser.has_lyrics():
            prev_lines, curr_txt, next_lines, active_idx = self.parser.get_lyric_window(adjusted_position, above_cnt, below_cnt)
            if curr_txt:
                self._set_window_lyric_display(prev_lines, curr_txt, next_lines, active_idx)
            else:
                self._set_window_lyric_display([], "♪", next_lines, -1)
        elif self._unsynced_lyrics:
            # Show unsynced lyrics as static text
            self._set_window_lyric_display([], self._unsynced_lyrics, [], -1)
        else:
            if self._pending_fetch_track == track_id:
                self._set_window_lyric_display([], "Loading lyrics...", [], -1)
            else:
                self._set_window_lyric_display([], "No synced lyrics found", [], -1)

    def _on_song_changed(self, artist: str, title: str):
        """
        Triggers async lyrics fetch on song change.
        Non-blocking: runs HTTP requests on a background QThread.
        """
        self.parser.parse("")  # Clear old lyrics
        self._unsynced_lyrics = ""
        self._pending_fetch_track = f"{artist} - {title}"
        self._set_window_lyric_display([], "Loading lyrics...", [], -1)

        # Cancel any existing fetch
        if self._lyrics_worker and self._lyrics_worker.isRunning():
            self._lyrics_worker.requestInterruption()
            self._lyrics_worker.wait(1000)

        # Start new async fetch
        self._lyrics_worker = LyricsFetchWorker(self.lrclib, artist, title)
        self._lyrics_worker.lyrics_ready.connect(self._on_lyrics_fetched)
        self._lyrics_worker.start()

    def _on_lyrics_fetched(self, artist: str, title: str, synced_lrc: str, unsynced_lrc: str):
        """
        Callback when lyrics fetch completes (runs on main thread via Qt signal).
        Handles synced → unsynced → none fallback chain.
        """
        track_id = f"{artist} - {title}"

        # Only apply if this is still the current song
        if track_id != self.current_track_id:
            log_event(f"[Lyrics Fetch] Discarding stale result for '{track_id}'")
            return

        self._pending_fetch_track = ""

        if synced_lrc:
            self.parser.parse(synced_lrc)
            if self.parser.has_lyrics():
                log_event(f"✅ [Lyrics Found] Found {self.parser.line_count} synced timestamped lines for '{artist} - {title}'", force=True)
            else:
                log_event(f"⚠️ [Lyrics Status] Synced data fetched but 0 valid timestamped lines for '{artist} - {title}'", force=True)
                self._set_window_lyric_display([], "No synced lyrics found", [], -1)
        elif unsynced_lrc:
            # Show first ~200 chars of unsynced lyrics as static text
            self._unsynced_lyrics = unsynced_lrc[:200].strip()
            if '\n' in self._unsynced_lyrics:
                # Show just the first 2-3 lines
                lines = self._unsynced_lyrics.split('\n')[:3]
                self._unsynced_lyrics = '\n'.join(lines)
            log_event(f"⚠️ [Lyrics Status] Found plain text unsynced lyrics for '{artist} - {title}'", force=True)
            self._set_window_lyric_display([], self._unsynced_lyrics, [], -1)
        else:
            log_event(f"❌ [Lyrics Not Found] Could not find lyrics on LRCLIB for '{artist} - {title}'", force=True)
            self._set_window_lyric_display([], "No synced lyrics found", [], -1)

    def _set_window_lyric_display(self, prev_lines: list, current_text: str, next_lines: list, active_index: int):
        """
        Updates multi-line lyric display with configurable above/below context lines.
        Triggers smooth QPropertyAnimation OutCubic vertical morphing slide transition on line changes.
        """
        prev_text = "\n".join(prev_lines) if prev_lines else ""
        next_text = "\n".join(next_lines) if next_lines else ""

        # Check if active line index changed
        if active_index != self._last_active_index or self.last_lyric_text != current_text:
            self._last_active_index = active_index
            self.last_lyric_text = current_text

            # Update label texts
            self.prev_lyric_label.setText(prev_text)
            self.prev_lyric_label.setVisible(bool(prev_text))

            self.lyric_label.setText(current_text)

            self.next_lyric_label.setText(next_text)
            self.next_lyric_label.setVisible(bool(next_text))

            # Trigger smooth container opacity transition animation
            if hasattr(self, '_line_anim'):
                self._line_anim.stop()
                self._line_anim.setStartValue(0.35)
                self._line_anim.setEndValue(1.0)
                self._line_anim.start()

    def _set_3line_lyric_display(self, prev_text: str, current_text: str, next_text: str, active_index: int):
        """Legacy compatibility wrapper."""
        self._set_window_lyric_display([prev_text] if prev_text else [], current_text, [next_text] if next_text else [], active_index)

    def _set_lyric_display(self, text: str):
        """Legacy compatibility wrapper."""
        self._set_3line_lyric_display("", text, "", -1)

    # --- Mouse Hover Events ---
    def enterEvent(self, event):
        self._is_hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        super().leaveEvent(event)

    # --- System Tray Actions ---
    def _on_tray_icon_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._toggle_widget_visibility()

    def _toggle_widget_visibility(self):
        if self.isVisible():
            self.hide()
            self.action_visible.setText("👁️ Show Lyrics Overlay")
        else:
            self.show()
            self.action_visible.setText("👁️ Hide Lyrics Overlay")

    def _open_settings(self):
        if self.settings_dialog is None or not self.settings_dialog.isVisible():
            self.settings_dialog = SettingsDialog(self.settings_mgr, self)
            self.settings_dialog.settings_changed.connect(self._apply_settings)
            self.settings_dialog.show()
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()

    def _toggle_always_on_top(self, checked: bool):
        self.settings_mgr.set("always_on_top", checked)
        self._apply_settings(self.settings_mgr.settings)

    def _toggle_lock_position(self, checked: bool):
        self.settings_mgr.set("lock_position", checked)
        self._apply_settings(self.settings_mgr.settings)

    # --- Context Menu ---
    def contextMenuEvent(self, event):
        self._update_source_menu()
        self.tray_menu.exec(event.globalPos())

    # --- Fast Non-Blocking Window Dragging ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.settings_mgr.get("lock_position", False):
                self._is_dragging = True
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if self._is_dragging and event.buttons() == Qt.MouseButton.LeftButton:
            if not self.settings_mgr.get("lock_position", False):
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging:
                self._is_dragging = False
                # Save position after drag
                pos = self.pos()
                self.settings_mgr.set("window_x", pos.x())
                self.settings_mgr.set("window_y", pos.y())
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        """Debounced resize: saves dimensions after 500ms of no resize activity."""
        super().resizeEvent(event)
        # Restart the debounce timer on each resize event
        self._resize_timer.start(500)

    def _save_window_dimensions(self):
        """Actually save dimensions to disk (called by debounce timer)."""
        self.settings_mgr.set("window_width", self.width())
        self.settings_mgr.set("window_height", self.height())
