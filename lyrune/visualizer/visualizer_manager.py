"""
visualizer_manager.py — Coordinator for the Lyrune visualizer system.

Responsibilities:
  - Manages VisualizerWindow, active visualizer strategy (BarVisualizer), and AudioSource
  - Synchronizes rendering loop and media playback lifecycle (play, pause, stop, track change)
  - Manages independent visibility, settings persistence, and style updates
  - Provides Game Overlay Mode for borderless fullscreen game HUDs with multi-monitor tracking
  - Provides clean public methods for Tray menu, hotkeys, and Settings dialog
"""

from typing import Dict, Any, Optional
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from lyrune.visualizer.base import BaseVisualizer
from lyrune.visualizer.bar_visualizer import BarVisualizer
from lyrune.visualizer.audio_source import AdaptiveAudioSource
from lyrune.visualizer.visualizer_window import VisualizerWindow
from lyrune.settings_manager import SettingsManager
from lyrune.logger import log_event
from lyrune.window_utils import (
    get_target_screen_by_name,
    get_active_game_screen,
    get_foreground_window_rect,
    is_window_fullscreen,
    reassert_window_topmost,
    is_window_below_foreground,
    is_window_below_any_topmost
)


class VisualizerManager(QObject):
    """
    Master controller for Lyrune's visualizer subsystem.
    """
    visibility_changed = pyqtSignal(bool)
    overlay_mode_changed = pyqtSignal(str)

    def __init__(self, settings_manager: SettingsManager, player: Optional[Any] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.settings_mgr = settings_manager
        self.player = player

        # Visualizer strategy registry
        self._visualizers: Dict[str, BaseVisualizer] = {
            "Pill Bars": BarVisualizer(),
            "Standard Bars": BarVisualizer(),
            "Bars": BarVisualizer()
        }
        self._current_style_name = self.settings_mgr.get("visualizer_style", "Pill Bars")
        self._active_visualizer = self._visualizers.get(self._current_style_name, self._visualizers["Pill Bars"])

        # Audio pipeline
        self.audio_source = AdaptiveAudioSource(num_bands=32, parent=self)
        self.audio_source.audio_ready.connect(self._on_audio_data)

        # Independent Window
        self.window = VisualizerWindow(visualizer=self._active_visualizer)
        self.window.position_changed.connect(self._on_window_position_changed)

        # Render loop timer (60 FPS)
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(16)
        self._render_timer.timeout.connect(self._on_render_tick)

        # Game Overlay tracking timer (500ms, low CPU overhead)
        self._game_tracking_timer = QTimer(self)
        self._game_tracking_timer.setInterval(500)
        self._game_tracking_timer.timeout.connect(self._on_game_tracking_tick)
        self._last_game_screen_name: str = ""
        self._game_overlay_hidden_by_inactive: bool = False

        # Track state
        self._last_track_id: str = ""
        self._last_status: str = ""
        self._manually_hidden: bool = False

        # Initialize
        self._init_from_settings()

    def _init_from_settings(self) -> None:
        """Initializes window position, styles, and audio pipeline from persistent settings."""
        s = self.settings_mgr.settings
        self.window.restore_saved_state(s)

        # Check if starting in Game Overlay Mode
        if s.get("visualizer_overlay_mode") == "Game Overlay":
            self._apply_game_overlay_position()
            self._start_game_tracking()

        enabled = s.get("visualizer_enabled", False)
        if enabled and not self._manually_hidden:
            self.window.show()
            self.audio_source.start()
            self._render_timer.start()
        else:
            self.window.hide()

        log_event(f"✨ [VisualizerManager] Initialized (Style: {self._current_style_name}, Mode: {s.get('visualizer_overlay_mode', 'Normal')}, Enabled: {enabled})", force=True)

    def _on_audio_data(self, audio_data) -> None:
        """Delivers audio frame to active visualizer."""
        if self._active_visualizer and self.window.isVisible():
            self._active_visualizer.update_audio(audio_data)

    def _on_render_tick(self) -> None:
        """60 FPS repaint tick for the visualizer window."""
        if self.window.isVisible():
            if hasattr(self._active_visualizer, 'get_bar_count'):
                self.audio_source.set_target_bars(self._active_visualizer.get_bar_count())
            self.window.update()

    def get_audio_diagnostics(self) -> Dict[str, Any]:
        """Returns real-time audio capture and spectral analysis diagnostics."""
        if hasattr(self.audio_source, 'get_diagnostics'):
            diag = self.audio_source.get_diagnostics()
        else:
            diag = {}
        diag["active_style"] = self._current_style_name
        diag["overlay_mode"] = self.settings_mgr.get("visualizer_overlay_mode", "Normal")
        diag["window_visible"] = self.window.isVisible()
        diag["orientation"] = self.window._orientation
        diag["snap_edge"] = self.window._snap_edge
        diag["bar_count"] = getattr(self._active_visualizer, 'get_bar_count', lambda: 32)()
        return diag

    def _on_window_position_changed(self, pos_data: Dict[str, Any]) -> None:
        """Saves window position and orientation to settings."""
        if self.settings_mgr.get("visualizer_overlay_mode") == "Normal":
            for k, v in pos_data.items():
                self.settings_mgr.settings[k] = v
            self.settings_mgr.save()

    def set_style(self, style_name: str) -> None:
        """Swaps active visualizer style (extensible for future visualizers)."""
        if style_name in self._visualizers:
            self._current_style_name = style_name
            self._active_visualizer = self._visualizers[style_name]
            self.window.set_visualizer(self._active_visualizer)
            self._active_visualizer.set_style(self.settings_mgr.settings)
            self.settings_mgr.set("visualizer_style", style_name)
            log_event(f"🎨 [VisualizerManager] Visualizer style set to: {style_name}", force=True)

    def set_overlay_mode(self, mode: str) -> None:
        """Switches between 'Normal' and 'Game Overlay' modes while preserving user snapshots."""
        current_mode = self.settings_mgr.get("visualizer_overlay_mode", "Normal")
        if mode == current_mode:
            return

        s = self.settings_mgr.settings

        if mode == "Game Overlay":
            # 1. Take snapshot of current Normal state
            normal_snapshot = {
                "visualizer_x": self.window.pos().x(),
                "visualizer_y": self.window.pos().y(),
                "visualizer_width": s.get("visualizer_width", 320),
                "visualizer_height": s.get("visualizer_height", 64),
                "visualizer_orientation": self.window._orientation,
                "visualizer_snap_edge": self.window._snap_edge,
                "visualizer_always_on_top": s.get("visualizer_always_on_top", True),
                "visualizer_click_through": s.get("visualizer_click_through", False),
                "visualizer_opacity": s.get("visualizer_opacity", 100),
            }
            s["visualizer_normal_snapshot"] = normal_snapshot
            s["visualizer_overlay_mode"] = "Game Overlay"

            # 2. Apply Game Overlay configuration defaults
            s["visualizer_always_on_top"] = True
            s["visualizer_click_through"] = True

            self._apply_game_overlay_position()
            self._start_game_tracking()

            log_event("🎮 [Visualizer] Game Overlay Mode ACTIVATED", force=True)

        else:  # Switching back to Normal mode
            # 1. Save Game Overlay snapshot
            game_snapshot = {
                "visualizer_overlay_screen": s.get("visualizer_overlay_screen", "Active Game Monitor"),
                "visualizer_overlay_position": s.get("visualizer_overlay_position", "Bottom"),
                "visualizer_overlay_margin": s.get("visualizer_overlay_margin", 15),
            }
            s["visualizer_game_snapshot"] = game_snapshot
            s["visualizer_overlay_mode"] = "Normal"

            self._stop_game_tracking()
            if self._game_overlay_hidden_by_inactive and not self._manually_hidden:
                self.window.show()
                self._game_overlay_hidden_by_inactive = False

            # 2. Restore Normal snapshot
            norm = s.get("visualizer_normal_snapshot", {})
            if norm:
                s["visualizer_always_on_top"] = norm.get("visualizer_always_on_top", True)
                s["visualizer_click_through"] = norm.get("visualizer_click_through", False)
                s["visualizer_opacity"] = norm.get("visualizer_opacity", 100)
                s["visualizer_width"] = norm.get("visualizer_width", 320)
                s["visualizer_height"] = norm.get("visualizer_height", 64)
                s["visualizer_orientation"] = norm.get("visualizer_orientation", "BOTTOM")
                s["visualizer_snap_edge"] = norm.get("visualizer_snap_edge", "BOTTOM")
                s["visualizer_x"] = norm.get("visualizer_x", -1)
                s["visualizer_y"] = norm.get("visualizer_y", -1)

                self.window.restore_saved_state(s)

            log_event("🖥️ [Visualizer] Normal Desktop Mode RESTORED", force=True)

        self.settings_mgr.save()
        self.apply_settings(s)
        self.overlay_mode_changed.emit(mode)

    def toggle_game_overlay(self) -> None:
        """Toggles between Normal mode and Game Overlay mode."""
        current_mode = self.settings_mgr.get("visualizer_overlay_mode", "Normal")
        new_mode = "Game Overlay" if current_mode == "Normal" else "Normal"
        self.set_overlay_mode(new_mode)

    def _apply_game_overlay_position(self) -> None:
        """Positions the visualizer on the target screen using Game Overlay presets & margin."""
        s = self.settings_mgr.settings
        target_screen_name = s.get("visualizer_overlay_screen", "Active Game Monitor")
        target_screen = get_target_screen_by_name(target_screen_name)
        pos_preset = s.get("visualizer_overlay_position", "Bottom")
        margin = s.get("visualizer_overlay_margin", 15)

        self.window.set_preset_position(
            preset=pos_preset,
            screen=target_screen,
            margin=margin,
            use_full_screen=True
        )
        self._last_game_screen_name = target_screen.name() if target_screen else ""

    def _start_game_tracking(self) -> None:
        if not self._game_tracking_timer.isActive():
            self._game_tracking_timer.start()

    def _stop_game_tracking(self) -> None:
        if self._game_tracking_timer.isActive():
            self._game_tracking_timer.stop()

    def _on_game_tracking_tick(self) -> None:
        """Low-frequency (500ms) background tracking for active game/window transitions."""
        s = self.settings_mgr.settings
        mode = s.get("visualizer_overlay_mode", "Normal")
        always_top = s.get("visualizer_always_on_top", True)

        if mode != "Game Overlay" and not always_top:
            self._stop_game_tracking()
            return

        # Windows Z-guard: maintain topmost Z-order above fullscreen games without stealing focus
        if self.window.isVisible() and always_top:
            hwnd = int(self.window.winId()) if self.window.winId() else 0
            if hwnd and (is_window_below_any_topmost(hwnd) or is_window_below_foreground(hwnd)):
                reassert_window_topmost(hwnd)

        if mode != "Game Overlay":
            return

        target_mode = s.get("visualizer_overlay_screen", "Active Game Monitor")
        follow_window = s.get("visualizer_follow_active_window", False)
        inactive_behavior = s.get("visualizer_overlay_inactive_behavior", "Keep visible")

        current_active_screen = get_active_game_screen()
        win_rect = get_foreground_window_rect()
        is_fullscreen = is_window_fullscreen(win_rect, current_active_screen) if win_rect else False

        # Inactive behavior handling when follow active window is enabled
        if follow_window and inactive_behavior == "Hide":
            if not is_fullscreen:
                if self.window.isVisible() and not self._game_overlay_hidden_by_inactive:
                    self.window.hide()
                    self._game_overlay_hidden_by_inactive = True
                return
            else:
                if self._game_overlay_hidden_by_inactive and not self._manually_hidden:
                    self.window.show()
                    self._game_overlay_hidden_by_inactive = False

        # Multi-monitor target screen tracking
        if target_mode == "Active Game Monitor" or follow_window:
            if current_active_screen and current_active_screen.name() != self._last_game_screen_name:
                self._apply_game_overlay_position()

    def apply_settings(self, s: Dict[str, Any]) -> None:
        """Applies configuration changes live."""
        style_name = s.get("visualizer_style", "Pill Bars")
        if style_name != self._current_style_name:
            self.set_style(style_name)

        mode = s.get("visualizer_overlay_mode", "Normal")
        always_top = s.get("visualizer_always_on_top", True)

        if mode == "Game Overlay":
            self._apply_game_overlay_position()
            self._start_game_tracking()
        elif always_top:
            self._start_game_tracking()
        else:
            self._stop_game_tracking()

        self.window.apply_settings(s)

        enabled = s.get("visualizer_enabled", False)
        if enabled:
            if not self.window.isVisible() and not self._manually_hidden and not self._game_overlay_hidden_by_inactive:
                self.window.show()
            if not self.audio_source.is_active():
                self.audio_source.start()
            if not self._render_timer.isActive():
                self._render_timer.start()
        else:
            self.window.hide()
            self.audio_source.stop()
            self._render_timer.stop()

    def update_playback_state(self, info: Dict[str, Any]) -> None:
        """Synchronizes visualizer with media playback state."""
        status = info.get("status", "Paused")
        is_running = info.get("is_running", False)
        artist = info.get("artist") or ""
        title = info.get("title") or ""
        track_id = f"{artist} - {title}"

        self.audio_source.set_media_info(info)

        if track_id != self._last_track_id and bool(title):
            self._last_track_id = track_id
            if self._active_visualizer:
                self._active_visualizer.reset()
            log_event(f"🎵 [Visualizer] Track sync: '{track_id}'")

        if self._active_visualizer:
            self._active_visualizer.update_media_state(status, is_running, track_id)

    def set_preset_position(self, preset: str) -> None:
        """Snaps visualizer window to preset position."""
        if self.settings_mgr.get("visualizer_overlay_mode") == "Game Overlay":
            self.settings_mgr.set("visualizer_overlay_position", preset)
            self._apply_game_overlay_position()
        else:
            self.window.set_preset_position(preset)

    def toggle_visibility(self) -> None:
        """Toggles visualizer window visibility independently from lyrics overlay."""
        if self.window.isVisible():
            self._manually_hidden = True
            self.window.hide()
            self.visibility_changed.emit(False)
            log_event("👁️ [Visualizer] Manually hidden", force=True)
        else:
            self._manually_hidden = False
            self._game_overlay_hidden_by_inactive = False
            self.window.show()
            if not self.audio_source.is_active():
                self.audio_source.start()
            if not self._render_timer.isActive():
                self._render_timer.start()
            self.visibility_changed.emit(True)
            log_event("👁️ [Visualizer] Manually shown", force=True)

    def is_visible(self) -> bool:
        return self.window.isVisible()

    def shutdown(self) -> None:
        """Cleanly stops timers, audio streams, and saves final geometry."""
        self._render_timer.stop()
        self._game_tracking_timer.stop()
        self.audio_source.stop()
        if self.settings_mgr.get("visualizer_overlay_mode") == "Normal":
            pos = self.window.pos()
            self.settings_mgr.settings["visualizer_x"] = pos.x()
            self.settings_mgr.settings["visualizer_y"] = pos.y()
            self.settings_mgr.settings["visualizer_orientation"] = self.window._orientation
            self.settings_mgr.settings["visualizer_snap_edge"] = self.window._snap_edge
            self.settings_mgr.save_immediate()
        log_event("[VisualizerManager] Subsystem shutdown completed.")
