"""
Lyrune Wallpaper Subsystem.

Provides a desktop-hosted wallpaper renderer with static/live backgrounds
and a rotating vinyl record displaying the current song's album art and metadata.
The wallpaper renders behind Windows desktop icons using the WorkerW technique.
"""

from lyrune.wallpaper.model import WallpaperConfig, MediaSnapshot
from lyrune.wallpaper.manager import WallpaperManager
from lyrune.wallpaper.vinyl_renderer import VinylRenderer
from lyrune.wallpaper.static_renderer import StaticWallpaperRenderer
from lyrune.wallpaper.video_renderer import VideoWallpaperRenderer
from lyrune.wallpaper.windows_host import WindowsDesktopHost
from lyrune.wallpaper.preview_widget import WallpaperPreviewWidget

__all__ = [
    "WallpaperConfig",
    "MediaSnapshot",
    "WallpaperManager",
    "VinylRenderer",
    "StaticWallpaperRenderer",
    "VideoWallpaperRenderer",
    "WindowsDesktopHost",
    "WallpaperPreviewWidget",
]
