"""
settings_manager.py — Configuration persistence, schema migrations, profiles, and backup/restore.

Provides robust, versioned JSON configuration persistence in the user's APPDATA/XDG directory
with atomic disk writes, debounced saves, corrupt file recovery, schema migrations, and preset profiles.
"""

import os
import sys
import json
import time
import shutil
from typing import Dict, Any, Optional, List, Tuple
from PyQt6.QtCore import QTimer

# Resolve project root
_LOCAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CURRENT_SCHEMA_VERSION = 2

DEFAULT_SETTINGS: Dict[str, Any] = {
    "settings_schema_version": CURRENT_SCHEMA_VERSION,

    # Typography & Lyrics Presentation
    "font_family": "Segoe UI",
    "font_size": 24,
    "font_bold": True,
    "text_color": "#FFFFFF",
    "bg_color": "#000000",
    "bg_opacity": 0,
    "border_enabled": False,
    "shadow_enabled": True,
    "shadow_color": "#000000",
    "shadow_blur": 8,
    "text_align": "Center",
    "show_song_info": True,
    "context_lines": 2,
    "auto_resize_height": True,
    "animation_speed_ms": 400,
    "adaptive_color": False,
    "active_text_outline": True,
    "active_line_opacity": 100,
    "context_line_opacity": 45,
    "link_opacity_levels": True,
    "lyrics_view_mode": "Multi-line",   # "Multi-line", "Single-line Ticker", "Minimal"

    # Lyrics Synchronization & Matching
    "sync_offset_ms": 0,
    "track_sync_offsets": {},           # Per-track persistent sync offsets dict
    "auto_search_lyrics": True,

    # Media Source Management & Deterministic Priority
    "selected_media_source": "Auto-Detect",
    "prefer_playing_session": True,
    "source_priority": [
        "Spotify Desktop",
        "Spotify Web",
        "YouTube Music",
        "Brave",
        "Chrome",
        "Edge",
        "Firefox",
        "Opera"
    ],

    # Lyrics Overlay Window Geometry & Behavior
    "always_on_top": True,
    "window_layer_mode": "Top",         # "Top", "Normal", "Bottom"
    "lock_position": False,
    "window_width": 800,
    "window_height": 220,
    "window_x": -1,
    "window_y": -1,
    "snap_to_corners": True,
    "click_through": False,
    "auto_hide_on_pause": False,
    "auto_hide_delay_sec": 5,
    "exclude_from_capture": False,

    # Standalone Visualizer Subsystem
    "visualizer_enabled": False,
    "visualizer_style": "Pill Bars",
    "visualizer_shape": "Pill",        # "Pill", "Rounded Bar", "Square Bar"
    "visualizer_corner_radius": 4,
    "visualizer_auto_bar_count": True,
    "visualizer_bar_count": 32,
    "visualizer_x": -1,
    "visualizer_y": -1,
    "visualizer_width": 320,
    "visualizer_height": 64,
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
    "visualizer_gradient_direction": "Follow Visualizer",
    "visualizer_bar_width": 4,
    "visualizer_bar_spacing": 3,
    "visualizer_max_height": 100,
    "visualizer_sensitivity": 100,
    "visualizer_smoothing": 75,
    "visualizer_click_through": False,
    "visualizer_always_on_top": True,
    "visualizer_window_layer_mode": "Top",
    "visualizer_exclude_from_capture": False,
    "visualizer_preview_mode": "Demo",  # "Demo", "Live Audio"
    "visualizer_fft_size": 1024,
    "visualizer_frequency_scale": "Logarithmic",
    "visualizer_channel": "Stereo",

    # Game Overlay Mode
    "visualizer_overlay_mode": "Normal",               # "Normal", "Game Overlay"
    "visualizer_overlay_screen": "Active Game Monitor",
    "visualizer_overlay_position": "Bottom",
    "visualizer_overlay_margin": 15,
    "visualizer_follow_active_window": False,
    "visualizer_overlay_inactive_behavior": "Keep visible",
    "visualizer_normal_snapshot": {},
    "visualizer_game_snapshot": {},

    # Desktop Wallpaper Engine
    "wallpaper_enabled": False,
    "wallpaper_type": "static",               # "static", "video"
    "wallpaper_path": "",
    "wallpaper_scaling_mode": "fill",         # "fill", "fit", "stretch", "center"
    "wallpaper_display_mode": "Primary Display",
    "wallpaper_vinyl_x": 0.78,
    "wallpaper_vinyl_y": 0.65,
    "wallpaper_vinyl_size": 0.20,
    "wallpaper_vinyl_opacity": 100,
    "wallpaper_vinyl_label_ratio": 38.0,
    "wallpaper_rotation_speed": 12.0,
    "wallpaper_show_title": True,
    "wallpaper_show_artist": True,
    "wallpaper_text_position": "Below",
    "wallpaper_text_alignment": "Center",
    "wallpaper_text_color": "#FFFFFF",
    "wallpaper_title_font_size": 14,
    "wallpaper_artist_font_size": 11,
    "wallpaper_rotate_while_playing": True,
    "wallpaper_pause_on_music_pause": True,
    "wallpaper_pause_on_battery": False,
    "wallpaper_pause_on_fullscreen": False,
    "wallpaper_fps": 30,
    "wallpaper_snapping": True,
    "wallpaper_debug_hud": False,

    # Global Appearance & Materials
    "theme_mode": "Dynamic Album Accent",  # "Dynamic Album Accent", "Manual Accent", "Neutral Dark"
    "manual_accent_color": "#1DB954",
    "glass_intensity": 75,
    "background_style": "Cosmic Nebula",   # "Cosmic Nebula", "Album Glow", "Minimal Dark", "Solid"
    "reduced_motion": False,

    # Global System & Behavior
    "close_action": "Minimize to Tray",    # "Minimize to Tray", "Hide Window", "Quit App"
    "start_with_windows": False,

    # Shortcuts
    "shortcut_toggle_overlay": "Ctrl+H",
    "shortcut_refresh": "Ctrl+R",
    "shortcut_nudge_minus": "Ctrl+Left",
    "shortcut_nudge_plus": "Ctrl+Right",
    "shortcut_toggle_visualizer": "Ctrl+Shift+V",
    "shortcut_toggle_game_overlay": "Ctrl+Shift+G",
    "shortcut_command_palette": "Ctrl+K",

    # Performance & Power Profile
    "power_profile": "Balanced",          # "High Performance", "Balanced", "Battery Saver"
    "preview_fps": 60,
    "background_polling_ms": 80,

    # Profiles & Presets
    "active_profile": "Default",
    "profiles": {}
}

DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
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
    "Neon Spectrum": {
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
    "Minimal Gaming": {
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

PRESETS = DEFAULT_PROFILES


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
    Includes schema migrations, corrupt recovery, export/import, and profile presets.
    """

    def __init__(self, filename: str = "settings.json"):
        self.app_dir = _get_app_config_dir()
        self.filepath = os.path.join(self.app_dir, filename)
        self.backup_dir = os.path.join(self.app_dir, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

        # Legacy local settings migration
        legacy_paths = [os.path.join(_LOCAL_DIR, filename), os.path.join(_LOCAL_DIR, 'lyrune', filename)]
        if not os.path.exists(self.filepath):
            for local_path in legacy_paths:
                if os.path.exists(local_path):
                    try:
                        shutil.copy2(local_path, self.filepath)
                    except Exception:
                        pass
                    break

        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._save_timer: Optional[QTimer] = None
        self._dirty = False
        self.load()

        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.save_immediate)

    def _migrate_schema(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Applies schema migrations to older config files."""
        migrated = dict(raw)
        version = raw.get("settings_schema_version", 1)

        if version < 2:
            from lyrune.logger import log_event
            log_event(f"⚙️ [SettingsManager] Migrating schema from v{version} to v2...")

            # Canonical scaling mode names
            scaling = str(migrated.get("wallpaper_scaling_mode", "fill")).lower()
            if scaling in ("fill", "fit", "stretch", "center"):
                migrated["wallpaper_scaling_mode"] = scaling
            else:
                migrated["wallpaper_scaling_mode"] = "fill"

            # Canonical orientation names
            orientation = str(migrated.get("visualizer_orientation", "BOTTOM")).upper()
            if orientation in ("TOP", "BOTTOM", "LEFT", "RIGHT"):
                migrated["visualizer_orientation"] = orientation

            # Add missing defaults
            for key, val in DEFAULT_SETTINGS.items():
                if key not in migrated:
                    migrated[key] = val

            migrated["settings_schema_version"] = CURRENT_SCHEMA_VERSION

        return migrated

    def load(self) -> Dict[str, Any]:
        """Load settings from disk, merging with defaults and running migrations."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    saved = json.load(f)

                migrated = self._migrate_schema(saved)

                # Merge over defaults
                self.settings = dict(DEFAULT_SETTINGS)
                self.settings.update(migrated)

                # Strip unknown obsolete keys
                orphaned = [k for k in list(self.settings.keys()) if k not in DEFAULT_SETTINGS]
                for k in orphaned:
                    del self.settings[k]

                if orphaned:
                    from lyrune.logger import log_event
                    log_event(f"[SettingsManager] Pruned {len(orphaned)} obsolete key(s): {orphaned}")
                    self._write_to_disk()

            except Exception as e:
                from lyrune.logger import log_event
                log_event(f"⚠️ [SettingsManager Warning] Corrupted settings file, backing up & recovering defaults: {e}")

                # Backup corrupt file
                corrupt_backup = os.path.join(
                    self.backup_dir,
                    f"settings_corrupt_{int(time.time())}.json"
                )
                try:
                    shutil.copy2(self.filepath, corrupt_backup)
                    log_event(f"💾 [SettingsManager] Saved corrupt settings copy to: {corrupt_backup}")
                except Exception:
                    pass

                self.settings = dict(DEFAULT_SETTINGS)
                self._write_to_disk()
        else:
            self.settings = dict(DEFAULT_SETTINGS)
            self._write_to_disk()

        return self.settings

    def _write_to_disk(self) -> None:
        """Immediate atomic write to disk via temp file."""
        tmp_path = f"{self.filepath}.tmp_{os.getpid()}_{int(time.time() * 1000)}"
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
        """Debounced save: writes to disk after 400ms of inactivity."""
        self._dirty = True
        if self._save_timer is None:
            self._save_timer = QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self._on_save_timer)
        self._save_timer.start(400)

    def _on_save_timer(self) -> None:
        if self._dirty:
            self._write_to_disk()

    def save(self) -> None:
        self._schedule_save()

    def save_immediate(self) -> None:
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

    # === Backup & Restore ===

    def create_backup(self, label: str = "") -> str:
        """Creates a timestamped snapshot backup of current settings."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_label = f"_{label.strip().replace(' ', '_')}" if label else ""
        filename = f"backup_{ts}{safe_label}.json"
        target_path = os.path.join(self.backup_dir, filename)

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=4)

        from lyrune.logger import log_event
        log_event(f"💾 [SettingsManager] Backup created: {filename}")
        return target_path

    def restore_backup(self, backup_path: str) -> bool:
        """Restores settings from a backup JSON file."""
        if not os.path.exists(backup_path):
            return False
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            migrated = self._migrate_schema(data)
            self.settings.update(migrated)
            self.save_immediate()
            from lyrune.logger import log_event
            log_event(f"🔄 [SettingsManager] Restored settings from backup: {os.path.basename(backup_path)}")
            return True
        except Exception as e:
            from lyrune.logger import log_event
            log_event(f"❌ [SettingsManager] Failed to restore backup: {e}")
            return False

    def list_backups(self) -> List[Dict[str, Any]]:
        """Returns sorted list of available backup files."""
        if not os.path.exists(self.backup_dir):
            return []
        items = []
        for fn in sorted(os.listdir(self.backup_dir), reverse=True):
            if fn.endswith(".json"):
                full_p = os.path.join(self.backup_dir, fn)
                items.append({
                    "filename": fn,
                    "path": full_p,
                    "size": os.path.getsize(full_p),
                    "time": time.ctime(os.path.getmtime(full_p))
                })
        return items

    # === Import & Export ===

    def export_settings(self, export_path: str) -> bool:
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            return True
        except Exception as e:
            from lyrune.logger import log_event
            log_event(f"❌ [SettingsManager] Export failed: {e}")
            return False

    def import_settings(self, import_path: str) -> bool:
        if not os.path.exists(import_path):
            return False
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            migrated = self._migrate_schema(data)
            self.settings.update(migrated)
            self.save_immediate()
            return True
        except Exception as e:
            from lyrune.logger import log_event
            log_event(f"❌ [SettingsManager] Import failed: {e}")
            return False

    # === Profiles ===

    def get_profiles(self) -> List[str]:
        builtin = list(DEFAULT_PROFILES.keys())
        custom = list(self.settings.get("profiles", {}).keys())
        return builtin + [c for c in custom if c not in builtin]

    def save_profile(self, name: str) -> bool:
        if not name:
            return False
        profiles = self.settings.setdefault("profiles", {})
        profiles[name] = dict(self.settings)
        self.settings["active_profile"] = name
        self.save()
        return True

    def load_profile(self, name: str) -> bool:
        if name in DEFAULT_PROFILES:
            preset = DEFAULT_PROFILES[name]
            self.settings.update(preset)
            self.settings["active_profile"] = name
            self.save_immediate()
            return True
        profiles = self.settings.get("profiles", {})
        if name in profiles:
            self.settings.update(profiles[name])
            self.settings["active_profile"] = name
            self.save_immediate()
            return True
        return False
