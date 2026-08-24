import os
import json
from typing import Dict, Any, Optional
from PyQt6.QtCore import QTimer

# Resolve settings path relative to the project root, not CWD.
# (Module lives in the lyrune/ package, legacy settings.json sits at the repo root.)
_LOCAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_SETTINGS: Dict[str, Any] = {
    "font_family": "Segoe UI",
    "font_size": 24,
    "font_bold": True,
    "text_color": "#FFFFFF",
    "bg_color": "#000000",
    "bg_opacity": 0,
    "border_enabled": False,     # Borderless by default as requested
    "shadow_enabled": True,
    "shadow_color": "#000000",
    "shadow_blur": 8,
    "text_align": "Center",
    "show_song_info": True,
    "always_on_top": True,
    "window_layer_mode": "Top",   # "Top" (Always on Top / Hover), "Normal", "Bottom" (Background / Desktop layer)
    "lock_position": False,
    "window_width": 800,
    "window_height": 220,
    "window_x": -1,              # -1 = not set / use system default
    "window_y": -1,
    "selected_media_source": "Auto-Detect",
    "sync_offset_ms": 0,          # Timing nudge in milliseconds (-5000ms to +5000ms)
    "context_lines": 2,          # Unified context lines before & after current lyric line (0 to 5)
    "auto_resize_height": True,   # Automatically adapt overlay height to current lyrics content
    "animation_speed_ms": 400,    # Duration of smooth Spotify-style scroll animation (100 to 800ms)
    "adaptive_color": False,      # Smart per-pixel contrast inversion over light/dark backgrounds
    "active_text_outline": True,  # High-contrast text contour outline on currently playing line
    "active_line_opacity": 100,   # Opacity percentage of currently playing lyric line (10-100%)
    "context_line_opacity": 45,   # Opacity percentage of context lyric lines (0-100%)
    "link_opacity_levels": True,  # Master link: scale active & context line opacities together proportionally
    "shortcut_toggle_overlay": "Ctrl+H",  # Hotkey to show/hide lyrics overlay
    "shortcut_refresh": "Ctrl+R",          # Hotkey to refresh/reload lyrics
    "shortcut_nudge_minus": "Ctrl+Left",   # Hotkey to nudge timing earlier (-250ms)
    "shortcut_nudge_plus": "Ctrl+Right",   # Hotkey to nudge timing later (+250ms)
    "click_through": False,       # Mouse-transparent click-through overlay mode
    "auto_hide_on_pause": False,  # Auto-hide overlay when media is paused/stopped
    "exclude_from_capture": False, # Exclude overlay window from OBS/Discord screen capture (Windows)
    "track_sync_offsets": {},     # Per-track sync timing offsets persistent dict
    "snap_to_corners": True,      # Snap overlay to screen borders/corners when dragged near edges

    # Standalone Visualizer Settings
    "visualizer_enabled": False,
    "visualizer_style": "Pill Bars",
    "visualizer_shape": "Pill",        # "Pill", "Rounded Bar", "Square Bar"
    "visualizer_corner_radius": 4,     # px corner radius for Rounded Bar
    "visualizer_auto_bar_count": True, # Auto-adapt bar count to width
    "visualizer_bar_count": 32,        # Custom manual bar count
    "visualizer_x": -1,
    "visualizer_y": -1,
    "visualizer_width": 320,           # Logical length
    "visualizer_height": 64,           # Logical thickness
    "visualizer_orientation": "BOTTOM",
    "visualizer_snap_edge": "BOTTOM",
    "visualizer_opacity": 100,
    "visualizer_color_mode": "Solid",  # "Solid", "Gradient", "Active Lyric Color"
    "visualizer_color": "#FFFFFF",
    "visualizer_gradient_stops": [
        {"pos": 0.0, "color": "#FF4D8D"},
        {"pos": 0.5, "color": "#8B5CF6"},
        {"pos": 1.0, "color": "#3B82F6"}
    ],
    "visualizer_gradient_direction": "Follow Visualizer", # "Follow Visualizer", "Fixed Horizontal", "Fixed Vertical", "Reverse"
    "visualizer_bar_width": 4,
    "visualizer_bar_spacing": 3,
    "visualizer_max_height": 100,
    "visualizer_sensitivity": 100,
    "visualizer_smoothing": 75,
    "visualizer_click_through": False,
    "visualizer_always_on_top": True,
    "visualizer_window_layer_mode": "Top", # "Top" (Hover over all), "Normal", "Bottom" (Background / Desktop layer)
    "visualizer_exclude_from_capture": False,
    "shortcut_toggle_visualizer": "Ctrl+Shift+V",

    # Game Overlay Mode Settings
    "visualizer_overlay_mode": "Normal",               # "Normal", "Game Overlay"
    "visualizer_overlay_screen": "Active Game Monitor", # "Active Game Monitor", "Primary Monitor", "Monitor 1", ...
    "visualizer_overlay_position": "Bottom",           # "Bottom", "Top", "Left", "Right", "Custom"
    "visualizer_overlay_margin": 15,                   # px margin inside game area (0 to 60)
    "visualizer_follow_active_window": False,          # Dynamically track foreground game window screen
    "visualizer_overlay_inactive_behavior": "Keep visible", # "Keep visible", "Hide"
    "shortcut_toggle_game_overlay": "Ctrl+Shift+G",
    "visualizer_normal_snapshot": {},
    "visualizer_game_snapshot": {},

    # Desktop Wallpaper System Settings
    "wallpaper_enabled": False,
    "wallpaper_type": "static",               # "static", "video"
    "wallpaper_path": "",
    "wallpaper_scaling_mode": "fill",         # "fill", "fit", "stretch", "center"
    "wallpaper_display_mode": "Primary Display", # "Primary Display", "All Displays", "Monitor 1", ...
    "wallpaper_vinyl_x": 0.78,                # Normalized [0.0, 1.0]
    "wallpaper_vinyl_y": 0.65,                # Normalized [0.0, 1.0]
    "wallpaper_vinyl_size": 0.20,             # Normalized diameter [0.05, 0.60]
    "wallpaper_vinyl_opacity": 100,           # 0 to 100%
    "wallpaper_vinyl_label_ratio": 38.0,      # Album cover size as % of vinyl disc [10% to 80%]
    "wallpaper_rotation_speed": 12.0,         # Seconds per revolution
    "wallpaper_show_title": True,
    "wallpaper_show_artist": True,
    "wallpaper_text_position": "Below",       # "Below", "Above", "Left", "Right", "Hidden"
    "wallpaper_text_alignment": "Center",     # "Center", "Left", "Right"
    "wallpaper_text_color": "#FFFFFF",        # Hex color
    "wallpaper_title_font_size": 14,          # Song title font size pt
    "wallpaper_artist_font_size": 11,         # Artist font size pt
    "wallpaper_rotate_while_playing": True,
    "wallpaper_pause_on_music_pause": True,
    "wallpaper_pause_on_battery": False,
    "wallpaper_pause_on_fullscreen": False,
}

PRESETS: Dict[str, Dict[str, Any]] = {
    "Default Clean": {
        "text_color": "#FFFFFF",
        "bg_color": "#000000",
        "bg_opacity": 0,
        "border_enabled": False,
        "shadow_enabled": True,
        "shadow_color": "#000000",
        "shadow_blur": 8,
        "font_bold": True,
        "context_lines": 2,
    },
    "Spotify Dark": {
        "text_color": "#1DB954",
        "bg_color": "#121212",
        "bg_opacity": 80,
        "border_enabled": False,
        "shadow_enabled": True,
        "shadow_color": "#000000",
        "shadow_blur": 10,
        "font_bold": True,
        "context_lines": 3,
    },
    "Cinematic Cyan": {
        "text_color": "#00F3FF",
        "bg_color": "#0D0D14",
        "bg_opacity": 75,
        "border_enabled": False,
        "shadow_enabled": True,
        "shadow_color": "#00F3FF",
        "shadow_blur": 14,
        "font_bold": True,
        "context_lines": 2,
    },
    "Neon Pink": {
        "text_color": "#FF007F",
        "bg_color": "#0A0A10",
        "bg_opacity": 60,
        "border_enabled": False,
        "shadow_enabled": True,
        "shadow_color": "#FF007F",
        "shadow_blur": 16,
        "font_bold": True,
        "context_lines": 2,
    },
    "High Contrast": {
        "text_color": "#FFFF00",
        "bg_color": "#000000",
        "bg_opacity": 90,
        "border_enabled": False,
        "shadow_enabled": False,
        "shadow_color": "#000000",
        "shadow_blur": 0,
        "font_bold": True,
        "context_lines": 1,
    }
}


def _get_app_config_dir() -> str:
    """Returns platform-appropriate user config directory."""
    if os.name == 'nt':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
    config_dir = os.path.join(base, 'Lyrune')
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


class SettingsManager:
    """
    Manages persistent configuration settings for Lyrune.

    Improvements over original:
      - Saves settings to user APPDATA/XDG_CONFIG directory (prevents PyInstaller temp dir losses).
      - Automatically migrates legacy local settings.json on startup.
      - Atomic disk writes via temporary file replace to prevent corrupted JSON.
      - Debounced disk writes (500ms) with flush-on-exit support.
    """

    def __init__(self, filename: str = "settings.json"):
        app_dir = _get_app_config_dir()
        self.filepath = os.path.join(app_dir, filename)

        # Legacy local settings migration (repo root, and old in-package location)
        legacy_paths = [os.path.join(_LOCAL_DIR, filename), os.path.join(_LOCAL_DIR, 'lyrune', filename)]
        if not os.path.exists(self.filepath):
            for local_path in legacy_paths:
                if os.path.exists(local_path):
                    try:
                        import shutil
                        shutil.copy2(local_path, self.filepath)
                    except Exception:
                        pass
                    break

        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._save_timer: Optional[QTimer] = None
        self._dirty = False
        self.load()

        # Auto-connect aboutToQuit to ensure clean save on app termination
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.save_immediate)

    def load(self) -> Dict[str, Any]:
        """Load settings from disk, merging with defaults for any missing keys."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.settings.update(saved)
                    # Strip orphaned keys not in DEFAULT_SETTINGS (remnants from old versions)
                    orphaned = [k for k in self.settings if k not in DEFAULT_SETTINGS]
                    for k in orphaned:
                        del self.settings[k]
                    if orphaned:
                        from lyrune.logger import log_event
                        log_event(f"[SettingsManager] Migrated out {len(orphaned)} orphaned key(s): {orphaned}")
                        self._write_to_disk()
            except Exception as e:
                from lyrune.logger import log_event
                log_event(f"⚠️ [SettingsManager Warning] Corrupted settings file, falling back to defaults: {e}")
                self.settings = dict(DEFAULT_SETTINGS)
        else:
            self._write_to_disk()
        return self.settings

    def _write_to_disk(self) -> None:
        """Immediate atomic write to disk."""
        tmp_path = f"{self.filepath}.tmp_{os.getpid()}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            os.replace(tmp_path, self.filepath)
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            from lyrune.logger import log_event
            log_event(f"❌ [SettingsManager Exception] Failed to write settings to disk: {e}")
        self._dirty = False

    def _schedule_save(self) -> None:
        """
        Debounced save: schedules a disk write after 500ms of inactivity.
        Multiple rapid calls only trigger one write.
        """
        self._dirty = True
        if self._save_timer is None:
            self._save_timer = QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self._on_save_timer)
        # Restart the timer on every call
        self._save_timer.start(500)

    def _on_save_timer(self) -> None:
        """Timer callback: actually write to disk."""
        if self._dirty:
            self._write_to_disk()

    def save(self) -> None:
        """Public save — uses debounced scheduling."""
        self._schedule_save()

    def save_immediate(self) -> None:
        """Force an immediate synchronous write (e.g., on app exit)."""
        if self._save_timer and self._save_timer.isActive():
            self._save_timer.stop()
        self._write_to_disk()

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.save()

    def update(self, new_settings: Dict[str, Any]) -> None:
        self.settings.update(new_settings)
        self.save()

    def reset_to_defaults(self) -> Dict[str, Any]:
        self.settings = dict(DEFAULT_SETTINGS)
        self.save_immediate()
        return self.settings

    def reset_visualizer_settings(self) -> Dict[str, Any]:
        """Resets ONLY visualizer-related settings back to defaults without touching lyrics or app settings."""
        vis_keys = [k for k in DEFAULT_SETTINGS if k.startswith("visualizer_") and k not in ("visualizer_x", "visualizer_y")]
        for k in vis_keys:
            self.settings[k] = DEFAULT_SETTINGS[k]
        self.save_immediate()
        return self.settings
