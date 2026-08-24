"""
model.py — Wallpaper configuration and media state dataclasses.

Contains the immutable configuration model for the wallpaper system
and a snapshot of the current media state for rendering.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, Dict


class WallpaperOwnershipState(str, Enum):
    """
    Explicit lifecycle states for native Windows wallpaper ownership.
    """
    NATIVE_ORIGINAL = "native_original"   # User's original wallpaper active, Lyrune inactive
    NATIVE_FALLBACK = "native_fallback"   # Neutral fallback applied to native Windows background
    LYRUNE_ACTIVE = "lyrune_active"       # Lyrune WorkerW surface actively rendering over fallback
    RESTORING = "restoring"               # In the process of restoring original wallpaper
    FAILED = "failed"                     # Startup/recovery failed, rolled back to original


@dataclass
class WallpaperConfig:
    """
    Complete wallpaper configuration state.

    All position/size values are normalized to [0.0, 1.0] relative to the
    target monitor dimensions. This ensures resolution-independence between
    the preview editor and the actual desktop renderer.
    """
    enabled: bool = False
    wallpaper_type: str = "static"           # "static" | "video"
    wallpaper_path: str = ""
    scaling_mode: str = "fill"               # "fill" | "fit" | "stretch" | "center"
    display_mode: str = "primary"            # "primary" | "all" | "Monitor 1", etc.

    # Vinyl position & appearance (normalized coordinates)
    vinyl_x: float = 0.78                    # Horizontal center [0.0, 1.0]
    vinyl_y: float = 0.65                    # Vertical center [0.0, 1.0]
    vinyl_size: float = 0.20                 # Diameter as fraction of monitor width
    vinyl_opacity: int = 100                 # 0–100 %
    rotation_speed: float = 12.0             # Seconds per full revolution

    # Metadata display
    show_title: bool = True
    show_artist: bool = True

    # Rotation behavior
    rotate_while_playing: bool = True
    pause_on_music_pause: bool = True

    # Power / performance
    pause_on_battery: bool = False
    pause_on_fullscreen: bool = False

    @classmethod
    def from_settings(cls, settings: dict) -> "WallpaperConfig":
        """Construct a WallpaperConfig from the flat settings dictionary."""
        return cls(
            enabled=settings.get("wallpaper_enabled", False),
            wallpaper_type=settings.get("wallpaper_type", "static"),
            wallpaper_path=settings.get("wallpaper_path", ""),
            scaling_mode=settings.get("wallpaper_scaling_mode", "fill"),
            display_mode=settings.get("wallpaper_display_mode", "primary"),
            vinyl_x=settings.get("wallpaper_vinyl_x", 0.78),
            vinyl_y=settings.get("wallpaper_vinyl_y", 0.65),
            vinyl_size=settings.get("wallpaper_vinyl_size", 0.20),
            vinyl_opacity=settings.get("wallpaper_vinyl_opacity", 100),
            rotation_speed=settings.get("wallpaper_rotation_speed", 12.0),
            show_title=settings.get("wallpaper_show_title", True),
            show_artist=settings.get("wallpaper_show_artist", True),
            rotate_while_playing=settings.get("wallpaper_rotate_while_playing", True),
            pause_on_music_pause=settings.get("wallpaper_pause_on_music_pause", True),
            pause_on_battery=settings.get("wallpaper_pause_on_battery", False),
            pause_on_fullscreen=settings.get("wallpaper_pause_on_fullscreen", False),
        )

    def to_settings(self) -> dict:
        """Flatten this config into the settings dictionary key-value format."""
        return {
            "wallpaper_enabled": self.enabled,
            "wallpaper_type": self.wallpaper_type,
            "wallpaper_path": self.wallpaper_path,
            "wallpaper_scaling_mode": self.scaling_mode,
            "wallpaper_display_mode": self.display_mode,
            "wallpaper_vinyl_x": self.vinyl_x,
            "wallpaper_vinyl_y": self.vinyl_y,
            "wallpaper_vinyl_size": self.vinyl_size,
            "wallpaper_vinyl_opacity": self.vinyl_opacity,
            "wallpaper_rotation_speed": self.rotation_speed,
            "wallpaper_show_title": self.show_title,
            "wallpaper_show_artist": self.show_artist,
            "wallpaper_rotate_while_playing": self.rotate_while_playing,
            "wallpaper_pause_on_music_pause": self.pause_on_music_pause,
            "wallpaper_pause_on_battery": self.pause_on_battery,
            "wallpaper_pause_on_fullscreen": self.pause_on_fullscreen,
        }


@dataclass
class MediaSnapshot:
    """
    Snapshot of the current media playback state for wallpaper rendering.

    This is a lightweight value object used to communicate track identity
    and playback status from the media layer to the wallpaper renderer.
    The album_art field holds decoded QPixmap data (None if unavailable).
    """
    title: str = ""
    artist: str = ""
    album: str = ""
    album_art: Any = None                   # QPixmap | None (typed as Any to avoid import at module level)
    album_art_bytes: Optional[bytes] = None  # Raw thumbnail bytes for cache keying
    status: str = "Unknown"                  # "Playing" | "Paused" | "Stopped" | "Unknown"
    track_id: str = ""                       # "{artist} - {title}" identity key

    @property
    def is_playing(self) -> bool:
        return self.status == "Playing"

    @property
    def has_track(self) -> bool:
        return bool(self.title)

    @property
    def has_art(self) -> bool:
        return self.album_art is not None


@dataclass
class OriginalWallpaperState:
    """
    Captured state of the user's original Windows wallpaper before Lyrune takes over.
    Used to restore the wallpaper when Lyrune's wallpaper mode is disabled or the app exits.
    """
    wallpaper_path: str = ""
    wallpaper_style: int = 0                 # SPI wallpaper style flags
    tile_wallpaper: str = "0"
    per_monitor_wallpapers: Dict[str, str] = field(default_factory=dict)
    captured: bool = False
