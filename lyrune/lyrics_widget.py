import re
import sys
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import (
    Qt, QTimer, QPoint
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QSizeGrip,
    QMenu, QSystemTrayIcon
)
from PyQt6.QtGui import (
    QColor, QFont, QAction, QActionGroup, QPainter,
    QPen, QShortcut, QKeySequence
)

from lyrune.spotify_player import SpotifyPlayer
from lyrune.lrclib_client import LRCLibClient, LyricsFetchWorker
from lyrune.lrc_parser import LRCParser
from lyrune.settings_manager import SettingsManager
from lyrune.settings_dialog import SettingsDialog
from lyrune.logger import log_event
from lyrune.animation_engine import LyricsRenderer
from lyrune.ui_theme import get_icon, get_app_icon, MENU_STYLESHEET
from lyrune.visualizer import VisualizerManager
from lyrune.wallpaper import WallpaperManager
from lyrune.window_utils import (
    calculate_edge_snap,
    constrain_to_work_area,
    apply_native_overlay_styles,
    reassert_window_topmost,
    is_window_below_foreground,
    is_window_below_any_topmost,
    sync_hyprland_window
)


class LyricsWidget(QWidget):
    """
    Desktop Lyrics Overlay Widget.

    Improvements over original:
      - Async lyrics fetching: HTTP requests run on a QThread, never blocking the GUI.
      - Loading/unsynced/synced display states with user feedback.
      - Debounced resize: batches dimension saves instead of per-pixel disk writes.
      - Hover border is painter-drawn (no stylesheet swap) so hovering never touches
        the layout or native window frame — the overlay can't shift under the cursor.
      - Auto-resize-height is deferred while the pointer is over the overlay so the
        window surface stays put while interacting (stable right-click hit-testing).
      - Saves/restores window position across restarts.
      - Standard Windows borderless overlay support with Z-guard & focus preservation.
    """

    def __init__(self, settings_manager: Optional[SettingsManager] = None, parent=None):
        super().__init__(parent)
        self.settings_mgr = settings_manager or SettingsManager()
        self.player = SpotifyPlayer()
        self.lrclib = LRCLibClient()
        self.parser = LRCParser()

        # Standalone Visualizer Subsystem (independent floating window & pipeline)
        self.visualizer_manager = VisualizerManager(self.settings_mgr, self.player)

        # Desktop Wallpaper Subsystem (WorkerW desktop hosted rendering)
        self.wallpaper_manager = WallpaperManager(self.settings_mgr, parent=self)
        if self.settings_mgr.get("wallpaper_enabled", False):
            self.wallpaper_manager.start()

        # Set app-wide icon (taskbar + all windows)
        app = QApplication.instance()
        if app:
            app.setWindowIcon(get_app_icon())

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
        self._pending_target_h: Optional[int] = None  # deferred auto-resize while hovering/dragging
        self._manually_hidden: bool = False

        # Async lyrics worker
        self._lyrics_worker: Optional[LyricsFetchWorker] = None
        self._retired_workers: List[LyricsFetchWorker] = []  # keep refs until QThreads finish
        self._pending_fetch_track: str = ""

        # Unsynced lyrics fallback
        self._unsynced_lyrics: str = ""

        # Lyrics retry state
        self._lyrics_retry_count: int = 0
        self._lyrics_retry_max: int = 3
        self._lyrics_fetch_failed: bool = False  # True when LRCLIB returned empty
        self._lyrics_retry_timer = QTimer(self)
        self._lyrics_retry_timer.setInterval(2000)
        self._lyrics_retry_timer.timeout.connect(self._on_lyrics_retry_tick)

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
        self.setWindowTitle("Lyrune Lyrics Overlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
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

        self._shortcut_vis_toggle = QShortcut(self)
        self._shortcut_vis_toggle.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut_vis_toggle.activated.connect(self.visualizer_manager.toggle_visibility)

        self._shortcut_game_toggle = QShortcut(self)
        self._shortcut_game_toggle.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut_game_toggle.activated.connect(self._toggle_game_overlay_from_shortcut)

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
        key_vis_toggle = s.get("shortcut_toggle_visualizer", "Ctrl+Shift+V")
        key_game_toggle = s.get("shortcut_toggle_game_overlay", "Ctrl+Shift+G")
        key_refresh = s.get("shortcut_refresh", "Ctrl+R")
        key_minus = s.get("shortcut_nudge_minus", "Ctrl+Left")
        key_plus = s.get("shortcut_nudge_plus", "Ctrl+Right")

        if key_toggle:
            self._shortcut_toggle.setKey(QKeySequence(key_toggle))
        if key_vis_toggle:
            self._shortcut_vis_toggle.setKey(QKeySequence(key_vis_toggle))
        if key_game_toggle:
            self._shortcut_game_toggle.setKey(QKeySequence(key_game_toggle))
        if key_refresh:
            self._sc_refresh.setKey(QKeySequence(key_refresh))
        if key_minus:
            self._sc_nudge_minus.setKey(QKeySequence(key_minus))
        if key_plus:
            self._sc_nudge_plus.setKey(QKeySequence(key_plus))

    def _nudge_sync_offset(self, delta_ms: int):
        """Nudges the lyric sync timing offset live by delta_ms for the active track."""
        track_key = f"{self.current_song_artist} - {self.current_song_title}" if self.current_song_title else "global"
        offsets = dict(self.settings_mgr.get("track_sync_offsets", {}))
        current = offsets.get(track_key, self.settings_mgr.get("sync_offset_ms", 0))
        new_val = max(-5000, min(5000, current + delta_ms))

        if track_key != "global":
            offsets[track_key] = new_val
            self.settings_mgr.set("track_sync_offsets", offsets)
            log_event(f"⏱️ [Track Sync Nudge] Timing offset for '{track_key}' set to {new_val}ms (delta: {delta_ms:+d}ms)", force=True)
        else:
            self.settings_mgr.set("sync_offset_ms", new_val)
            log_event(f"⏱️ [Global Sync Nudge] Timing offset adjusted to {new_val}ms", force=True)

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
        self.tray_icon = QSystemTrayIcon(get_app_icon(), self)
        self.tray_icon.setToolTip("Lyrune Desktop Widget")

        # System Tray Menu
        self.tray_menu = QMenu(self)
        self.tray_menu.setStyleSheet(MENU_STYLESHEET)

        self.action_refresh = QAction(get_icon("refresh"), "Refresh Lyrics", self)
        self.action_refresh.triggered.connect(self._refresh_current_lyrics)
        self.tray_menu.addAction(self.action_refresh)

        self.action_settings = QAction(get_icon("settings"), "Settings...", self)
        self.action_settings.triggered.connect(self._open_settings)
        self.tray_menu.addAction(self.action_settings)

        self.tray_menu.addSeparator()

        # Target Media Source Submenu
        self.source_menu = QMenu("Target Media Source", self.tray_menu)
        self.source_menu.setIcon(get_icon("target"))
        self.source_menu.setStyleSheet(MENU_STYLESHEET)
        self.tray_menu.addMenu(self.source_menu)

        self.tray_menu.addSeparator()

        self.action_visible = QAction(get_icon("eye_off"), "Hide Lyrics Overlay", self)
        self.action_visible.triggered.connect(self._toggle_widget_visibility)
        self.tray_menu.addAction(self.action_visible)

        # Layer Mode Submenu (Top, Normal, Bottom)
        self.layer_menu = QMenu("Layer Mode", self.tray_menu)
        self.layer_menu.setIcon(get_icon("pin"))
        self.layer_menu.setStyleSheet(MENU_STYLESHEET)

        curr_layer = self.settings_mgr.get("window_layer_mode", "Top" if self.settings_mgr.get("always_on_top", True) else "Normal")
        self.action_layer_top = QAction("Always on Top (Foreground)", self.layer_menu)
        self.action_layer_top.setCheckable(True)
        self.action_layer_top.setChecked(curr_layer == "Top")
        self.action_layer_top.triggered.connect(lambda: self._set_layer_mode_from_tray("Top"))
        self.layer_menu.addAction(self.action_layer_top)

        self.action_layer_normal = QAction("Normal Window", self.layer_menu)
        self.action_layer_normal.setCheckable(True)
        self.action_layer_normal.setChecked(curr_layer == "Normal")
        self.action_layer_normal.triggered.connect(lambda: self._set_layer_mode_from_tray("Normal"))
        self.layer_menu.addAction(self.action_layer_normal)

        self.action_layer_bottom = QAction("Background / Desktop (Below All)", self.layer_menu)
        self.action_layer_bottom.setCheckable(True)
        self.action_layer_bottom.setChecked(curr_layer == "Bottom")
        self.action_layer_bottom.triggered.connect(lambda: self._set_layer_mode_from_tray("Bottom"))
        self.layer_menu.addAction(self.action_layer_bottom)

        self.tray_menu.addMenu(self.layer_menu)

        lock_icon = get_icon("lock" if self.settings_mgr.get("lock_position", False) else "lock_open")
        self.action_lock = QAction(lock_icon, "Lock Position", self)
        self.action_lock.setCheckable(True)
        self.action_lock.setChecked(self.settings_mgr.get("lock_position", False))
        self.action_lock.triggered.connect(self._toggle_lock_position)
        self.tray_menu.addAction(self.action_lock)

        self.action_click_through = QAction(get_icon("hint"), "Click-Through Mode", self)
        self.action_click_through.setCheckable(True)
        self.action_click_through.setChecked(self.settings_mgr.get("click_through", False))
        self.action_click_through.triggered.connect(self._toggle_click_through)
        self.tray_menu.addAction(self.action_click_through)

        self.tray_menu.addSeparator()

        # Standalone Visualizer Submenu
        self.vis_menu = QMenu("Visualizer", self.tray_menu)
        self.vis_menu.setIcon(get_icon("visualizer"))
        self.vis_menu.setStyleSheet(MENU_STYLESHEET)

        self.action_vis_enable = QAction("Enable Visualizer", self)
        self.action_vis_enable.setCheckable(True)
        self.action_vis_enable.setChecked(self.settings_mgr.get("visualizer_enabled", True))
        self.action_vis_enable.triggered.connect(self._toggle_visualizer_enabled_from_tray)
        self.vis_menu.addAction(self.action_vis_enable)

        self.vis_menu.addSeparator()

        # Overlay Mode Submenu
        self.vis_mode_menu = QMenu("Overlay Mode", self.vis_menu)
        self.vis_mode_menu.setStyleSheet(MENU_STYLESHEET)

        current_mode = self.settings_mgr.get("visualizer_overlay_mode", "Normal")
        self.action_vis_mode_normal = QAction("Normal", self.vis_mode_menu)
        self.action_vis_mode_normal.setCheckable(True)
        self.action_vis_mode_normal.setChecked(current_mode == "Normal")
        self.action_vis_mode_normal.triggered.connect(lambda: self._set_visualizer_mode_from_tray("Normal"))
        self.vis_mode_menu.addAction(self.action_vis_mode_normal)

        self.action_vis_mode_game = QAction("Game Overlay", self.vis_mode_menu)
        self.action_vis_mode_game.setCheckable(True)
        self.action_vis_mode_game.setChecked(current_mode == "Game Overlay")
        self.action_vis_mode_game.triggered.connect(lambda: self._set_visualizer_mode_from_tray("Game Overlay"))
        self.vis_mode_menu.addAction(self.action_vis_mode_game)

        self.vis_menu.addMenu(self.vis_mode_menu)

        self.vis_menu.addSeparator()

        self.vis_pos_menu = QMenu("Position", self.vis_menu)
        self.vis_pos_menu.setStyleSheet(MENU_STYLESHEET)
        for preset in ["Free", "Top", "Bottom", "Left", "Right"]:
            act = QAction(preset, self.vis_pos_menu)
            act.triggered.connect(lambda _, p=preset: self.visualizer_manager.set_preset_position(p))
            self.vis_pos_menu.addAction(act)
        self.vis_menu.addMenu(self.vis_pos_menu)

        self.vis_menu.addSeparator()

        # Visualizer Layer Mode Submenu
        self.vis_layer_menu = QMenu("Layer Mode", self.vis_menu)
        self.vis_layer_menu.setStyleSheet(MENU_STYLESHEET)

        curr_vis_layer = self.settings_mgr.get("visualizer_window_layer_mode", "Top" if self.settings_mgr.get("visualizer_always_on_top", True) else "Normal")
        self.action_vis_layer_top = QAction("Always on Top (Foreground)", self.vis_layer_menu)
        self.action_vis_layer_top.setCheckable(True)
        self.action_vis_layer_top.setChecked(curr_vis_layer == "Top")
        self.action_vis_layer_top.triggered.connect(lambda: self._set_visualizer_layer_mode_from_tray("Top"))
        self.vis_layer_menu.addAction(self.action_vis_layer_top)

        self.action_vis_layer_normal = QAction("Normal Window", self.vis_layer_menu)
        self.action_vis_layer_normal.setCheckable(True)
        self.action_vis_layer_normal.setChecked(curr_vis_layer == "Normal")
        self.action_vis_layer_normal.triggered.connect(lambda: self._set_visualizer_layer_mode_from_tray("Normal"))
        self.vis_layer_menu.addAction(self.action_vis_layer_normal)

        self.action_vis_layer_bottom = QAction("Background / Desktop (Below All)", self.vis_layer_menu)
        self.action_vis_layer_bottom.setCheckable(True)
        self.action_vis_layer_bottom.setChecked(curr_vis_layer == "Bottom")
        self.action_vis_layer_bottom.triggered.connect(lambda: self._set_visualizer_layer_mode_from_tray("Bottom"))
        self.vis_layer_menu.addAction(self.action_vis_layer_bottom)

        self.vis_menu.addMenu(self.vis_layer_menu)

        self.action_vis_click_through = QAction("Click-Through Mode", self)
        self.action_vis_click_through.setCheckable(True)
        self.action_vis_click_through.setChecked(self.settings_mgr.get("visualizer_click_through", False))
        self.action_vis_click_through.triggered.connect(self._toggle_visualizer_click_through_from_tray)
        self.vis_menu.addAction(self.action_vis_click_through)

        self.tray_menu.addMenu(self.vis_menu)

        # Desktop Wallpaper Submenu
        self.wallpaper_menu = QMenu("Desktop Wallpaper", self.tray_menu)
        self.wallpaper_menu.setIcon(get_icon("wallpaper"))
        self.wallpaper_menu.setStyleSheet(MENU_STYLESHEET)

        self.action_wallpaper_enable = QAction("Enable Wallpaper Engine", self)
        self.action_wallpaper_enable.setCheckable(True)
        self.action_wallpaper_enable.setChecked(self.settings_mgr.get("wallpaper_enabled", False))
        self.action_wallpaper_enable.triggered.connect(self._toggle_wallpaper_enabled_from_tray)
        self.wallpaper_menu.addAction(self.action_wallpaper_enable)

        self.action_wallpaper_settings = QAction("Configure Wallpaper...", self)
        self.action_wallpaper_settings.triggered.connect(self._open_wallpaper_settings)
        self.wallpaper_menu.addAction(self.action_wallpaper_settings)

        self.tray_menu.addMenu(self.wallpaper_menu)

        self.tray_menu.addSeparator()

        self.action_exit = QAction(get_icon("exit"), "Exit", self)
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
            raw_name = item['name']
            clean_name = re.sub(r'^[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\s]+', '', raw_name).strip()

            if "Spotify" in clean_name or "Spotify" in item['id']:
                icon = get_icon("music")
            elif any(b in clean_name for b in ["Browser", "Chrome", "Brave", "Edge", "Firefox", "Opera"]):
                icon = get_icon("browser")
            else:
                icon = get_icon("auto_detect")

            action = QAction(icon, clean_name, self.source_menu)
            action.setCheckable(True)
            if item['id'] == selected_id or item['name'] == selected_id or clean_name == selected_id:
                action.setChecked(True)

            action.triggered.connect(lambda _, src_id=item['id']: self._set_target_source_from_tray(src_id))
            group.addAction(action)
            self.source_menu.addAction(action)

    def _set_target_source_from_tray(self, source_id: str):
        self.settings_mgr.set("selected_media_source", source_id)
        self.player.set_target_source(source_id)

    def _on_ideal_height_changed(self, ideal_height: int):
        """Adapt container window height to fit visible lyrics context lines.

        While the pointer is over the overlay (or the user is dragging it), the
        resize is deferred so the window surface never moves under the cursor —
        otherwise the auto-fit would shrink/grow the window mid-hover, making the
        overlay appear to jump and breaking right-click (Settings) hit-testing.
        """
        if not self.settings_mgr.get("auto_resize_height", True):
            return
        extra = 28 if self.sub_label.isVisible() else 0
        target_h = max(70, ideal_height + extra + 20)
        if self._is_hovered or self._is_dragging:
            self._pending_target_h = target_h
            return
        self._pending_target_h = None
        if abs(self.height() - target_h) > 4:
            self.resize(self.width(), target_h)

    def _apply_pending_resize(self):
        """Apply a deferred auto-resize once the user is no longer interacting."""
        target_h = getattr(self, '_pending_target_h', None)
        if target_h is None or self._is_hovered or self._is_dragging:
            return
        self._pending_target_h = None
        if abs(self.height() - target_h) > 4:
            self.resize(self.width(), target_h)

    def _toggle_visualizer_enabled_from_tray(self, checked: bool):
        self.settings_mgr.set("visualizer_enabled", checked)
        self.visualizer_manager.apply_settings(self.settings_mgr.settings)

    def _toggle_visualizer_top_from_tray(self, checked: bool):
        self.settings_mgr.set("visualizer_always_on_top", checked)
        self.visualizer_manager.apply_settings(self.settings_mgr.settings)

    def _toggle_visualizer_click_through_from_tray(self, checked: bool):
        self.settings_mgr.set("visualizer_click_through", checked)
        self.visualizer_manager.apply_settings(self.settings_mgr.settings)

    def _quit_application(self):
        """Safely stops worker thread, animations, and exits application."""
        pos = self.pos()
        self.settings_mgr.settings["window_x"] = pos.x()
        self.settings_mgr.settings["window_y"] = pos.y()
        self.settings_mgr.save_immediate()

        if hasattr(self, 'visualizer_manager'):
            self.visualizer_manager.shutdown()

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

        if hasattr(self, 'visualizer_manager'):
            self.visualizer_manager.shutdown()

        if hasattr(self, 'player'):
            self.player.stop_worker_thread()
        super().closeEvent(event)

    def _apply_settings(self, s: Dict[str, Any]):
        """Applies configuration settings to the widget UI."""
        target_src = s.get("selected_media_source", "Auto-Detect")
        self.player.set_target_source(target_src)

        layer_mode = s.get("window_layer_mode")
        if not layer_mode:
            layer_mode = "Top" if s.get("always_on_top", True) else "Normal"

        always_top = (layer_mode == "Top")
        always_bottom = (layer_mode == "Bottom")
        click_through = s.get("click_through", False)
        was_visible = self.isVisible()
        current_flags = self.windowFlags()

        # Clear layer flags
        current_flags &= ~Qt.WindowType.WindowStaysOnTopHint
        current_flags &= ~Qt.WindowType.WindowStaysOnBottomHint

        if always_top:
            current_flags |= Qt.WindowType.WindowStaysOnTopHint
        elif always_bottom:
            current_flags |= Qt.WindowType.WindowStaysOnBottomHint

        if click_through:
            current_flags |= Qt.WindowType.WindowTransparentForInput
        else:
            current_flags &= ~Qt.WindowType.WindowTransparentForInput

        self.setWindowFlags(current_flags)
        if was_visible:
            self.show()
            if always_top:
                self.raise_()
            elif always_bottom:
                self.lower()

        # Windows Screen Capture Exclusion (SetWindowDisplayAffinity)
        exclude_capture = s.get("exclude_from_capture", False)
        if sys.platform == "win32" and self.winId():
            try:
                import ctypes
                hwnd = int(self.winId())
                # WDA_EXCLUDEFROMCAPTURE = 0x00000011 (Windows 10 2004+ / Windows 11)
                # WDA_MONITOR = 0x00000001 (Windows 7/8/early 10)
                # WDA_NONE = 0x0
                affinity = 0x00000011 if exclude_capture else 0x0
                res = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, affinity)
                if not res and exclude_capture:
                    # Fallback to WDA_MONITOR for older Windows builds
                    ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000001)

                # Standard Windows Extended Styles & Z-Order
                apply_native_overlay_styles(
                    hwnd,
                    layer_mode=layer_mode,
                    always_on_top=always_top,
                    click_through=click_through,
                    no_activate=True
                )
            except Exception as e:
                log_event(f"[Lyrics Native Overlay Error] {e}")

        # Linux / Hyprland Compositor Sync (Enforces float, pin, geometry)
        QTimer.singleShot(80, lambda: sync_hyprland_window("Lyrune Lyrics Overlay", layer_mode=layer_mode, target_pos=self.pos(), target_size=self.size()))

        if hasattr(self, 'action_layer_top'):
            self.action_layer_top.setChecked(layer_mode == "Top")
            self.action_layer_normal.setChecked(layer_mode == "Normal")
            self.action_layer_bottom.setChecked(layer_mode == "Bottom")

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

        font_family = s.get("font_family", "Segoe UI")
        font_size = s.get("font_size", 24)
        font_bold = s.get("font_bold", True)

        weight = QFont.Weight.Bold if font_bold else QFont.Weight.Normal
        self.main_font = QFont(font_family, font_size, weight)

        text_color = s.get("text_color", "#FFFFFF")
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

        # Update Dimensions & Position if changed
        w = s.get("window_width")
        h = s.get("window_height")
        if w and h and (self.width() != w or self.height() != h):
            self.resize(w, h)

        x = s.get("window_x")
        y = s.get("window_y")
        if x is not None and y is not None and x >= 0 and y >= 0:
            if self.pos().x() != x or self.pos().y() != y:
                self.move(x, y)

        # Update shortcuts dynamically
        self._update_shortcuts_from_settings(s)

        # Update visualizer subsystem
        if hasattr(self, 'visualizer_manager'):
            self.visualizer_manager.apply_settings(s)
            if hasattr(self, 'action_vis_enable'):
                self.action_vis_enable.setChecked(s.get("visualizer_enabled", False))
            if hasattr(self, 'action_vis_top'):
                self.action_vis_top.setChecked(s.get("visualizer_always_on_top", True))
            vis_layer = s.get("visualizer_window_layer_mode", "Top" if s.get("visualizer_always_on_top", True) else "Normal")
            if hasattr(self, 'action_vis_layer_top'):
                self.action_vis_layer_top.setChecked(vis_layer == "Top")
                self.action_vis_layer_normal.setChecked(vis_layer == "Normal")
                self.action_vis_layer_bottom.setChecked(vis_layer == "Bottom")
            if hasattr(self, 'action_vis_click_through'):
                self.action_vis_click_through.setChecked(s.get("visualizer_click_through", False))

        # Update wallpaper subsystem
        if hasattr(self, 'wallpaper_manager'):
            self.wallpaper_manager.apply_config(s)

    def _update_widget_border(self, bg_rgba: Optional[str] = None, border: bool = False):
        """Sets the translucent background via a *constant* stylesheet."""
        if bg_rgba is None:
            bg_rgba = getattr(self, '_base_bg_rgba', 'transparent')
        self._border_visible = bool(border)
        self.setStyleSheet(
            f"background-color: {bg_rgba};"
            f" border-radius: 10px;"
        )
        self.update()

    def paintEvent(self, event):        # noqa: N802
        """Draws the hover/settings border as pure painting (no geometry effects)."""
        super().paintEvent(event)
        if getattr(self, '_border_visible', False):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(255, 255, 255, 31), 1))  # rgba(255,255,255,0.12)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
            painter.end()

    def _init_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_lyrics_loop)
        self.timer.start(50)

    def _update_lyrics_loop(self):
        """Main 50ms polling loop. Reads cached playback info and updates lyrics display."""
        if self._is_dragging:
            return

        info = self.player.get_playback_info()

        # Propagate live playback state to standalone visualizer
        if hasattr(self, 'visualizer_manager'):
            self.visualizer_manager.update_playback_state(info)

        # Propagate live playback state to wallpaper subsystem
        if hasattr(self, 'wallpaper_manager'):
            self.wallpaper_manager.update_media_state(info)

        layer_mode = self.settings_mgr.get("window_layer_mode", "Top" if self.settings_mgr.get("always_on_top", True) else "Normal")

        # Windows Z-guard: maintain topmost Z-order above fullscreen games without stealing focus
        if sys.platform == "win32" and self.isVisible() and layer_mode == "Top":
            hwnd = int(self.winId()) if self.winId() else 0
            vis_hwnd = int(self.visualizer_manager.window.winId()) if hasattr(self, 'visualizer_manager') and self.visualizer_manager.window.winId() else 0
            if hwnd and (is_window_below_any_topmost(hwnd, excluded_hwnds=[vis_hwnd]) or is_window_below_foreground(hwnd)):
                reassert_window_topmost(hwnd)
        elif self.isVisible() and layer_mode == "Bottom":
            # Ensure background overlay remains at bottom
            self.lower()

        if not info['is_running'] or not info['title']:
            self.renderer.set_status("Waiting for Spotify...")
            if self.settings_mgr.get("auto_hide_on_pause", False) and self.isVisible():
                self.hide()
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
            self.sub_label.setText(f"{artist} - {title}")
            self.sub_label.setVisible(show_info)

            log_event(f"🎵 [Song Identified] Identified next song: '{artist} - {title}'", force=True)
            self._on_song_changed(artist, title)

        if status == "Paused":
            if self.settings_mgr.get("auto_hide_on_pause", False) and self.isVisible():
                self.hide()
        else:
            # If we were auto-hidden and playback resumed, show again (unless user manually hid via shortcut/tray)
            if self.settings_mgr.get("auto_hide_on_pause", False) and not self.isVisible() and not getattr(self, '_manually_hidden', False):
                self.show()

        # Check per-track offset first, fallback to global offset
        offsets = self.settings_mgr.get("track_sync_offsets", {})
        sync_offset_ms = offsets.get(track_id, self.settings_mgr.get("sync_offset_ms", 0))
        adjusted_position = max(0.0, position + (sync_offset_ms / 1000.0))

        if self.parser.has_lyrics():
            if not self.renderer._lines:
                self.renderer.set_lines(self.parser.texts)
            active_idx = self.parser.get_current_index(adjusted_position)
            self.renderer.set_active_index(active_idx)
        elif self._unsynced_lyrics:
            if not self.renderer._lines:
                self.renderer.set_lines([line for line in self._unsynced_lyrics.split('\n') if line])

    def _on_song_changed(self, artist: str, title: str):
        """Triggers async lyrics fetch on song change with smooth fade transition."""
        self.parser.parse("")
        self._unsynced_lyrics = ""
        self._pending_fetch_track = f"{artist} - {title}"

        # Reset retry state for the new song
        self._lyrics_retry_count = 0
        self._lyrics_fetch_failed = False
        self._lyrics_retry_timer.stop()

        self.renderer.set_status("Loading lyrics...")
        self._start_lyrics_fetch(artist, title)

    def _start_lyrics_fetch(self, artist: str, title: str):
        """Launches a background lyrics fetch worker for the given track."""
        if self._lyrics_worker and self._lyrics_worker.isRunning():
            old = self._lyrics_worker
            self._retired_workers.append(old)
            old.finished.connect(
                lambda w=old: self._retired_workers.remove(w)
                if w in self._retired_workers else None
            )
            try:
                if old.isFinished() and old in self._retired_workers:
                    self._retired_workers.remove(old)
            except ValueError:
                pass

        self._lyrics_worker = LyricsFetchWorker(self.lrclib, artist, title)
        self._lyrics_worker.lyrics_ready.connect(self._on_lyrics_fetched)
        self._lyrics_worker.start()

    def _on_lyrics_retry_tick(self):
        """Retry timer callback: re-fetch lyrics if still loading or previously failed."""
        if not self.current_song_artist or not self.current_song_title:
            self._lyrics_retry_timer.stop()
            return

        track_id = f"{self.current_song_artist} - {self.current_song_title}"

        # Check if lyrics were already loaded successfully
        if self.parser.has_lyrics() or self._unsynced_lyrics:
            self._lyrics_retry_timer.stop()
            return

        self._lyrics_retry_count += 1
        log_event(f"🔄 [Lyrics Retry] Attempt {self._lyrics_retry_count}/{self._lyrics_retry_max} for '{track_id}'", force=True)

        if self._lyrics_retry_count >= self._lyrics_retry_max:
            self._lyrics_retry_timer.stop()
            # Show contextual error message
            if self._lyrics_fetch_failed:
                self.renderer.set_status("Lyrics not found")
                log_event(f"❌ [Lyrics Not Found] Lyrics not found for '{track_id}' after {self._lyrics_retry_max} attempts", force=True)
            else:
                self.renderer.set_status("Lyrics aren't being loaded")
                log_event(f"❌ [Lyrics Load Failure] Lyrics aren't being loaded for '{track_id}' after {self._lyrics_retry_max} attempts", force=True)
            return

        # Re-fetch: clear cache for this track and try again
        self.lrclib.clear_track_cache(self.current_song_artist, self.current_song_title)
        self.renderer.set_status("Retrying lyrics...")
        self._start_lyrics_fetch(self.current_song_artist, self.current_song_title)

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
                self._lyrics_retry_timer.stop()
                return
            else:
                log_event(f"⚠️ [Lyrics Status] Synced data fetched but 0 valid timestamped lines for '{artist} - {title}'", force=True)
        elif unsynced_lrc:
            raw_lines = [line.strip() for line in unsynced_lrc.split('\n') if line.strip()]
            self._unsynced_lyrics = "\n".join(raw_lines[:15])
            log_event(f"⚠️ [Lyrics Status] Found plain text unsynced lyrics for '{artist} - {title}'", force=True)
            self.renderer.set_lines(raw_lines[:15])
            self._lyrics_retry_timer.stop()
            return
        else:
            log_event(f"❌ [Lyrics Not Found] Could not find lyrics on LRCLIB for '{artist} - {title}'", force=True)
            self._lyrics_fetch_failed = True

        # Lyrics not found or empty — start retry timer if not already retrying
        if self._lyrics_retry_count < self._lyrics_retry_max and not self._lyrics_retry_timer.isActive():
            self.renderer.set_status("Loading lyrics...")
            self._lyrics_retry_timer.start()
        elif self._lyrics_retry_count >= self._lyrics_retry_max:
            # Already exhausted retries
            if self._lyrics_fetch_failed:
                self.renderer.set_status("Lyrics not found")
            else:
                self.renderer.set_status("Lyrics aren't being loaded")

    # --- Mouse Hover Events ---
    def enterEvent(self, event):
        self._is_hovered = True
        self._update_widget_border(self._base_bg_rgba, border=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self._update_widget_border(self._base_bg_rgba, border=getattr(self, '_border_enabled', False))
        self._apply_pending_resize()
        super().leaveEvent(event)

    # --- System Tray Actions ---
    def _on_tray_icon_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._toggle_widget_visibility()

    def _toggle_widget_visibility(self):
        if self.isVisible():
            self._manually_hidden = True
            self.hide()
            self.action_visible.setText("Show Lyrics Overlay")
            self.action_visible.setIcon(get_icon("eye"))
        else:
            self._manually_hidden = False
            self.show()
            self.action_visible.setText("Hide Lyrics Overlay")
            self.action_visible.setIcon(get_icon("eye_off"))

    def _open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self.settings_mgr, player=self.player, parent=None)
            self.settings_dialog.settings_changed.connect(self._apply_settings)
            self.settings_dialog.show()
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
        else:
            self.settings_dialog._refresh_media_sources()
            if self.settings_dialog.isMinimized():
                self.settings_dialog.setWindowState(Qt.WindowState.WindowNoState)
            self.settings_dialog.show()
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()

    def _set_layer_mode_from_tray(self, mode: str):
        self.settings_mgr.set("window_layer_mode", mode)
        self.settings_mgr.set("always_on_top", mode == "Top")
        self._apply_settings(self.settings_mgr.settings)

    def _toggle_always_on_top(self, checked: bool):
        mode = "Top" if checked else "Normal"
        self._set_layer_mode_from_tray(mode)

    def _toggle_lock_position(self, checked: bool):
        self.settings_mgr.set("lock_position", checked)
        self.action_lock.setIcon(get_icon("lock" if checked else "lock_open"))
        self._apply_settings(self.settings_mgr.settings)

    def _toggle_click_through(self, checked: bool):
        self.settings_mgr.set("click_through", checked)
        self._apply_settings(self.settings_mgr.settings)

    # --- Standalone Visualizer Tray & Shortcut Handlers ---
    def _toggle_visualizer_enabled_from_tray(self, checked: bool):
        self.settings_mgr.set("visualizer_enabled", checked)
        self.visualizer_manager.apply_settings(self.settings_mgr.settings)

    def _set_visualizer_mode_from_tray(self, mode: str):
        self.visualizer_manager.set_overlay_mode(mode)
        if hasattr(self, 'action_vis_mode_normal'):
            self.action_vis_mode_normal.setChecked(mode == "Normal")
            self.action_vis_mode_game.setChecked(mode == "Game Overlay")

    def _toggle_game_overlay_from_shortcut(self):
        self.visualizer_manager.toggle_game_overlay()
        new_mode = self.settings_mgr.get("visualizer_overlay_mode", "Normal")
        if hasattr(self, 'action_vis_mode_normal'):
            self.action_vis_mode_normal.setChecked(new_mode == "Normal")
            self.action_vis_mode_game.setChecked(new_mode == "Game Overlay")

    def _set_visualizer_layer_mode_from_tray(self, mode: str):
        self.settings_mgr.set("visualizer_window_layer_mode", mode)
        self.settings_mgr.set("visualizer_always_on_top", mode == "Top")
        self.visualizer_manager.apply_settings(self.settings_mgr.settings)

    def _toggle_visualizer_top_from_tray(self, checked: bool):
        mode = "Top" if checked else "Normal"
        self._set_visualizer_layer_mode_from_tray(mode)

    def _toggle_visualizer_click_through_from_tray(self, checked: bool):
        self.settings_mgr.set("visualizer_click_through", checked)
        self.visualizer_manager.apply_settings(self.settings_mgr.settings)

    # --- Desktop Wallpaper Tray Handlers ---
    def _toggle_wallpaper_enabled_from_tray(self, checked: bool):
        self.settings_mgr.set("wallpaper_enabled", checked)
        if hasattr(self, 'wallpaper_manager'):
            self.wallpaper_manager.apply_config(self.settings_mgr.settings)

    def _open_wallpaper_settings(self):
        self._open_settings()
        if self.settings_dialog and hasattr(self.settings_dialog, '_switch_page'):
            self.settings_dialog._switch_page("wallpaper")

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
                # Snap to border if enabled and near a screen edge
                if self.settings_mgr.get("snap_to_corners", True):
                    self._snap_to_nearest_corner()
                # Save position after drag
                pos = self.pos()
                self.settings_mgr.set("window_x", pos.x())
                self.settings_mgr.set("window_y", pos.y())
                self._apply_pending_resize()
        super().mouseReleaseEvent(event)

    def _snap_to_nearest_corner(self):
        """Snap the overlay to screen borders (sides, top, bottom, and corners) if within threshold."""
        edge, snapped_pos = calculate_edge_snap(self.geometry(), threshold=60)
        if edge:
            self.move(snapped_pos)
            log_event(f"🧲 [Lyrics Overlay] Snapped to {edge} border", force=True)
        else:
            safe_pos = constrain_to_work_area(self.pos(), self.size())
            self.move(safe_pos)

    def resizeEvent(self, event):
        """Debounced resize: saves dimensions after 500ms of no resize activity."""
        super().resizeEvent(event)
        # Restart the debounce timer on each resize event
        self._resize_timer.start(500)

    def _save_window_dimensions(self):
        """Actually save dimensions to disk (called by debounce timer)."""
        self.settings_mgr.set("window_width", self.width())
        self.settings_mgr.set("window_height", self.height())

    def shutdown(self):
        """Cleanly shuts down player threads, visualizer timers, wallpaper host, and saves settings."""
        if hasattr(self, 'wallpaper_manager'):
            self.wallpaper_manager.shutdown()
        if hasattr(self, 'visualizer_manager'):
            self.visualizer_manager.shutdown()
        if hasattr(self, 'player'):
            self.player.stop_worker_thread()
        if hasattr(self, 'settings_mgr'):
            self.settings_mgr.save_immediate()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _quit_application(self):
        self.shutdown()
        app = QApplication.instance()
        if app:
            app.quit()

