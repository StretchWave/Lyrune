"""
renderer.py — Abstract base renderer for wallpaper backgrounds.

Defines the common interface that all wallpaper renderers (static, video)
must implement. The manager switches between renderers based on the
selected wallpaper type without knowing renderer internals.
"""

from abc import ABC, abstractmethod
from typing import Optional
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget


class BaseWallpaperRenderer(ABC):
    """
    Abstract base class for wallpaper background renderers.

    Subclasses handle specific media types (static images, video, etc.)
    and render into a target QWidget that is parented into the desktop WorkerW.
    """

    @abstractmethod
    def start(self, target_widget: QWidget, geometry: QRect, source_path: str,
              scaling_mode: str = "fill") -> bool:
        """
        Initializes and starts rendering the wallpaper.

        Args:
            target_widget: The QWidget to render into (parented into desktop WorkerW).
            geometry: The target geometry in physical screen pixels.
            source_path: Path to the wallpaper source file.
            scaling_mode: One of "fill", "fit", "stretch", "center".

        Returns True on success.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stops rendering and releases all resources."""
        ...

    @abstractmethod
    def resize(self, geometry: QRect) -> None:
        """Called when the target geometry changes (monitor resize/DPI change)."""
        ...

    @abstractmethod
    def is_active(self) -> bool:
        """Returns True if the renderer is currently active and rendering."""
        ...

    @abstractmethod
    def get_source_path(self) -> str:
        """Returns the path of the currently loaded source file."""
        ...

    def update_scaling_mode(self, scaling_mode: str) -> None:
        """
        Updates the scaling mode without reloading the source.
        Default implementation does nothing (subclasses override if needed).
        """
        pass
