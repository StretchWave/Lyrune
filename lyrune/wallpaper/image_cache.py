"""
image_cache.py — Caching for wallpaper images and album artwork.

Provides LRU-evicting caches to prevent redundant image decoding.
All cache access is thread-safe via threading.Lock.
"""

import os
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


def fetch_album_art_online(artist: str, title: str) -> Optional[bytes]:
    """
    Fetches high-resolution album cover artwork from iTunes Search API / Deezer API.
    Used for web browsers (Brave, Chrome, Edge) and media players where Windows GSMTC
    does not provide a direct thumbnail stream.
    Caches results to disk (.lyrics_cache/art_<hash>.jpg).
    """
    if not artist and not title:
        return None

    # Disk cache check
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".lyrics_cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_key = hashlib.md5(f"{artist.lower().strip()} - {title.lower().strip()}".encode('utf-8')).hexdigest()
    disk_path = os.path.join(cache_dir, f"art_{cache_key}.jpg")

    if os.path.isfile(disk_path) and os.path.getsize(disk_path) > 0:
        try:
            with open(disk_path, "rb") as f:
                return f.read()
        except Exception:
            pass

    import urllib.request
    import urllib.parse
    import json

    # 1. Try iTunes Search API
    try:
        clean_artist = artist.split(',')[0].strip()  # If multiple artists, use primary for cleaner query
        clean_title = title.split('(')[0].split('-')[0].strip()
        query = f"{clean_artist} {clean_title}".strip()
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            results = data.get('results', [])
            if results:
                art_url = results[0].get('artworkUrl100', '')
                if art_url:
                    high_res = art_url.replace('100x100bb.jpg', '600x600bb.jpg').replace('100x100', '600x600')
                    with urllib.request.urlopen(urllib.request.Request(high_res, headers={'User-Agent': 'Mozilla/5.0'}), timeout=3.0) as aresp:
                        b = aresp.read()
                        if b:
                            try:
                                with open(disk_path, "wb") as f:
                                    f.write(b)
                            except Exception:
                                pass
                            return b
    except Exception:
        pass

    # 2. Try Deezer API Fallback
    try:
        q = f"{artist} {title}".strip()
        url = f"https://api.deezer.com/search?q={urllib.parse.quote(q)}&limit=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            data_list = data.get('data', [])
            if data_list:
                album = data_list[0].get('album', {})
                art_url = album.get('cover_big') or album.get('cover_medium') or album.get('cover')
                if art_url:
                    with urllib.request.urlopen(urllib.request.Request(art_url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=3.0) as aresp:
                        b = aresp.read()
                        if b:
                            try:
                                with open(disk_path, "wb") as f:
                                    f.write(b)
                            except Exception:
                                pass
                            return b
    except Exception:
        pass

    return None
