import sys
import time
import threading
from collections import deque
from PyQt6.QtCore import QObject, pyqtSignal


class AppLogger(QObject):
    """
    Thread-safe singleton logger for Lyrune.

    Features:
      - Thread-safe singleton via threading.Lock (fixes TOCTOU race).
      - Duplicate message throttling: suppresses identical messages within a
        configurable time window to prevent 20 Hz polling loops from flooding
        the log console.
      - Safe Windows console encoding (cp1252/utf-8) without UnicodeEncodeError.
      - Rolling history buffer (500 entries) for instant Live Logs display.
    """
    log_signal = pyqtSignal(str, str)  # (timestamp, message)

    _instance = None
    _lock = threading.RLock()

    # Throttle: suppress duplicate messages within this window (seconds)
    THROTTLE_WINDOW = 1.0

    def __init__(self):
        super().__init__()
        self.history: deque = deque(maxlen=500)
        self._last_message: str = ""
        self._last_message_time: float = 0.0
        self._suppressed_count: int = 0
        self._seen_keys: set = set()

    @classmethod
    def instance(cls) -> "AppLogger":
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking
                if cls._instance is None:
                    cls._instance = AppLogger()
        return cls._instance

    def log(self, message: str, force: bool = False) -> None:
        """
        Log a message. Duplicate messages within THROTTLE_WINDOW seconds
        are suppressed and summarized when a new message arrives.
        
        Args:
            force: If True, bypasses throttling entirely.
        """
        now = time.monotonic()
        safe_msg = str(message)

        # Never throttle error/exception messages
        is_critical = any(kw in safe_msg for kw in ('Exception', 'Error', 'CRITICAL', 'Traceback'))

        with self._lock:
            # Throttle duplicate messages (unless forced or critical)
            if not force and not is_critical:
                if safe_msg == self._last_message and (now - self._last_message_time) < self.THROTTLE_WINDOW:
                    self._suppressed_count += 1
                    return

            # If we suppressed duplicates, emit a summary line first
            if self._suppressed_count > 0:
                summary = f"  ... (repeated {self._suppressed_count}x, suppressed)"
                self._emit_entry_locked(summary)
                self._suppressed_count = 0

            self._last_message = safe_msg
            self._last_message_time = now
            self._emit_entry_locked(safe_msg)

    def log_once(self, key: str, message: str) -> None:
        """Log a message only once per unique key. Useful for one-time diagnostics."""
        with self._lock:
            if key not in self._seen_keys:
                self._seen_keys.add(key)
                # Call internal locked emit directly to avoid double lock acquisition
                now = time.monotonic()
                self._last_message = str(message)
                self._last_message_time = now
                self._emit_entry_locked(str(message))

    def _emit_entry_locked(self, message: str) -> None:
        """Formats, stores, prints, and signals a single log entry. Assumes caller holds self._lock."""
        ts = time.strftime("%H:%M:%S")
        self.history.append((ts, message))

        # Safely print to stdout without crashing on cp1252 encoding
        try:
            encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            encoded_bytes = f"[{ts}] {message}\n".encode(encoding, errors='replace')
            sys.stdout.buffer.write(encoded_bytes)
            sys.stdout.buffer.flush()
        except Exception:
            pass

        self.log_signal.emit(ts, message)


def log_event(message: str, force: bool = False) -> None:
    """Module-level helper to log messages."""
    AppLogger.instance().log(message, force=force)


def log_once(key: str, message: str) -> None:
    """Module-level helper to log a message only once."""
    AppLogger.instance().log_once(key, message)
