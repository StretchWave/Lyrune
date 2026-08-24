"""
transform.py — Canonical Wallpaper Coordinate Space and Transformation Pipeline.

Provides a unified, mathematically reversible mapping between logical wallpaper
coordinates and viewport/screen coordinates across all scaling modes (Fill, Fit,
Stretch, Center) for both preview and native desktop renderers.
"""

from typing import Tuple, Optional
from PyQt6.QtCore import QRectF, QSizeF, QPointF


class WallpaperTransform:
    """
    Computes the canonical transformation between logical wallpaper space (0.0 to 1.0)
    and physical viewport coordinates (preview widget or desktop WorkerW).
    """

    def __init__(
        self,
        source_size: QSizeF,
        viewport_size: QSizeF,
        scaling_mode: str = "fill",
        monitor_size: Optional[QSizeF] = None
    ):
        self.source_width = max(1.0, float(source_size.width()))
        self.source_height = max(1.0, float(source_size.height()))
        self.viewport_width = max(1.0, float(viewport_size.width()))
        self.viewport_height = max(1.0, float(viewport_size.height()))
        self.scaling_mode = (scaling_mode or "fill").lower()

        if monitor_size and monitor_size.isValid() and monitor_size.width() > 0 and monitor_size.height() > 0:
            self.monitor_width = float(monitor_size.width())
            self.monitor_height = float(monitor_size.height())
        else:
            self.monitor_width = self.viewport_width
            self.monitor_height = self.viewport_height

        self.content_rect: QRectF = self._calculate_content_rect()

    def _calculate_content_rect(self) -> QRectF:
        sw = self.source_width
        sh = self.source_height
        vw = self.viewport_width
        vh = self.viewport_height
        mw = self.monitor_width
        mh = self.monitor_height

        mode = self.scaling_mode

        if mode == "fit":
            scale = min(vw / sw, vh / sh)
            rw = sw * scale
            rh = sh * scale
            ox = (vw - rw) / 2.0
            oy = (vh - rh) / 2.0
            return QRectF(ox, oy, rw, rh)

        elif mode == "stretch":
            return QRectF(0.0, 0.0, vw, vh)

        elif mode == "center":
            # In center mode, scale source relative to the target display monitor
            scale = min(vw / mw, vh / mh)
            rw = sw * scale
            rh = sh * scale
            ox = (vw - rw) / 2.0
            oy = (vh - rh) / 2.0
            return QRectF(ox, oy, rw, rh)

        else:
            # Default: "fill" (crop to aspect ratio)
            scale = max(vw / sw, vh / sh)
            rw = sw * scale
            rh = sh * scale
            ox = (vw - rw) / 2.0
            oy = (vh - rh) / 2.0
            return QRectF(ox, oy, rw, rh)

    @property
    def reference_dimension(self) -> float:
        """Shorter dimension of the content rectangle for circular object scaling."""
        return min(self.content_rect.width(), self.content_rect.height())

    def logical_to_viewport(self, lx: float, ly: float) -> Tuple[float, float]:
        """Maps normalized logical coordinate (0.0 to 1.0) into viewport pixel coordinates."""
        vx = self.content_rect.left() + lx * self.content_rect.width()
        vy = self.content_rect.top() + ly * self.content_rect.height()
        return vx, vy

    def viewport_to_logical(self, vx: float, vy: float) -> Tuple[float, float]:
        """Maps viewport pixel coordinates back into normalized logical coordinates (0.0 to 1.0)."""
        cw = max(1.0, self.content_rect.width())
        ch = max(1.0, self.content_rect.height())
        lx = (vx - self.content_rect.left()) / cw
        ly = (vy - self.content_rect.top()) / ch
        return lx, ly

    def logical_to_viewport_size(self, logical_size: float) -> float:
        """Converts normalized logical size to pixel diameter."""
        return float(logical_size) * self.reference_dimension

    def viewport_to_logical_size(self, pixel_size: float) -> float:
        """Converts pixel diameter back to normalized logical size."""
        ref = max(1.0, self.reference_dimension)
        return float(pixel_size) / ref

    def get_debug_info(self, lx: float, ly: float, l_size: float) -> dict:
        """Returns transform debug details for validation overlay."""
        vx, vy = self.logical_to_viewport(lx, ly)
        v_size = self.logical_to_viewport_size(l_size)
        return {
            "mode": self.scaling_mode,
            "source_size": (int(self.source_width), int(self.source_height)),
            "viewport_size": (int(self.viewport_width), int(self.viewport_height)),
            "content_rect": (
                round(self.content_rect.x(), 1),
                round(self.content_rect.y(), 1),
                round(self.content_rect.width(), 1),
                round(self.content_rect.height(), 1)
            ),
            "logical": (round(lx, 3), round(ly, 3), round(l_size, 3)),
            "viewport": (round(vx, 1), round(vy, 1), round(v_size, 1))
        }
