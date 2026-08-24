"""
static_renderer.py — Static image wallpaper renderer.

Loads and displays a static image (PNG, JPG, JPEG, WebP, BMP) as
the desktop wallpaper background with configurable scaling modes.
"""

import os
from typing import Optional
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QWidget

from lyrune.wallpaper.renderer import BaseWallpaperRenderer
from lyrune.wallpaper.image_cache import WallpaperImageCache, scale_image_to_mode
from lyrune.logger import log_event

# Supported static image extensions
SUPPORTED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}


def is_supported_image(path: str) -> bool:
    """Returns True if the file extension is a supported static image format."""
    if not path:
        return False
    _, ext = os.path.splitext(path)
    return ext.lower() in SUPPORTED_IMAGE_EXTENSIONS


class StaticWallpaperRenderer(BaseWallpaperRenderer):
    """
    Renders a static image as the desktop wallpaper background.

    The image is loaded once, scaled to the target geometry with the
    selected scaling mode, cached, and painted onto the target widget.
    Re-rendering only occurs when the source, geometry, or scaling mode changes.
    """

    def __init__(self):
        self._source_path: str = ""
        self._scaling_mode: str = "fill"
        self._target_widget: Optional[QWidget] = None
        self._geometry: QRect = QRect()
        self._cached_pixmap: Optional[QPixmap] = None
        self._image_cache = WallpaperImageCache(max_entries=3)
        self._active: bool = False

    def start(self, target_widget: QWidget, geometry: QRect, source_path: str,
              scaling_mode: str = "fill") -> bool:
        """
        Loads the image and renders it onto the target widget.
        """
        if not source_path or not os.path.isfile(source_path):
            log_event(f"[Static Renderer] Source file not found: '{source_path}'")
            return False

        if not is_supported_image(source_path):
            log_event(f"[Static Renderer] Unsupported format: '{source_path}'")
            return False

        self._source_path = source_path
        self._scaling_mode = scaling_mode
        self._target_widget = target_widget
        self._geometry = geometry

        success = self._render()
        if success:
            self._active = True
            log_event(
                f"[Static Renderer] Started: '{os.path.basename(source_path)}' "
                f"({geometry.width()}x{geometry.height()}, mode={scaling_mode})"
            )
        return success

    def stop(self) -> None:
        """Stops rendering and clears the cached pixmap."""
        self._active = False
        self._cached_pixmap = None
        self._source_path = ""
        if self._target_widget:
            self._target_widget.update()
        log_event("[Static Renderer] Stopped.")

    def resize(self, geometry: QRect) -> None:
        """Re-renders the image for the new geometry."""
        if not self._active or geometry == self._geometry:
            return
        self._geometry = geometry
        self._render()

    def is_active(self) -> bool:
        return self._active

    def get_source_path(self) -> str:
        return self._source_path

    def update_scaling_mode(self, scaling_mode: str) -> None:
        """Changes the scaling mode and re-renders."""
        if scaling_mode == self._scaling_mode:
            return
        self._scaling_mode = scaling_mode
        if self._active:
            self._render()

    def get_rendered_pixmap(self) -> Optional[QPixmap]:
        """Returns the current rendered wallpaper pixmap (for composition)."""
        return self._cached_pixmap

    def _render(self) -> bool:
        """
        Loads the source image, applies scaling, and caches the result.
        Returns True on success.
        """
        if not self._source_path or not self._geometry.width() or not self._geometry.height():
            return False

        w = self._geometry.width()
        h = self._geometry.height()

        # Check cache first
        cached = self._image_cache.get(self._source_path, w, h, self._scaling_mode)
        if cached is not None:
            self._cached_pixmap = cached
            if self._target_widget:
                self._target_widget.update()
            return True

        # Load source image
        source = QPixmap(self._source_path)
        if source.isNull():
            log_event(f"[Static Renderer] Failed to load image: '{self._source_path}'")
            return False

        # Scale to target geometry
        scaled = scale_image_to_mode(source, w, h, self._scaling_mode)
        self._cached_pixmap = scaled
        self._image_cache.put(self._source_path, w, h, self._scaling_mode, scaled)

        if self._target_widget:
            self._target_widget.update()

        return True

    def paint(self, painter: QPainter, rect: QRect) -> None:
        """
        Paints the cached wallpaper pixmap onto the given painter.
        Fills the exact target rect in full physical pixel resolution.
        """
        if self._cached_pixmap and not self._cached_pixmap.isNull():
            if self._geometry.size() != rect.size():
                self._geometry = rect
                self._render()
            painter.drawPixmap(rect, self._cached_pixmap)
        else:
            # Fallback: black background
            painter.fillRect(rect, QColor(0, 0, 0))
