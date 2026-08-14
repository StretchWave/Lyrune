"""
base.py — Abstract interface definitions for the Lyrune visualizer system.

Establishes clean contracts for:
  - AudioData: normalized frequency & waveform payloads
  - BaseAudioSource: audio capture and procedural generation pipeline
  - BaseVisualizer: visualizer rendering & animation lifecycle
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from PyQt6.QtCore import QObject, pyqtSignal, QRect
from PyQt6.QtGui import QPainter


@dataclass
class AudioData:
    """Represents a discrete audio frame payload for visualizers."""
    amplitudes: List[float] = field(default_factory=list)  # Normalized [0.0, 1.0] frequency bins
    raw_waveform: Optional[List[float]] = None             # Time-domain waveform samples if available
    energy: float = 0.0                                     # Overall frame RMS energy [0.0, 1.0]
    timestamp: float = 0.0                                  # Frame timestamp in seconds


class BaseAudioSource(QObject):
    """
    Abstract base class for audio data sources.
    Emits `audio_ready(AudioData)` to deliver processed audio frames to the visualizer pipeline.
    """
    audio_ready = pyqtSignal(object)  # Emits AudioData

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

    @abstractmethod
    def start(self) -> None:
        """Starts audio capture or generation."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stops audio capture or generation."""
        pass

    @abstractmethod
    def is_active(self) -> bool:
        """Returns whether the audio source is currently running."""
        pass

    def set_media_info(self, info: Dict[str, Any]) -> None:
        """Notifies the audio source of current media playback state."""
        pass


class BaseVisualizer(ABC):
    """
    Abstract interface for visualizer rendering strategies.
    Future visualizer styles (e.g. WaveformVisualizer, CircularVisualizer, SpectrumVisualizer)
    must implement this interface without modifying the window or audio pipeline.
    """

    @abstractmethod
    def update_audio(self, audio_data: AudioData) -> None:
        """Receives new audio frame data."""
        pass

    @abstractmethod
    def update_media_state(self, status: str, is_running: bool, track_id: str) -> None:
        """
        Responds to media playback lifecycle:
          - Playing: active animation
          - Paused: smooth decay to resting baseline
          - Stopped: smooth decay to 0
          - Track changed: reset / transition state
        """
        pass

    @abstractmethod
    def paint(self, painter: QPainter, rect: QRect) -> None:
        """Paints the visualization inside the given bounding rectangle."""
        pass

    @abstractmethod
    def resize(self, width: int, height: int) -> None:
        """Adapts internal layout and bar/element count to new dimensions."""
        pass

    @abstractmethod
    def set_orientation(self, orientation: str) -> None:
        """Sets rendering orientation: 'BOTTOM', 'TOP', 'LEFT', 'RIGHT'."""
        pass

    @abstractmethod
    def set_style(self, settings: Dict[str, Any]) -> None:
        """Applies user visual settings (colors, opacity, dimensions, smoothing, etc.)."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Resets all internal animation values to zero / resting state."""
        pass
