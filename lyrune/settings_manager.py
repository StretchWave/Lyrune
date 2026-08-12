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
