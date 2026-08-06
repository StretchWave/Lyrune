import re
import bisect
from typing import List, Tuple, Optional


class LRCParser:
    """
    Parses LRC formatted synchronized lyrics and provides fast timestamp matching.

    Improvements over original:
      - O(log n) lyric lookup via bisect instead of O(n) linear scan.
      - Supports hour-format timestamps: [hh:mm:ss.xx], [mm:ss.xx], [mm:ss].
      - Normalizes 1-3 digit milliseconds correctly (.1 → 0.1, .12 → 0.12, .123 → 0.123).
      - Preserves empty lyric lines as "♪" (musical interlude markers).
      - Exposes track duration from last timestamp for position capping.

    LRC Format examples:
        [00:12.34] First lyric line
        [00:15.67] Second lyric line
        [01:02:15.67] Hour-format line
        [00:30.00]                    ← empty = instrumental interlude
    """

    # Matches [mm:ss], [mm:ss.x], [mm:ss.xx], [mm:ss.xxx], [hh:mm:ss.xx]
    _TIMESTAMP_RE = re.compile(
        r'\[(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]'
    )

    def __init__(self, lrc_text: Optional[str] = None):
        # Parallel sorted lists for bisect: timestamps[i] ↔ lyrics[i]
        self._timestamps: List[float] = []
        self._lyrics: List[str] = []
        if lrc_text:
            self.parse(lrc_text)

    def parse(self, lrc_text: str) -> None:
        """Parses LRC text into sorted timestamp-lyric pairs."""
        pairs: List[Tuple[float, str]] = []

        if not lrc_text or not lrc_text.strip():
            self._timestamps = []
            self._lyrics = []
            return

        for raw_line in lrc_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            timestamps = self._TIMESTAMP_RE.findall(line)
            if not timestamps:
                continue

            # Remove all timestamp tags to get the lyric text
            lyric_text = self._TIMESTAMP_RE.sub('', line).strip()

            # Preserve empty lines as interlude markers
            if not lyric_text:
                lyric_text = "♪"

            for hours_str, mins_str, secs_str, ms_str in timestamps:
                hours = int(hours_str) if hours_str else 0
                minutes = int(mins_str)
                seconds = int(secs_str)

                # Normalize milliseconds: pad to 3 digits then divide
                if ms_str:
                    ms_padded = ms_str.ljust(3, '0')
                    fraction = int(ms_padded) / 1000.0
                else:
                    fraction = 0.0

                total_seconds = hours * 3600 + minutes * 60 + seconds + fraction
                pairs.append((total_seconds, lyric_text))

        # Sort chronologically
        pairs.sort(key=lambda item: item[0])

        # Split into parallel lists for bisect
        self._timestamps = [t for t, _ in pairs]
        self._lyrics = [l for _, l in pairs]

    def get_current_lyric(self, current_time: float) -> str:
        """
        Returns the active lyric line for the given playback time.
        Uses bisect for O(log n) lookup.
        Returns empty string if position is before the first timestamp.
        """
        if not self._timestamps:
            return ""

        # bisect_right returns insertion point; subtract 1 to get the active line
        idx = bisect.bisect_right(self._timestamps, current_time) - 1
        if idx < 0:
            return ""
        return self._lyrics[idx]

    def get_lyric_context(self, current_time: float) -> Tuple[str, str, str, int]:
        """
        Returns (prev_lyric, current_lyric, next_lyric, active_index).
        Provides 3-line context for smooth multi-line display.
        """
        if not self._timestamps:
            return ("", "", "", -1)

        idx = bisect.bisect_right(self._timestamps, current_time) - 1
        if idx < 0:
            next_lyric = self._lyrics[0] if self._lyrics else ""
            return ("", "", next_lyric, -1)

        prev_lyric = self._lyrics[idx - 1] if idx > 0 else ""
        current_lyric = self._lyrics[idx]
        next_lyric = self._lyrics[idx + 1] if idx < len(self._lyrics) - 1 else ""

        return (prev_lyric, current_lyric, next_lyric, idx)

    def get_lyric_window(self, current_time: float, above: int = 1, below: int = 1) -> Tuple[List[str], str, List[str], int]:
        """
        Returns (prev_lines, active_line, next_lines, active_index) for dynamic multi-line context windows.
        prev_lines: list of up to `above` lines preceding the active line (oldest to newest).
        next_lines: list of up to `below` lines following the active line.
        """
        if not self._timestamps:
            return ([], "", [], -1)

        idx = bisect.bisect_right(self._timestamps, current_time) - 1
        if idx < 0:
            next_lines = self._lyrics[:below] if self._lyrics else []
            return ([], "", next_lines, -1)

        start_above = max(0, idx - above)
        prev_lines = self._lyrics[start_above:idx]

        active_line = self._lyrics[idx]

        end_below = min(len(self._lyrics), idx + 1 + below)
        next_lines = self._lyrics[idx + 1:end_below]

        return (prev_lines, active_line, next_lines, idx)

    def has_lyrics(self) -> bool:
        """Checks if any valid timestamped lyrics were parsed."""
        return len(self._timestamps) > 0

    @property
    def duration(self) -> float:
        """Returns the timestamp of the last lyric line, useful for position capping."""
        if self._timestamps:
            return self._timestamps[-1]
        return 0.0

    @property
    def line_count(self) -> int:
        """Number of parsed lyric lines."""
        return len(self._timestamps)

    @property
    def lines(self) -> List[Tuple[float, str]]:
        """Legacy compatibility: returns list of (timestamp, lyric) tuples."""
        return list(zip(self._timestamps, self._lyrics))
