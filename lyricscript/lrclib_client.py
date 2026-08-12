import os
import re
import json
import time
import hashlib
import requests
from typing import Optional, Dict, Tuple, List
from PyQt6.QtCore import QThread, pyqtSignal

from lyricscript.logger import log_event

# Disk cache directory — next to the script
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_SCRIPT_DIR, ".lyrics_cache")


class LyricsFetchWorker(QThread):
    """
    Background worker thread for fetching lyrics from LRCLIB.
    Prevents the GUI from freezing during HTTP requests.

    Emits:
      - lyrics_ready(artist, title, synced_lrc, unsynced_lrc)
      - fetch_started(artist, title)
    """
    lyrics_ready = pyqtSignal(str, str, str, str)   # artist, title, synced, unsynced
    fetch_started = pyqtSignal(str, str)              # artist, title

    def __init__(self, client: "LRCLibClient", artist: str, title: str):
        super().__init__()
        self._client = client
        self._artist = artist
        self._title = title

    def run(self):
        try:
            self.fetch_started.emit(self._artist, self._title)
            synced, unsynced = self._client.fetch_lyrics(self._artist, self._title)
            self.lyrics_ready.emit(self._artist, self._title, synced or "", unsynced or "")
        except Exception as e:
            log_event(f"❌ [LyricsWorker Exception] Error fetching lyrics: {e}")
            self.lyrics_ready.emit(self._artist, self._title, "", "")


class LRCLibClient:
    """
    Client for querying synced/unsynced lyrics from LRCLIB (https://lrclib.net).

    Improvements over original:
      - Two-tier API: tries /api/get (exact match) first, then /api/search (fuzzy).
      - Returns both synced and unsynced lyrics (unsynced as fallback display).
      - Disk cache: lyrics persist across app restarts in .lyrics_cache/ directory.
      - In-memory cache for instant repeated lookups within a session.
      - Network failure TTL: caches failures for 60s to avoid retry spam.
      - Non-blocking async fetch via LyricsFetchWorker QThread.
    """

    API_GET_URL = "https://lrclib.net/api/get"
    API_SEARCH_URL = "https://lrclib.net/api/search"
    FAILURE_TTL = 60.0  # seconds before retrying a failed network lookup
    HEADERS = {"User-Agent": "LyricScript-DesktopWidget/2.0"}

    def __init__(self):
        self._mem_cache: Dict[Tuple[str, str], Tuple[Optional[str], Optional[str]]] = {}
        self._failure_cache: Dict[Tuple[str, str], float] = {}  # key → monotonic timestamp
        os.makedirs(_CACHE_DIR, exist_ok=True)

    def _normalize_tag(self, s: str) -> str:
        """Normalizes titles and artists for stable cache key generation."""
        if not s:
            return ""
        clean = s.strip().lower()
        clean = re.sub(r'\s*-\s*tiktok.*$', '', clean)
        clean = re.sub(r'\s*\((?:tiktok|remix|official video|lyric video|radio edit|video|audio|deluxe|bonus).*?\)', '', clean)
        clean = re.sub(r'[\W_]+', ' ', clean).strip()
        return clean

    def _cache_key(self, artist: str, title: str) -> Tuple[str, str]:
        return (self._normalize_tag(artist), self._normalize_tag(title))

    def _disk_cache_path(self, artist: str, title: str) -> str:
        """Generates a stable filesystem-safe cache filename."""
        key_str = f"{self._normalize_tag(artist)}|{self._normalize_tag(title)}"
        h = hashlib.sha256(key_str.encode("utf-8")).hexdigest()[:16]
        return os.path.join(_CACHE_DIR, f"{h}.json")

    def _load_disk_cache(self, artist: str, title: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
        """Load cached lyrics from disk."""
        path = self._disk_cache_path(artist, title)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return (data.get("synced"), data.get("unsynced"))
            except Exception:
                pass
        return None

    def _save_disk_cache(self, artist: str, title: str, synced: Optional[str], unsynced: Optional[str]) -> None:
        """Persist lyrics to disk cache using atomic temp file replacement."""
        path = self._disk_cache_path(artist, title)
        tmp_path = f"{path}.tmp_{os.getpid()}_{int(time.time() * 1000)}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"synced": synced, "unsynced": unsynced, "artist": artist, "title": title}, f)
            os.replace(tmp_path, path)
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            log_event(f"[LRCLib Cache Error] Failed to write cache for '{artist} - {title}': {e}")

    def get_synced_lyrics(self, artist: str, title: str) -> Optional[str]:
        """
        Legacy compatibility: returns only synced lyrics (or None).
        Prefer fetch_lyrics() for both synced + unsynced.
        """
        synced, _ = self.fetch_lyrics(artist, title)
        return synced

    def fetch_lyrics(self, artist: str, title: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Fetches lyrics for the given artist/title.
        Returns (synced_lrc, unsynced_lyrics). Either or both may be None.

        Lookup order:
          1. In-memory cache
          2. Disk cache
          3. /api/get (exact match)
          4. /api/search (fuzzy search) — first result with synced lyrics
        """
        if not artist or not title:
            log_event("[LRCLibClient] Skipping fetch: artist or track is empty.")
            return (None, None)

        key = self._cache_key(artist, title)

        # 1. In-memory cache
        if key in self._mem_cache:
            log_event(f"[LRCLib Cache HIT] In-memory cache for '{artist} - {title}'")
            return self._mem_cache[key]

        # 2. Disk cache
        disk_result = self._load_disk_cache(artist, title)
        if disk_result is not None:
            self._mem_cache[key] = disk_result
            log_event(f"[LRCLib Cache HIT] Disk cache for '{artist} - {title}'")
            return disk_result

        # 3. Check failure TTL
        if key in self._failure_cache:
            elapsed = time.monotonic() - self._failure_cache[key]
            if elapsed < self.FAILURE_TTL:
                log_event(f"[LRCLib] Skipping retry for '{artist} - {title}' (failed {elapsed:.0f}s ago, TTL={self.FAILURE_TTL}s)")
                return (None, None)
            else:
                del self._failure_cache[key]

        # 4. Try /api/get (exact match)
        log_event(f"[LRCLib] Querying /api/get for '{artist}' - '{title}'...")
        synced, unsynced = self._api_get(artist, title)

        # 5. Fallback to /api/search if no synced lyrics from /api/get
        if synced is None:
            log_event(f"[LRCLib] Exact match failed, trying /api/search for '{artist}' - '{title}'...")
            synced_s, unsynced_s = self._api_search(artist, title)
            if synced_s:
                synced = synced_s
            if unsynced_s and not unsynced:
                unsynced = unsynced_s

        # 6. Fallback: try swapped artist/title if no lyrics found yet
        if synced is None and unsynced is None and artist and title:
            log_event(f"[LRCLib] Retrying with swapped query '{title}' - '{artist}'...")
            synced_sw, unsynced_sw = self._api_get(title, artist)
            if synced_sw or unsynced_sw:
                synced, unsynced = synced_sw, unsynced_sw
            else:
                synced_s, unsynced_s = self._api_search(title, artist)
                if synced_s or unsynced_s:
                    synced, unsynced = synced_s, unsynced_s

        # 7. Fallback: try primary artist & clean title (strip TikTok/remix tags and secondary artists)
        if synced is None:
            import re
            clean_artist = re.split(r'[,&]|\s+(?:ft|feat)\.?', artist, flags=re.IGNORECASE)[0].strip()
            clean_title = re.sub(r'\s*-\s*TikTok.*$', '', title, flags=re.IGNORECASE).strip()
            clean_title = re.sub(r'\s*\((?:TikTok|Remix|Official Video|Lyric Video|Radio Edit|Video|Audio|Deluxe|Bonus).*?\)', '', clean_title, flags=re.IGNORECASE).strip()

            if (clean_artist != artist or clean_title != title) and (clean_artist or clean_title):
                log_event(f"[LRCLib] Retrying with cleaned query '{clean_artist}' - '{clean_title}'...")
                synced_c, unsynced_c = self._api_search(clean_artist or artist, clean_title or title)
                if synced_c:
                    synced = synced_c
                if unsynced_c and not unsynced:
                    unsynced = unsynced_c

        # Cache result
        result = (synced, unsynced)
        if synced or unsynced:
            self._mem_cache[key] = result
            self._save_disk_cache(artist, title, synced, unsynced)
            log_event(f"[LRCLib] Cached {'synced' if synced else 'unsynced'} lyrics for '{artist} - {title}'")
        else:
            # Cache the failure with TTL. Deliberately NOT stored in the
            # in-memory cache: a permanent (None, None) entry would make the
            # failure TTL dead code (every later lookup would short-circuit on
            # the memory hit before ever reaching the retry check).
            self._failure_cache[key] = time.monotonic()
            log_event(f"[LRCLib] No lyrics found for '{artist} - {title}' (will retry after {self.FAILURE_TTL}s)")

        return result

    def _api_get(self, artist: str, title: str) -> Tuple[Optional[str], Optional[str]]:
        """Exact match API endpoint."""
        try:
            resp = requests.get(
                self.API_GET_URL,
                params={"artist_name": artist.strip(), "track_name": title.strip()},
                headers=self.HEADERS,
                timeout=3.5
            )
            if resp.status_code == 200:
                data = resp.json()
                synced = data.get("syncedLyrics") or None
                unsynced = data.get("plainLyrics") or None
                return (synced, unsynced)
            else:
                log_event(f"[LRCLib /api/get] HTTP {resp.status_code} for '{artist} - {title}'")
        except Exception as e:
            log_event(f"[LRCLib /api/get Exception] {e}")
        return (None, None)

    def search_lyrics(self, artist: str = "", title: str = "") -> List[dict]:
        """Performs a search query against LRCLIB API and returns list of result item dicts."""
        try:
            query = f"{artist} {title}".strip()
            resp = requests.get(
                self.API_SEARCH_URL,
                params={"q": query},
                headers=self.HEADERS,
                timeout=5.0
            )
            if resp.status_code == 200:
                results = resp.json()
                if isinstance(results, list):
                    return results
        except Exception as e:
            log_event(f"[LRCLib Search Exception] {e}")
        return []

    def _api_search(self, artist: str = "", title: str = "") -> Tuple[Optional[str], Optional[str]]:
        """Fuzzy search API endpoint. Returns the best match with synced lyrics after validating title match."""
        try:
            resp = requests.get(
                self.API_SEARCH_URL,
                params={"q": f"{artist} {title}"},
                headers=self.HEADERS,
                timeout=3.5
            )
            if resp.status_code == 200:
                results = resp.json()
                if isinstance(results, list):
                    norm_target_title = self._normalize_tag(title)
                    target_words = set(norm_target_title.split())

                    # Helper to check if a search result matches target title
                    def is_valid_match(item_dict: dict) -> bool:
                        res_track = self._normalize_tag(item_dict.get("trackName") or item_dict.get("name") or "")
                        if not res_track or not norm_target_title:
                            return True
                        res_words = set(res_track.split())
                        # Require at least 50% word overlap to prevent false matches
                        if target_words and res_words:
                            overlap = len(target_words & res_words)
                            overlap_ratio = overlap / max(len(target_words), 1)
                            return overlap_ratio >= 0.5
                        return True

                    # Prefer results with syncedLyrics and title similarity
                    for item in results:
                        synced = item.get("syncedLyrics")
                        if synced and is_valid_match(item):
                            unsynced = item.get("plainLyrics") or None
                            match_name = item.get("trackName") or title
                            log_event(f"[LRCLib /api/search] Found validated synced lyrics for '{match_name}'")
                            return (synced, unsynced)
                    # Fallback: first result with any lyrics and valid title match
                    for item in results:
                        unsynced = item.get("plainLyrics")
                        if unsynced and is_valid_match(item):
                            match_name = item.get("trackName") or title
                            log_event(f"[LRCLib /api/search] Found validated unsynced lyrics for '{match_name}'")
                            return (None, unsynced)
            else:
                log_event(f"[LRCLib /api/search] HTTP {resp.status_code}")
        except Exception as e:
            log_event(f"[LRCLib /api/search Exception] {e}")
        return (None, None)

    def clear_track_cache(self, artist: str, title: str) -> None:
        """Purges memory and disk cache for a specific track to force a fresh online reload."""
        key = self._cache_key(artist, title)
        if key in self._mem_cache:
            del self._mem_cache[key]
        if key in self._failure_cache:
            del self._failure_cache[key]
        disk_path = self._disk_cache_path(artist, title)
        if os.path.exists(disk_path):
            try:
                os.remove(disk_path)
            except Exception:
                pass
        log_event(f"[LRCLib Cache] Cleared cache for track: '{artist} - {title}'")

    def clear_cache(self) -> None:
        """Clears both in-memory and disk caches."""
        self._mem_cache.clear()
        self._failure_cache.clear()
        try:
            for f in os.listdir(_CACHE_DIR):
                fp = os.path.join(_CACHE_DIR, f)
                if os.path.isfile(fp) and f.endswith(".json"):
                    os.remove(fp)
        except Exception:
            pass
