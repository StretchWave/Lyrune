import os
import json
from typing import Dict, Any, Optional
from PyQt6.QtCore import QTimer

# Resolve settings path relative to THIS script's directory, not CWD
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_SETTINGS: Dict[str, Any] = {
    "font_family": "Segoe UI",
    "font_size": 26,
    "font_bold": True,
    "text_color": "#FFFFFF",
    "bg_color": "#000000",
    "bg_opacity": 0,
    "shadow_enabled": True,
    "shadow_color": "#000000",
    "shadow_blur": 8,
    "text_align": "Center",
    "show_song_info": True,
    "always_on_top": True,
    "lock_position": False,
    "window_width": 800,
    "window_height": 160,
    "window_x": -1,           # -1 = not set / use system default
    "window_y": -1,
    "selected_media_source": "Auto-Detect",
    "sync_offset_ms": 0,       # Timing nudge in milliseconds (-3000ms to +3000ms)
    "multi_line_enabled": True, # Enable multi-line previous & upcoming lyrics context
    "context_lines_above": 1,  # Number of previous lines to show (0 to 5)
    "context_lines_below": 1   # Number of upcoming lines to show (0 to 5)
}

PRESETS: Dict[str, Dict[str, Any]] = {
    "Default Clean": {
        "text_color": "#FFFFFF",
        "bg_color": "#000000",
        "bg_opacity": 0,
        "shadow_enabled": True,
        "shadow_color": "#000000",
        "shadow_blur": 8,
        "font_bold": True
    },
    "Cinematic Dark": {
        "text_color": "#00F3FF",
        "bg_color": "#121218",
        "bg_opacity": 75,
        "shadow_enabled": True,
        "shadow_color": "#000000",
        "shadow_blur": 12,
        "font_bold": True
    },
    "Neon Glow": {
        "text_color": "#FF007F",
        "bg_color": "#0A0A10",
        "bg_opacity": 50,
        "shadow_enabled": True,
        "shadow_color": "#FF007F",
        "shadow_blur": 18,
        "font_bold": True
    },
    "High Contrast": {
        "text_color": "#FFFF00",
        "bg_color": "#000000",
        "bg_opacity": 90,
        "shadow_enabled": False,
        "shadow_color": "#000000",
        "shadow_blur": 0,
        "font_bold": True
    }
}


class SettingsManager:
    """
    Manages persistent configuration settings for LyricScript.

    Improvements over original:
      - Settings file path is resolved relative to the script directory (absolute),
        so it works correctly regardless of the process's working directory.
      - Debounced disk writes: rapid set() calls (e.g., during window resize) are
        batched into a single JSON write after a 500ms quiet period.
      - Adds window_x / window_y for position persistence across restarts.
    """

    def __init__(self, filename: str = "settings.json"):
        self.filepath = os.path.join(_SCRIPT_DIR, filename)
        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._save_timer: Optional[QTimer] = None
        self._dirty = False
        self.load()

    def load(self) -> Dict[str, Any]:
        """Load settings from disk, merging with defaults for any missing keys."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.settings.update(saved)
            except Exception:
                self.settings = dict(DEFAULT_SETTINGS)
        else:
            self._write_to_disk()
        return self.settings

    def _write_to_disk(self) -> None:
        """Immediate synchronous write to disk."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
        except Exception:
            pass
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
