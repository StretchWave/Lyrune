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
from animation_engine import LyricsRenderer


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
        self._retired_workers: List[LyricsFetchWorker] = []  # keep refs until QThreads finish
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
        self.outer_layout.setContentsMargins(12, 10, 12, 10)
        self.outer_layout.setSpacing(4)

        # --- Custom Spotify-Style Lyrics Renderer ---
        self.renderer = LyricsRenderer(self)
        self.renderer.ideal_height_changed.connect(self._on_ideal_height_changed)
        self.outer_layout.addWidget(self.renderer, 1)

        # --- Song Info Sub-Label ---
        self.sub_label = QLabel("", self)
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 12px; font-style: italic; background: transparent;")
        self.sub_label.setVisible(False)
        self.outer_layout.addWidget(self.sub_label)

        self._last_active_index: int = -999

        # Size Grip
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("background: transparent;")
        self.outer_layout.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        # Configurable Keyboard Shortcuts
        self._shortcut_toggle = QShortcut(self)
        self._shortcut_toggle.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut_toggle.activated.connect(self._toggle_widget_visibility)

        self._sc_nudge_minus = QShortcut(self)
        self._sc_nudge_minus.activated.connect(lambda: self._nudge_sync_offset(-250))

        self._sc_nudge_plus = QShortcut(self)
        self._sc_nudge_plus.activated.connect(lambda: self._nudge_sync_offset(250))

        self._sc_refresh = QShortcut(self)
        self._sc_refresh.activated.connect(self._refresh_current_lyrics)

        self._sc_f5 = QShortcut(QKeySequence("F5"), self)
        self._sc_f5.activated.connect(self._refresh_current_lyrics)

        self._update_shortcuts_from_settings(self.settings_mgr.settings)

    def _update_shortcuts_from_settings(self, s: dict):
        """Updates QShortcut key sequences dynamically from settings dictionary."""
        key_toggle = s.get("shortcut_toggle_overlay", "Ctrl+H")
        key_refresh = s.get("shortcut_refresh", "Ctrl+R")
        key_minus = s.get("shortcut_nudge_minus", "Ctrl+Left")
        key_plus = s.get("shortcut_nudge_plus", "Ctrl+Right")

        if key_toggle:
            self._shortcut_toggle.setKey(QKeySequence(key_toggle))
        if key_refresh:
            self._sc_refresh.setKey(QKeySequence(key_refresh))
        if key_minus:
            self._sc_nudge_minus.setKey(QKeySequence(key_minus))
        if key_plus:
            self._sc_nudge_plus.setKey(QKeySequence(key_plus))

    def _nudge_sync_offset(self, delta_ms: int):
        """Nudges the lyric sync timing offset live by delta_ms."""
        current = self.settings_mgr.get("sync_offset_ms", 0)
        new_val = max(-5000, min(5000, current + delta_ms))
        self.settings_mgr.set("sync_offset_ms", new_val)
        log_event(f"⏱️ [Sync Nudge] Timing offset adjusted to {new_val}ms (delta: {delta_ms:+d}ms)", force=True)

    def _refresh_current_lyrics(self):
        """Forces a fresh online reload of lyrics for the current song, purging caches."""
        if not self.current_song_artist or not self.current_song_title:
            log_event("🔄 [Refresh Lyrics] No song currently playing to refresh.", force=True)
            return

        artist = self.current_song_artist
        title = self.current_song_title
        log_event(f"🔄 [Refresh Lyrics] Forcing fresh reload for '{artist} - {title}'...", force=True)

        self.lrclib.clear_track_cache(artist, title)
        self.current_track_id = None
        self._on_song_changed(artist, title)

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

        self.action_refresh = QAction("🔄 Refresh Lyrics", self)
        self.action_refresh.triggered.connect(self._refresh_current_lyrics)
        self.tray_menu.addAction(self.action_refresh)

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

    def _on_ideal_height_changed(self, ideal_height: int):
        """Adapt container window height to fit visible lyrics context lines."""
        if self.settings_mgr.get("auto_resize_height", True):
            extra = 28 if self.sub_label.isVisible() else 0
            target_h = max(70, ideal_height + extra + 20)
            if abs(self.height() - target_h) > 4:
                self.resize(self.width(), target_h)

    def _quit_application(self):
        """Safely stops worker thread, animations, and exits application."""
        pos = self.pos()
        self.settings_mgr.settings["window_x"] = pos.x()
        self.settings_mgr.settings["window_y"] = pos.y()
        self.settings_mgr.save_immediate()

        if hasattr(self, 'renderer'):
            self.renderer.stop_all()

        if hasattr(self, 'player'):
            self.player.stop_worker_thread()
        self._stop_lyrics_workers()
        QApplication.instance().quit()

    def _stop_lyrics_workers(self):
        """Bounded wait for in-flight lyrics fetches so their QThreads are not
        destroyed while still running when the app exits."""
        workers = []
        if getattr(self, '_lyrics_worker', None) and self._lyrics_worker.isRunning():
            workers.append(self._lyrics_worker)
        for w in getattr(self, '_retired_workers', []):
            if w.isRunning():
                workers.append(w)
        for w in workers:
            w.wait(3000)

    def closeEvent(self, event):
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
        was_visible = self.isVisible()
        current_flags = self.windowFlags()
        if always_top:
            self.setWindowFlags(current_flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(current_flags & ~Qt.WindowType.WindowStaysOnTopHint)
        if was_visible:
            self.show()

        if hasattr(self, 'action_top'):
            self.action_top.setChecked(always_top)

        locked = s.get("lock_position", False)
        if hasattr(self, 'action_lock'):
            self.action_lock.setChecked(locked)

        align_str = s.get("text_align", "Center")
        if align_str == "Left":
            align_flag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        elif align_str == "Right":
            align_flag = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        else:
            align_flag = Qt.AlignmentFlag.AlignCenter
        self.sub_label.setAlignment(align_flag)

        bg_color = s.get("bg_color", "#000000")
        bg_opacity = s.get("bg_opacity", 0)

        qbg = QColor(bg_color)
        alpha = int((bg_opacity / 100.0) * 255)
        rgba_str = f"rgba({qbg.red()}, {qbg.green()}, {qbg.blue()}, {alpha / 255.0:.2f})"

        border_enabled = s.get("border_enabled", False)
        self._base_bg_rgba = rgba_str
        self._border_enabled = border_enabled
        self._update_widget_border(rgba_str, border_enabled)

        show_info = s.get("show_song_info", True)
        self.sub_label.setVisible(show_info and bool(self.current_song_title))

        # Update custom lyrics renderer
        if hasattr(self, 'renderer'):
            self.renderer.update_style(s)

        # Update shortcuts dynamically
        self._update_shortcuts_from_settings(s)

    def _update_widget_border(self, bg_rgba: Optional[str] = None, border: bool = False):
        """Sets widget background with optional border."""
        if bg_rgba is None:
            bg_rgba = getattr(self, '_base_bg_rgba', 'transparent')
        border_str = "border: 1px solid rgba(255, 255, 255, 0.12);" if border else "border: none;"
        self.setStyleSheet(
            f"background-color: {bg_rgba};"
            f" border-radius: 10px;"
            f" {border_str}"
        )

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
            self.renderer.set_status("Waiting for Spotify...")
            if self.current_track_id is not None:
                self.current_track_id = None
                self.current_song_title = ""
                self.current_song_artist = ""
                self.parser.parse("")
                self._unsynced_lyrics = ""
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
            return

        sync_offset_ms = self.settings_mgr.get("sync_offset_ms", 0)
        adjusted_position = max(0.0, position + (sync_offset_ms / 1000.0))

        if self.parser.has_lyrics():
            active_idx = self.parser.get_current_index(adjusted_position)
            self.renderer.set_active_index(active_idx)
        elif self._unsynced_lyrics:
            pass  # Already set in _on_lyrics_fetched
        else:
            if self._pending_fetch_track == track_id:
                pass
            else:
                self.renderer.set_status("No synced lyrics found")

    def _on_song_changed(self, artist: str, title: str):
        """Triggers async lyrics fetch on song change with smooth fade transition."""
        self.parser.parse("")
        self._unsynced_lyrics = ""
        self._pending_fetch_track = f"{artist} - {title}"

        def _mid_transition():
            self.renderer.set_status("Loading lyrics...")

        self.renderer.fade_out_then(_mid_transition)

        if self._lyrics_worker and self._lyrics_worker.isRunning():
            old = self._lyrics_worker
            self._retired_workers.append(old)
            old.finished.connect(
                lambda w=old: self._retired_workers.remove(w)
                if w in self._retired_workers else None
            )
            if old.isFinished():
                self._retired_workers.remove(old)

        self._lyrics_worker = LyricsFetchWorker(self.lrclib, artist, title)
        self._lyrics_worker.lyrics_ready.connect(self._on_lyrics_fetched)
        self._lyrics_worker.start()

    def _on_lyrics_fetched(self, artist: str, title: str, synced_lrc: str, unsynced_lrc: str):
        """Callback when lyrics fetch completes (runs on main thread via Qt signal)."""
        track_id = f"{artist} - {title}"

        if track_id != self.current_track_id:
            log_event(f"[Lyrics Fetch] Discarding stale result for '{track_id}'")
            return

        self._pending_fetch_track = ""

        if synced_lrc:
            self.parser.parse(synced_lrc)
            if self.parser.has_lyrics():
                log_event(f"✅ [Lyrics Found] Found {self.parser.line_count} synced timestamped lines for '{artist} - {title}'", force=True)
                self.renderer.set_lines(self.parser.texts)
            else:
                log_event(f"⚠️ [Lyrics Status] Synced data fetched but 0 valid timestamped lines for '{artist} - {title}'", force=True)
                self.renderer.set_status("No synced lyrics found")
        elif unsynced_lrc:
            raw_lines = [line.strip() for line in unsynced_lrc.split('\n') if line.strip()]
            self._unsynced_lyrics = "\n".join(raw_lines[:15])
            log_event(f"⚠️ [Lyrics Status] Found plain text unsynced lyrics for '{artist} - {title}'", force=True)
            self.renderer.set_lines(raw_lines[:15])
        else:
            log_event(f"❌ [Lyrics Not Found] Could not find lyrics on LRCLIB for '{artist} - {title}'", force=True)
            self.renderer.set_status("No synced lyrics found")

    # --- Mouse Hover Events ---
    def enterEvent(self, event):
        self._is_hovered = True
        if getattr(self, '_border_enabled', False):
            self._update_widget_border(self._base_bg_rgba, border=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        if not getattr(self, '_border_enabled', False):
            self._update_widget_border(self._base_bg_rgba, border=False)
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
