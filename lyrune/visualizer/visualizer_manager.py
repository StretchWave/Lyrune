"""
visualizer_manager.py — Coordinator for the Lyrune visualizer system.

Responsibilities:
  - Manages VisualizerWindow, active visualizer strategy (BarVisualizer), and AudioSource
  - Synchronizes rendering loop and media playback lifecycle (play, pause, stop, track change)
  - Manages independent visibility, settings persistence, and style updates
  - Provides clean public methods for Tray menu and Settings dialog
"""

from typing import Dict, Any, Optional
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from lyrune.visualizer.base import BaseVisualizer
from lyrune.visualizer.bar_visualizer import BarVisualizer
from lyrune.visualizer.audio_source import AdaptiveAudioSource
from lyrune.visualizer.visualizer_window import VisualizerWindow
from lyrune.settings_manager import SettingsManager
from lyrune.logger import log_event


class VisualizerManager(QObject):
    """
    Master controller for Lyrune's visualizer subsystem.
    """
    visibility_changed = pyqtSignal(bool)

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

        enabled = s.get("visualizer_enabled", True)
        if enabled and not self._manually_hidden:
            self.window.show()
            self.audio_source.start()
            self._render_timer.start()
        else:
            self.window.hide()

        log_event(f"✨ [VisualizerManager] Initialized (Style: {self._current_style_name}, Enabled: {enabled})", force=True)

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
        diag["window_visible"] = self.window.isVisible()
        diag["orientation"] = self.window._orientation
        diag["snap_edge"] = self.window._snap_edge
        diag["bar_count"] = getattr(self._active_visualizer, 'get_bar_count', lambda: 32)()
        return diag

    def _on_window_position_changed(self, pos_data: Dict[str, Any]) -> None:
        """Saves window position and orientation to settings."""
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

    def apply_settings(self, s: Dict[str, Any]) -> None:
        """Applies configuration changes live."""
        style_name = s.get("visualizer_style", "Bars")
        if style_name != self._current_style_name:
            self.set_style(style_name)

        self.window.apply_settings(s)

        enabled = s.get("visualizer_enabled", True)
        if enabled:
            if not self.window.isVisible() and not self._manually_hidden:
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

        # Propagate to audio source
        self.audio_source.set_media_info(info)

        # Detect track changes
        if track_id != self._last_track_id and bool(title):
            self._last_track_id = track_id
            if self._active_visualizer:
                self._active_visualizer.reset()
            log_event(f"🎵 [Visualizer] Track sync: '{track_id}'")

        # Propagate status to visualizer
        if self._active_visualizer:
            self._active_visualizer.update_media_state(status, is_running, track_id)

    def set_preset_position(self, preset: str) -> None:
        """Snaps visualizer window to preset position."""
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
        self.audio_source.stop()
        pos = self.window.pos()
        self.settings_mgr.settings["visualizer_x"] = pos.x()
        self.settings_mgr.settings["visualizer_y"] = pos.y()
        self.settings_mgr.settings["visualizer_orientation"] = self.window._orientation
        self.settings_mgr.settings["visualizer_snap_edge"] = self.window._snap_edge
        self.settings_mgr.save_immediate()
        log_event("[VisualizerManager] Subsystem shutdown completed.")
