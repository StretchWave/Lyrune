"""
image_cache.py — Caching for wallpaper images and album artwork.

Provides LRU-evicting caches to prevent redundant image decoding.
All cache access is thread-safe via threading.Lock.
"""

import hashlib
import threading
from collections import OrderedDict
from typing import Optional, Tuple
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import QRect, Qt

from lyrune.logger import log_event


class WallpaperImageCache:
    """
    Caches scaled wallpaper images keyed by (path, width, height, scaling_mode).
    Uses LRU eviction to bound memory usage.
    """

    def __init__(self, max_entries: int = 5):
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def _make_key(self, path: str, width: int, height: int, scaling_mode: str) -> str:
        return f"{path}|{width}x{height}|{scaling_mode}"

    def get(self, path: str, width: int, height: int, scaling_mode: str) -> Optional[QPixmap]:
        """Returns a cached scaled pixmap, or None if not cached."""
        key = self._make_key(path, width, height, scaling_mode)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, path: str, width: int, height: int, scaling_mode: str,
            pixmap: QPixmap) -> None:
        """Stores a scaled pixmap in the cache."""
        key = self._make_key(path, width, height, scaling_mode)
        with self._lock:
            self._cache[key] = pixmap
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_entries:
                evicted_key, _ = self._cache.popitem(last=False)
                log_event(f"[ImageCache] Evicted wallpaper cache entry: {evicted_key[:60]}...")

    def invalidate(self, path: str = "") -> None:
        """Invalidates cache entries for the given path, or all entries if empty."""
        with self._lock:
            if not path:
                self._cache.clear()
            else:
                keys_to_remove = [k for k in self._cache if k.startswith(f"{path}|")]
                for k in keys_to_remove:
                    del self._cache[k]

    def clear(self) -> None:
        """Clears the entire cache."""
        with self._lock:
            self._cache.clear()


class AlbumArtCache:
    """
    Caches decoded album artwork QPixmaps keyed by a hash of the raw bytes.
    Prevents redundant decoding when the same artwork is received repeatedly.
    """

    def __init__(self, max_entries: int = 10):
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._max_entries = max_entries
        self._lock = threading.Lock()

    @staticmethod
    def _hash_bytes(data: bytes) -> str:
        return hashlib.md5(data).hexdigest()

    def get(self, art_bytes: bytes) -> Optional[QPixmap]:
        """Returns a cached QPixmap for the given art bytes, or None."""
        if not art_bytes:
            return None
        key = self._hash_bytes(art_bytes)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, art_bytes: bytes, pixmap: QPixmap) -> None:
        """Stores a decoded QPixmap for the given art bytes."""
        if not art_bytes:
            return
        key = self._hash_bytes(art_bytes)
        with self._lock:
            self._cache[key] = pixmap
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)

    def decode_and_cache(self, art_bytes: bytes) -> Optional[QPixmap]:
        """
        Decodes raw image bytes to QPixmap and caches the result.
        Returns None if decoding fails.
        """
        if not art_bytes:
            return None

        # Check cache first
        cached = self.get(art_bytes)
        if cached is not None:
            return cached

        # Decode
        try:
            image = QImage()
            if image.loadFromData(art_bytes):
                pixmap = QPixmap.fromImage(image)
                if not pixmap.isNull():
                    self.put(art_bytes, pixmap)
                    return pixmap
        except Exception as e:
            log_event(f"[AlbumArtCache] Decode failed: {e}")

        return None

    def clear(self) -> None:
        """Clears the entire cache."""
        with self._lock:
            self._cache.clear()


def scale_image_to_mode(source: QPixmap, target_width: int, target_height: int,
                        mode: str = "fill") -> QPixmap:
    """
    Scales a source QPixmap to the target dimensions using the specified mode.

    Modes:
    - "fill": Cover entire target, crop overflow (preserve aspect ratio).
    - "fit": Show entire image within target, letterbox (preserve aspect ratio).
    - "stretch": Stretch to fill exactly (ignore aspect ratio).
    - "center": Display at native size, centered on a black background.

    Returns a new QPixmap of exactly (target_width, target_height).
    """
    from PyQt6.QtGui import QPainter, QColor

    result = QPixmap(target_width, target_height)
    result.fill(QColor(0, 0, 0))  # Black background for letterboxing/center

    if source.isNull():
        return result

    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    src_w = source.width()
    src_h = source.height()

    if mode == "stretch":
        # Stretch to fill, ignoring aspect ratio
        painter.drawPixmap(0, 0, target_width, target_height, source)

    elif mode == "center":
        # Native size, centered
        x = (target_width - src_w) // 2
        y = (target_height - src_h) // 2
        painter.drawPixmap(x, y, source)

    elif mode == "fit":
        # Fit entire image, letterbox
        scale = min(target_width / src_w, target_height / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        x = (target_width - new_w) // 2
        y = (target_height - new_h) // 2
        scaled = source.scaled(new_w, new_h, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(x, y, scaled)

    else:  # "fill" (default)
        # Cover entire target, crop overflow
        scale = max(target_width / src_w, target_height / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        x = (target_width - new_w) // 2
        y = (target_height - new_h) // 2
        scaled = source.scaled(new_w, new_h, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(x, y, scaled)

    painter.end()
    return result
