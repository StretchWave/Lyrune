"""
video_renderer.py — Live video wallpaper renderer using libmpv.

Plays a video file as the desktop wallpaper background using the mpv
media player library. The video is rendered directly into the wallpaper
widget's HWND for hardware-accelerated playback.

Requirements:
  - python-mpv (pip install python-mpv)
  - mpv-2.dll or libmpv-2.dll accessible on PATH or in the app directory
"""

import os
import sys
from typing import Optional
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from lyrune.wallpaper.renderer import BaseWallpaperRenderer
from lyrune.logger import log_event

# Supported video extensions
SUPPORTED_VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mkv', '.avi', '.mov'}

# Try to import mpv
HAS_MPV = False
try:
    import mpv
    HAS_MPV = True
except ImportError:
    pass
except Exception as e:
    log_event(f"[Video Renderer] mpv import error: {e}")


def is_supported_video(path: str) -> bool:
    """Returns True if the file extension is a supported video format."""
    if not path:
        return False
    _, ext = os.path.splitext(path)
    return ext.lower() in SUPPORTED_VIDEO_EXTENSIONS


class VideoWallpaperRenderer(BaseWallpaperRenderer):
    """
    Renders a video file as a live desktop wallpaper using libmpv.

    The video is:
    - Rendered directly into a target HWND (the wallpaper widget)
    - Looped infinitely
    - Muted by default
    - Hardware-accelerated where possible
    """

    def __init__(self):
        self._player: Optional[object] = None  # mpv.MPV instance
        self._source_path: str = ""
        self._target_widget: Optional[QWidget] = None
        self._geometry: QRect = QRect()
        self._active: bool = False
        self._target_hwnd: int = 0

    def start(self, target_widget: QWidget, geometry: QRect, source_path: str,
              scaling_mode: str = "fill") -> bool:
        """
        Initializes mpv and starts video playback into the target widget.
        """
        if not HAS_MPV:
            log_event("[Video Renderer] python-mpv is not installed. Cannot start live wallpaper.")
            return False

        if not source_path or not os.path.isfile(source_path):
            log_event(f"[Video Renderer] Source file not found: '{source_path}'")
            return False

        if not is_supported_video(source_path):
            log_event(f"[Video Renderer] Unsupported format: '{source_path}'")
            return False

        # Stop any existing playback
        self.stop()

        self._source_path = source_path
        self._target_widget = target_widget
        self._geometry = geometry

        try:
            # Ensure the widget has a valid HWND
            if not target_widget.winId():
                target_widget.show()

            self._target_hwnd = int(target_widget.winId())
            if not self._target_hwnd:
                log_event("[Video Renderer] Target widget has no HWND.")
                return False

            # Create mpv player instance
            self._player = mpv.MPV(
                wid=str(self._target_hwnd),
                log_handler=self._mpv_log_handler,
                loglevel='warn',
            )

            # Configure playback options
            self._player['loop-file'] = 'inf'        # Loop forever
            self._player['mute'] = True               # No audio from wallpaper
            self._player['hwdec'] = 'auto-safe'       # HW accel with safe fallback
            self._player['vo'] = 'gpu'                 # GPU video output
            self._player['gpu-context'] = 'win'        # Windows GPU context
            self._player['keepaspect'] = True
            self._player['keepaspect-window'] = False
            self._player['input-default-bindings'] = False
            self._player['input-vo-keyboard'] = False
            self._player['osc'] = False                # No on-screen controls
            self._player['osd-level'] = 0              # No OSD
            self._player['cursor-autohide'] = 'always'
            self._player['force-window'] = False

            # Panscan for fill mode (crop to fill)
            if scaling_mode == "fill":
                self._player['panscan'] = 1.0
            elif scaling_mode == "fit":
                self._player['panscan'] = 0.0
            elif scaling_mode == "stretch":
                self._player['keepaspect'] = False

            # Start playback
            self._player.play(source_path)
            self._active = True

            log_event(
                f"[Video Renderer] Started: '{os.path.basename(source_path)}' "
                f"(hwdec=auto-safe, loop=inf, mute=yes)"
            )
            return True

        except Exception as e:
            log_event(f"[Video Renderer] Start failed: {e}")
            self._cleanup_player()
            return False

    def stop(self) -> None:
        """Stops video playback and releases mpv resources."""
        self._active = False
        self._cleanup_player()
        self._source_path = ""
        log_event("[Video Renderer] Stopped.")

    def _cleanup_player(self) -> None:
        """Safely destroys the mpv player instance."""
        if self._player is not None:
            try:
                self._player.terminate()
            except Exception as e:
                log_event(f"[Video Renderer] Cleanup warning: {e}")
            finally:
                self._player = None

    def resize(self, geometry: QRect) -> None:
        """
        Called when the target geometry changes.
        mpv auto-resizes to its parent HWND, but we may need to update
        the widget geometry via the host.
        """
        self._geometry = geometry
        # mpv automatically fills its wid target — no explicit resize needed

    def is_active(self) -> bool:
        return self._active and self._player is not None

    def get_source_path(self) -> str:
        return self._source_path

    def update_scaling_mode(self, scaling_mode: str) -> None:
        """Updates the scaling mode on the live mpv player."""
        if not self._player:
            return
        try:
            if scaling_mode == "fill":
                self._player['panscan'] = 1.0
                self._player['keepaspect'] = True
            elif scaling_mode == "fit":
                self._player['panscan'] = 0.0
                self._player['keepaspect'] = True
            elif scaling_mode == "stretch":
                self._player['keepaspect'] = False
                self._player['panscan'] = 0.0
            elif scaling_mode == "center":
                self._player['keepaspect'] = True
                self._player['panscan'] = 0.0
        except Exception as e:
            log_event(f"[Video Renderer] Scaling mode update error: {e}")

    def _mpv_log_handler(self, loglevel: str, component: str, message: str) -> None:
        """Handles mpv log messages, routing errors to Lyrune's logger."""
        if loglevel in ('error', 'fatal'):
            log_event(f"[mpv {loglevel}] [{component}] {message}")
        elif loglevel == 'warn':
            log_event(f"[mpv warn] [{component}] {message}")

    def paint(self, painter, rect: QRect) -> None:
        """
        No-op for video renderer. mpv paints directly into the HWND;
        the QPainter is only used for the vinyl overlay layer.
        """
        pass
