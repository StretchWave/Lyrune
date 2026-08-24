"""
manager.py — Wallpaper system coordinator.

Orchestrates the entire wallpaper lifecycle:
  - Desktop host (WorkerW) management
  - Background renderer (static/video) switching
  - Vinyl record animation (time-based rotation)
  - Media state consumption (title, artist, album art, playback status)
  - Monitor change handling
  - Explorer restart recovery
  - Clean shutdown and wallpaper restoration

Follows the VisualizerManager pattern from lyrune.visualizer.
"""

import os
import sys
import time
from typing import Optional, Dict, Any

from PyQt6.QtCore import Qt, QObject, QTimer, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPixmap, QImage
from PyQt6.QtWidgets import QWidget, QApplication

from lyrune.logger import log_event
from lyrune.settings_manager import SettingsManager
from lyrune.wallpaper.model import WallpaperConfig, MediaSnapshot, WallpaperOwnershipState
from lyrune.wallpaper.image_cache import AlbumArtCache, fetch_album_art_online
from lyrune.wallpaper.vinyl_renderer import VinylRenderer
from lyrune.wallpaper.static_renderer import StaticWallpaperRenderer
from lyrune.wallpaper.monitor import get_monitor_by_name, MonitorInfo


class WallpaperCanvas(QWidget):
    """
    The Qt widget that is embedded into the desktop WorkerW.

    For static wallpapers, this widget renders the background + vinyl
    via paintEvent. For video wallpapers, this widget serves as the
    mpv render target; the vinyl overlay is composited on top.
    """

    def __init__(self, manager: "WallpaperManager", parent=None):
        super().__init__(parent)
        self._manager = manager
        self._paint_count = 0
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        """TEST D: Pure solid MAGENTA (#FF00FF) fill on entire canvas to isolate rendering path."""
        self._paint_count += 1
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#FF00FF"))  # Solid bright MAGENTA
        painter.end()

        if self._paint_count <= 5 or self._paint_count % 300 == 1:
            log_event(
                f"[Wallpaper Canvas] TEST D paintEvent #{self._paint_count} | "
                f"Rect: {self.rect().width()}x{self.rect().height()} | "
                f"Painted solid MAGENTA (#FF00FF)"
            )


class WallpaperManager(QObject):
    """
    Master coordinator for the Lyrune wallpaper system.

    Manages the complete lifecycle of desktop wallpaper rendering,
    vinyl animation, and media state tracking.
    """
    wallpaper_state_changed = pyqtSignal(bool)  # enabled/disabled
    _art_fetched_signal = pyqtSignal(str, bytes)  # (track_id, art_bytes)

    def __init__(self, settings_manager: SettingsManager, parent=None):
        super().__init__(parent)
        self.settings_mgr = settings_manager
        self._art_fetched_signal.connect(self._on_online_art_fetched)

        # Configuration
        self._config = WallpaperConfig.from_settings(settings_manager.settings)

        # Components
        self._host = None                    # WindowsDesktopHost (lazy init)
        self._canvas: Optional[WallpaperCanvas] = None
        self._native_surface = None          # NativeDesktopProbe (pure Win32 surface)
        self._active_renderer = None         # BaseWallpaperRenderer
        self._vinyl_renderer = VinylRenderer()
        self._album_art_cache = AlbumArtCache(max_entries=10)

        # Media state
        self._media = MediaSnapshot()
        self._last_track_id: str = ""
        self._grace_timer: float = 0.0       # Grace period for media transitions
        self._grace_duration: float = 0.8    # 800ms grace before clearing state

        # Rotation animation state
        self._rotation_angle: float = 0.0
        self._rotation_base_time: float = 0.0
        self._rotation_base_angle: float = 0.0
        self._is_rotating: bool = False

        # Rendering flags
        self._use_static_paint: bool = True  # True for static, False for video
        self._use_video_mode: bool = False

        # Monitor info
        self._current_monitor: Optional[MonitorInfo] = None
        self._monitor_geometry: QRect = QRect()

        # Animation timer (30 FPS for vinyl rotation + composition)
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(33)  # ~30 FPS
        self._render_timer.timeout.connect(self._on_render_tick)

        # Host validation timer (5s for explorer restart detection)
        self._host_check_timer = QTimer(self)
        self._host_check_timer.setInterval(5000)
        self._host_check_timer.timeout.connect(self._on_host_check)

        # Connect to screen changes
        app = QApplication.instance()
        if app:
            app.screenAdded.connect(self._on_screen_changed)
            app.screenRemoved.connect(self._on_screen_changed)

        log_event("[WallpaperManager] Initialized.")

    # === Public API ===

    def apply_config(self, settings: dict) -> None:
        """
        Applies a new wallpaper configuration from settings.
        Called when the user clicks Apply in the settings dialog.
        """
        new_config = WallpaperConfig.from_settings(settings)

        was_enabled = self._config.enabled
        self._config = new_config

        if new_config.enabled and not was_enabled:
            self.start()
        elif not new_config.enabled and was_enabled:
            self.stop()
        elif new_config.enabled:
            # Update the running wallpaper
            self._update_wallpaper()

        self.wallpaper_state_changed.emit(new_config.enabled)

    def start(self) -> bool:
        """
        Starts the desktop wallpaper system using the proven native Win32 host surface
        driven by QPainter QImage rendering.
        """
        if sys.platform != "win32":
            log_event("[WallpaperManager] Wallpaper is only supported on Windows.")
            return False

        if not self._config.enabled:
            return False

        log_event("[WallpaperManager] Starting native desktop wallpaper surface...")

        from lyrune.wallpaper.win32_probe import NativeDesktopProbe
        self._native_surface = NativeDesktopProbe()
        if not self._native_surface.start():
            log_event("[WallpaperManager] Failed to start native desktop host surface.")
            return False

        # Resolve target monitor physical surface geometry
        surf_w, surf_h = self._native_surface.get_surface_size()
        self._monitor_geometry = QRect(0, 0, surf_w, surf_h)
        log_event(f"[WallpaperManager] Physical wallpaper surface size: {surf_w}x{surf_h}")

        # Initialize background renderer
        self._start_renderer()

        # Start render & host validation timers
        self._render_timer.start(33)
        self._host_check_timer.start()

        # Initial frame render
        self._on_render_tick()

        log_event("[WallpaperManager] Native desktop wallpaper surface active.")
        return True

    def stop(self) -> None:
        """
        Stops the wallpaper system.
        """
        log_event("[WallpaperManager] Stopping wallpaper system...")

        # Stop timers
        self._render_timer.stop()
        self._host_check_timer.stop()

        # Clean up native surface
        if getattr(self, "_native_surface", None):
            self._native_surface.stop()
            self._native_surface = None

        log_event("[WallpaperManager] Wallpaper system stopped.")
        self.wallpaper_state_changed.emit(False)

    def shutdown(self) -> None:
        """
        Complete shutdown — called when Lyrune exits.
        Stops everything and restores the original wallpaper.
        """
        self.stop()
        self._album_art_cache.clear()
        log_event("[WallpaperManager] Full shutdown complete.")

    def update_media_state(self, info: dict) -> None:
        """
        Called from the main polling loop with the latest media info.
        Updates vinyl rendering state (track, art, playback status).
        """
        title = info.get('title', '') or ''
        artist = info.get('artist', '') or ''
        status = info.get('status', 'Unknown')
        album = info.get('album', '') or ''
        art_bytes = info.get('album_art_bytes')

        track_id = f"{artist} - {title}" if title else ""

        # Grace period: don't clear state immediately on empty media
        if not title and self._media.has_track:
            now = time.monotonic()
            if self._grace_timer == 0.0:
                self._grace_timer = now
            elif now - self._grace_timer < self._grace_duration:
                return  # Still in grace period, keep current state
            # Grace period expired — clear state
            self._grace_timer = 0.0
        else:
            self._grace_timer = 0.0

        # Track change detection
        if track_id != self._last_track_id and track_id:
            self._last_track_id = track_id
            self._media.title = title
            self._media.artist = artist
            self._media.album = album
            self._media.track_id = track_id
            log_event(f"[WallpaperManager] Track changed: '{artist} - {title}'")

            # Reset art immediately for new track
            if art_bytes:
                pixmap = self._album_art_cache.decode_and_cache(art_bytes)
                if pixmap:
                    self._media.album_art = pixmap
                    self._media.album_art_bytes = art_bytes
                    self._vinyl_renderer.set_album_art(pixmap)
                else:
                    self._fetch_art_async(track_id, artist, title)
            else:
                self._fetch_art_async(track_id, artist, title)
        elif track_id == self._last_track_id and track_id:
            if art_bytes and art_bytes != self._media.album_art_bytes:
                pixmap = self._album_art_cache.decode_and_cache(art_bytes)
                if pixmap:
                    self._media.album_art = pixmap
                    self._media.album_art_bytes = art_bytes
                    self._vinyl_renderer.set_album_art(pixmap)
            elif not self._media.album_art:
                self._fetch_art_async(track_id, artist, title)

        # Update playback status
        old_status = self._media.status
        self._media.status = status

        if not track_id:
            self._media.title = ""
            self._media.artist = ""
            self._media.album = ""
            self._media.track_id = ""

        # Handle rotation state changes
        if self._config.rotate_while_playing:
            if status == "Playing" and not self._is_rotating:
                self._start_rotation()
            elif status != "Playing" and self._is_rotating and self._config.pause_on_music_pause:
                self._pause_rotation()

    def _fetch_art_async(self, track_id: str, artist: str, title: str) -> None:
        """Fetches high-resolution album artwork in the background if GSMTC provided none."""
        if not artist or not title:
            return

        import threading
        def _worker():
            art = fetch_album_art_online(artist, title)
            if art:
                self._art_fetched_signal.emit(track_id, art)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_online_art_fetched(self, track_id: str, art_bytes: bytes) -> None:
        """Called on main thread when online album art is ready."""
        if not art_bytes:
            return
        curr_id = f"{self._media.artist} - {self._media.title}".strip()
        if curr_id != track_id and self._media.track_id != track_id:
            return
        pixmap = self._album_art_cache.decode_and_cache(art_bytes)
        if pixmap:
            self._media.album_art = pixmap
            self._media.album_art_bytes = art_bytes
            self._vinyl_renderer.set_album_art(pixmap)
            log_event(f"[WallpaperManager] Online album art loaded for '{track_id}' ({len(art_bytes)} bytes)")

    def get_config(self) -> WallpaperConfig:
        """Returns the current wallpaper configuration."""
        return self._config

    def get_media(self) -> MediaSnapshot:
        """Returns the current media snapshot."""
        return self._media

    def is_active(self) -> bool:
        """Returns True if the wallpaper is currently rendering."""
        return (self._config.enabled and
                self._native_surface is not None)

    # === Internal Rendering ===

    def _start_renderer(self) -> None:
        """Starts the appropriate background renderer based on config."""
        # Stop existing renderer
        if self._active_renderer:
            self._active_renderer.stop()
            self._active_renderer = None

        path = self._config.wallpaper_path
        if not path or not os.path.isfile(path):
            log_event(f"[WallpaperManager] No valid wallpaper file: '{path}'")
            self._use_static_paint = True
            self._use_video_mode = False
            return

        if self._config.wallpaper_type == "video":
            self._start_video_renderer(path)
        else:
            self._start_static_renderer(path)

    def _start_static_renderer(self, path: str) -> None:
        """Initializes the static image renderer."""
        renderer = StaticWallpaperRenderer()
        success = renderer.start(
            self._canvas, self._monitor_geometry, path,
            self._config.scaling_mode
        )
        if success:
            self._active_renderer = renderer
            self._use_static_paint = True
            self._use_video_mode = False
        else:
            log_event(f"[WallpaperManager] Static renderer failed for: '{path}'")

    def _start_video_renderer(self, path: str) -> None:
        """Initializes the video renderer."""
        from lyrune.wallpaper.video_renderer import VideoWallpaperRenderer
        renderer = VideoWallpaperRenderer()
        success = renderer.start(
            self._canvas, self._monitor_geometry, path,
            self._config.scaling_mode
        )
        if success:
            self._active_renderer = renderer
            self._use_static_paint = False
            self._use_video_mode = True
        else:
            log_event(f"[WallpaperManager] Video renderer failed for: '{path}'")
            # Fall back to static if video fails
            self._use_static_paint = True
            self._use_video_mode = False

    def _update_wallpaper(self) -> None:
        """Updates the running wallpaper with current config (without full restart)."""
        if not self.is_active():
            return

        # Check if source changed
        current_source = self._active_renderer.get_source_path() if self._active_renderer else ""
        if current_source != self._config.wallpaper_path or (
                self._active_renderer and
                self._config.wallpaper_type == "video" and self._use_static_paint
        ) or (
                self._active_renderer and
                self._config.wallpaper_type == "static" and self._use_video_mode
        ):
            self._start_renderer()
        elif self._active_renderer:
            self._active_renderer.update_scaling_mode(self._config.scaling_mode)

        # Update monitor if changed
        monitor = get_monitor_by_name(self._config.display_mode)
        if monitor and monitor.geometry != self._monitor_geometry:
            self._monitor_geometry = monitor.geometry
            self._current_monitor = monitor
            if self._canvas:
                self._canvas.setFixedSize(
                    self._monitor_geometry.width(),
                    self._monitor_geometry.height()
                )
            if self._host:
                self._host.resize_widget(self._monitor_geometry)
            if self._active_renderer:
                self._active_renderer.resize(self._monitor_geometry)

        # Force repaint
        if self._canvas:
            self._canvas.update()

    def _paint_vinyl(self, painter: QPainter, canvas_rect: QRect) -> None:
        """Paints the vinyl overlay on the wallpaper canvas using WallpaperTransform."""
        w = canvas_rect.width()
        h = canvas_rect.height()

        from lyrune.wallpaper.transform import WallpaperTransform
        from PyQt6.QtCore import QSizeF

        src_w = 16.0
        src_h = 9.0
        if self._active_renderer and hasattr(self._active_renderer, "_cached_pixmap") and self._active_renderer._cached_pixmap:
            pix = self._active_renderer._cached_pixmap
            if not pix.isNull():
                src_w = float(pix.width())
                src_h = float(pix.height())

        transform = WallpaperTransform(QSizeF(src_w, src_h), QSizeF(w, h), self._config.scaling_mode)
        center_x, center_y = transform.logical_to_viewport(self._config.vinyl_x, self._config.vinyl_y)
        diameter = transform.logical_to_viewport_size(self._config.vinyl_size)

        self._vinyl_renderer.render(
            painter,
            center_x, center_y,
            diameter,
            self._rotation_angle,
            self._config.vinyl_opacity,
            self._config,
            self._media,
        )

    # === Animation ===

    def _on_render_tick(self) -> None:
        """30 FPS render tick — renders wallpaper + vinyl using QPainter into QImage and blits to native surface."""
        if not self._native_surface:
            return

        now = time.monotonic()
        dt = 1.0 / 30.0

        # Update rotation (time-based)
        if self._is_rotating and self._config.rotation_speed > 0:
            elapsed = now - self._rotation_base_time
            self._rotation_angle = (
                self._rotation_base_angle +
                elapsed * (360.0 / self._config.rotation_speed)
            ) % 360.0

        # Advance crossfade
        self._vinyl_renderer.advance_crossfade(dt)

        w, h = self._native_surface.get_surface_size()
        rect = QRect(0, 0, w, h)

        img = QImage(w, h, QImage.Format.Format_RGB32)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 1. Background static wallpaper
        if self._active_renderer and self._use_static_paint:
            self._active_renderer.paint(painter, rect)
        else:
            painter.fillRect(rect, QColor(0, 0, 0))

        # 2. Vinyl record overlay via canonical WallpaperTransform
        from lyrune.wallpaper.transform import WallpaperTransform
        from PyQt6.QtCore import QSizeF

        src_w = 16.0
        src_h = 9.0
        if self._active_renderer and hasattr(self._active_renderer, "_cached_pixmap") and self._active_renderer._cached_pixmap:
            pix = self._active_renderer._cached_pixmap
            if not pix.isNull():
                src_w = float(pix.width())
                src_h = float(pix.height())

        transform = WallpaperTransform(QSizeF(src_w, src_h), QSizeF(w, h), self._config.scaling_mode)
        center_x, center_y = transform.logical_to_viewport(self._config.vinyl_x, self._config.vinyl_y)
        diameter = transform.logical_to_viewport_size(self._config.vinyl_size)

        self._vinyl_renderer.render(
            painter,
            center_x, center_y,
            diameter,
            self._rotation_angle,
            self._config.vinyl_opacity,
            self._config,
            self._media,
        )

        painter.end()

        # Transfer frame to proven native desktop host surface
        self._native_surface.render_image(img)

    def _start_rotation(self) -> None:
        """Starts vinyl rotation from the current angle."""
        self._rotation_base_time = time.monotonic()
        self._rotation_base_angle = self._rotation_angle
        self._is_rotating = True

    def _pause_rotation(self) -> None:
        """Pauses vinyl rotation, preserving the current angle."""
        self._is_rotating = False

    # === Recovery ===

    def _on_host_check(self) -> None:
        """Periodic host validation for explorer restart recovery."""
        if not self._config.enabled or not self._host:
            return

        if not self._host.is_host_valid():
            log_event("[WallpaperManager] Desktop host invalid — attempting recovery...")
            self._attempt_recovery()

    def _attempt_recovery(self) -> None:
        """Attempts to recover the wallpaper after explorer restart."""
        try:
            log_event("[WallpaperManager] Attempting recovery after shell change...")
            saved_angle = self._rotation_angle
            saved_media = self._media

            # Stop timers temporarily
            self._render_timer.stop()
            self._host_check_timer.stop()

            # Stop renderer
            if self._active_renderer:
                self._active_renderer.stop()
                self._active_renderer = None

            # Clean up old canvas
            if self._canvas:
                self._canvas.hide()
                self._canvas.setParent(None)
                self._canvas.deleteLater()
                self._canvas = None

            # Keep existing captured original wallpaper if host exists
            orig_wallpaper = self._host._original_wallpaper if self._host else None

            from lyrune.wallpaper.windows_host import WindowsDesktopHost
            self._host = WindowsDesktopHost()
            if orig_wallpaper and orig_wallpaper.captured:
                self._host._original_wallpaper = orig_wallpaper

            # Re-apply fallback and setup WorkerW
            if not self._host.setup_with_fallback():
                log_event("[WallpaperManager] Recovery failed: could not setup desktop host.")
                self._host_check_timer.start()
                return

            # Recreate canvas
            self._canvas = WallpaperCanvas(self)
            self._canvas.setFixedSize(self._monitor_geometry.width(),
                                      self._monitor_geometry.height())
            self._canvas.show()

            if not self._host.embed_widget(self._canvas, self._monitor_geometry):
                log_event("[WallpaperManager] Recovery failed: could not embed canvas.")
                self._host.detach_and_restore()
                self._host_check_timer.start()
                return

            # Restart renderer
            self._start_renderer()
            self._host.set_state(WallpaperOwnershipState.LYRUNE_ACTIVE)

            # Restore state
            self._rotation_angle = saved_angle
            self._rotation_base_angle = saved_angle
            self._rotation_base_time = time.monotonic()
            self._media = saved_media

            # Restore album art
            if saved_media.album_art:
                self._vinyl_renderer.set_album_art(saved_media.album_art)

            # Restart timers
            self._render_timer.start()
            self._host_check_timer.start()

            log_event("[WallpaperManager] Recovery successful — wallpaper restored.")

        except Exception as e:
            log_event(f"[WallpaperManager] Recovery failed with exception: {e}")
            self._host_check_timer.start()

    def _on_screen_changed(self, screen=None) -> None:
        """Handles monitor connect/disconnect/change events."""
        if not self._config.enabled:
            return

        log_event("[WallpaperManager] Screen configuration changed — reconfiguring...")

        # Re-resolve monitor
        new_monitor = get_monitor_by_name(self._config.display_mode)
        if new_monitor and new_monitor.geometry != self._monitor_geometry:
            self._monitor_geometry = new_monitor.geometry
            self._current_monitor = new_monitor

            if self._canvas:
                self._canvas.setFixedSize(
                    self._monitor_geometry.width(),
                    self._monitor_geometry.height()
                )
            if self._host:
                self._host.resize_widget(self._monitor_geometry)
            if self._active_renderer:
                self._active_renderer.resize(self._monitor_geometry)

            log_event(
                f"[WallpaperManager] Monitor updated: "
                f"{self._monitor_geometry.width()}x{self._monitor_geometry.height()}"
            )
