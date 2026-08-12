import sys
import re
import time
import ctypes
import asyncio
import subprocess
import threading
from typing import Dict, Any, Optional, Tuple, List
from PyQt6.QtCore import QThread, pyqtSignal

from lyrune.logger import log_event, log_once

# Global WinRT imports for Windows
HAS_WINRT = False
if sys.platform == "win32":
    try:
        import winrt.windows.media.control as wmc
        import winrt.windows.foundation.collections as wfc
        HAS_WINRT = True
    except Exception:
        HAS_WINRT = False


class MediaWorkerThread(QThread):
    """
    Dedicated QThread for Windows WinRT media queries.
    Isolates async WinRT calls from Qt's main GUI thread.

    Improvements:
      - Proper COM lifecycle (CoInitializeEx + CoUninitialize).
      - Media source scanning runs here too (non-blocking for GUI).
    """
    media_updated = pyqtSignal(dict)
    sources_scanned = pyqtSignal(list)   # For async media source enumeration

    def __init__(self, player: "SpotifyPlayer"):
        super().__init__()
        self.player = player
        self._scan_requested = False
        self._scan_lock = threading.Lock()

    def request_source_scan(self):
        """Request an async media source scan on the next loop iteration."""
        with self._scan_lock:
            self._scan_requested = True

    def run(self):
        # Initialize COM for WinRT
        self._com_initialized = False
        if sys.platform == "win32":
            try:
                res = ctypes.windll.ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED for WinRT async dispatch
                # S_OK = 0, S_FALSE = 1 (already initialized on this thread)
                if res in (0, 1):
                    self._com_initialized = True
            except Exception as e:
                log_event(f"[MediaWorkerThread] CoInitializeEx warning: {e}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        log_event("[MediaWorkerThread] Worker loop started.")

        iteration = 0
        try:
            while not self.isInterruptionRequested():
                iteration += 1

                # Handle source scan requests
                with self._scan_lock:
                    should_scan = self._scan_requested
                    self._scan_requested = False

                if should_scan:
                    try:
                        sources = loop.run_until_complete(self.player._scan_media_sources_async())
                        self.sources_scanned.emit(sources)
                    except Exception as e:
                        log_event(f"[MediaWorkerThread] Source scan error: {e}")

                # Regular media query with 0.5s timeout for zero latency
                try:
                    info = loop.run_until_complete(asyncio.wait_for(self.player._fetch_winrt_async(), timeout=0.5))
                    if info:
                        self.media_updated.emit(info)
                except asyncio.TimeoutError:
                    # If WinRT GSMTC hangs/times out, execute window title fallback immediately
                    fallback_info = self.player._fetch_window_title_fallback()
                    if fallback_info and fallback_info.get('title'):
                        self.media_updated.emit(fallback_info)
                except Exception as e:
                    log_event(f"[MediaWorkerThread] Media query error: {e}")

                self.msleep(80)  # ~12.5 Hz polling
        finally:
            # Cancel pending asyncio tasks before closing event loop
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()

            # Clean up COM safely only if initialized by this thread
            if sys.platform == "win32" and getattr(self, '_com_initialized', False):
                try:
                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass
            log_event("[MediaWorkerThread] Worker loop stopped, COM uninitialized.")


class SpotifyPlayer:
    """
    Interfaces with Spotify on Windows and Linux.

    Windows: Uses Windows GSMTC (WinRT) running on a dedicated QThread.
    Linux: Uses MPRIS DBus protocol (dbus-python / Gio / playerctl).

    Improvements over original:
      - Thread-safe interpolation state behind threading.Lock.
      - Position interpolation capped against known track duration.
      - Media source scanning runs on the worker thread (non-blocking GUI).
      - Verbose logging throttled: only logs on state changes.
      - Proper COM lifecycle in worker thread.
      - Window title fallback no longer assumes 'Playing' status blindly.
    """

    def __init__(self):
        self._is_windows = (sys.platform == "win32")
        self._mode: Optional[str] = None

        # Thread-safe interpolation state
        self._state_lock = threading.Lock()
        self._last_raw_pos: float = 0.0
        self._last_update_time: float = time.time()
        self._last_track_id: str = ""
        self._last_status: str = ""
        self._track_duration: float = 0.0  # For position capping

        self._target_source: str = "Auto-Detect"

        # Logging throttle: track what we last logged to avoid duplicate spam
        self._last_logged_track: str = ""
        self._last_logged_status: str = ""
        self._last_logged_lyric_pos: float = -1.0

        self._cached_info: Dict[str, Any] = {
            'title': None,
            'artist': None,
            'position': 0.0,
            'duration': 0.0,
            'status': 'Unknown',
            'is_running': False
        }
        self._worker_thread: Optional[MediaWorkerThread] = None
        self._init_backend()

    def set_target_source(self, source_name: str) -> None:
        """Sets target media source (e.g. 'Auto-Detect', 'Brave', 'Spotify.exe')."""
        self._target_source = source_name or "Auto-Detect"
        log_event(f"[SpotifyPlayer] Target media source set to: '{self._target_source}'")

    def start_worker_thread(self, on_update_callback=None):
        """Starts background QThread worker if running on Windows WinRT."""
        if self._is_windows and self._mode == 'winrt':
            self._worker_thread = MediaWorkerThread(self)
            if on_update_callback:
                self._worker_thread.media_updated.connect(on_update_callback)
            self._worker_thread.media_updated.connect(self._on_worker_update)
            self._worker_thread.start()
            log_event("[SpotifyPlayer] MediaWorkerThread background worker started.")

    def stop_worker_thread(self):
        """Safely stops background QThread worker."""
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.requestInterruption()
            self._worker_thread.wait(3000)  # 3s timeout instead of indefinite
            log_event("[SpotifyPlayer] MediaWorkerThread stopped.")

    def _on_worker_update(self, info: dict):
        """Receives media info from background thread via Qt signal (thread-safe delivery)."""
        self._cached_info = info

    def _init_backend(self) -> None:
        if self._is_windows:
            if HAS_WINRT:
                self._wmc = wmc
                self._mode = 'winrt'
                log_event("[SpotifyPlayer] Windows WinRT GSMTC backend initialized.")
                return
            else:
                self._mode = 'win32-fallback'
                log_event("[SpotifyPlayer] WinRT modules not available, fallback enabled.")
                return

        # Linux backends
        if not self._is_windows:
            try:
                import dbus  # type: ignore
                self._dbus = dbus
                self._mode = 'dbus-python'
                log_event("[SpotifyPlayer] Linux dbus-python backend initialized.")
                return
            except ImportError:
                pass

            try:
                from gi.repository import Gio, GLib  # type: ignore
                self._gio = Gio
                self._glib = GLib
                self._mode = 'gio'
                log_event("[SpotifyPlayer] Linux Gio backend initialized.")
                return
            except ImportError:
                pass

        self._mode = 'playerctl'
        log_event("[SpotifyPlayer] Linux playerctl fallback backend initialized.")

    def get_playback_info(self) -> Dict[str, Any]:
        """Instant O(1) non-blocking read from cached state."""
        if self._mode == 'winrt':
            return self._cached_info
        elif self._mode == 'dbus-python':
            return self._get_info_dbus_python()
        elif self._mode == 'gio':
            return self._get_info_gio()
        else:
            return self._get_info_playerctl()

    def request_source_scan(self):
        """
        Requests an async media source scan from the worker thread.
        Non-blocking for the GUI. Results delivered via sources_scanned signal.
        """
        if self._worker_thread:
            self._worker_thread.request_source_scan()

    def get_available_media_sources(self) -> List[Dict[str, str]]:
        """
        Enumerates all active media sessions (WinRT GSMTC) and visible media windows (win32gui).
        Returns a list of dicts: [{'name': Display Name, 'id': Target ID}]
        """
        sources = [{'name': "✨ Auto-Detect (Active Session)", 'id': "Auto-Detect"}]

        if not self._is_windows:
            return sources

        # 1. Scan WinRT GSMTC sessions (if manager is available)
        if HAS_WINRT and hasattr(self, '_gsm_manager') and self._gsm_manager:
            try:
                sessions = self._gsm_manager.get_sessions()
                for i, s in enumerate(sessions):
                    app_id = getattr(s, 'source_app_user_model_id', '') or f"Session_{i}"
                    lower_id = app_id.lower()
                    display_name = app_id
                    if 'spotify.exe' in lower_id or 'spotify' in lower_id:
                        display_name = "Spotify Desktop App (Spotify.exe)"
                    elif 'brave' in lower_id:
                        display_name = "Brave Browser (Spotify Web)"
                    elif 'chrome' in lower_id:
                        display_name = "Google Chrome (Spotify Web)"
                    elif 'edge' in lower_id:
                        display_name = "Microsoft Edge (Spotify Web)"
                    elif 'firefox' in lower_id:
                        display_name = "Mozilla Firefox (Spotify Web)"

                    target_id = app_id
                    if not any(s['id'] == target_id for s in sources):
                        sources.append({'name': f"🎵 {display_name}", 'id': target_id})
            except Exception as e:
                log_event(f"[GSMTC Source Enumeration Error] {e}")

        # 2. Scan open visible window titles using win32gui
        try:
            import win32gui
            scanned_titles = []

            ignored_keywords = [
                'default ime', 'msctfime ui', 'task view', 'spotify free',
                'spotify premium', 'web player: music for everyone', 'new tab',
                'settings', 'extensions', 'bookmarks', 'downloads'
            ]

            def enum_cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    t = win32gui.GetWindowText(hwnd)
                    if t:
                        norm_t = self._normalize_title(t)
                        lower_t = norm_t.lower().strip()
                        if any(b in lower_t for b in ['spotify', 'brave', 'chrome', 'edge', 'firefox', 'opera']):
                            if not any(ign in lower_t for ign in ignored_keywords):
                                scanned_titles.append((norm_t, lower_t))

            win32gui.EnumWindows(enum_cb, None)

            for norm_t, lower_t in scanned_titles:
                target_id = norm_t
                if 'brave' in lower_t:
                    name = f"🌐 Brave Browser — [{norm_t}]"
                elif 'chrome' in lower_t:
                    name = f"🌐 Chrome Browser — [{norm_t}]"
                elif 'edge' in lower_t:
                    name = f"🌐 Edge Browser — [{norm_t}]"
                elif 'firefox' in lower_t:
                    name = f"🌐 Firefox Browser — [{norm_t}]"
                elif 'spotify' in lower_t:
                    name = f"🎵 Spotify App — [{norm_t}]"
                else:
                    name = f"🖥️ {norm_t}"

                if not any(s['id'] == target_id or s['name'] == name for s in sources):
                    sources.append({'name': name, 'id': target_id})

        except Exception as e:
            log_event(f"[Window Title Source Enumeration Error] {e}")

        return sources

    def get_active_media_sessions(self) -> List[Dict[str, str]]:
        """Alias method for get_available_media_sources."""
        return self.get_available_media_sources()

    async def _scan_media_sources_async(self) -> List[Dict[str, str]]:
        """
        Async media source scan. Runs on the worker thread.
        Returns list of available media sessions.
        """
        sources = [{'name': "✨ Auto-Detect (Active Session)", 'id': "Auto-Detect"}]
        try:
            manager = await self._wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
            sessions = manager.get_sessions()

            for i, s in enumerate(sessions):
                app_id = getattr(s, 'source_app_user_model_id', '') or f"Session_{i}"
                p = await s.try_get_media_properties_async()
                p_title = p.title if p else ""
                p_artist = p.artist if p else ""
                c_art, c_tit = self._clean_track_info(p_title, p_artist)

                display_name = app_id
                lower_id = app_id.lower()
                if 'spotify.exe' in lower_id:
                    display_name = "Spotify Desktop App (Spotify.exe)"
                elif 'brave' in lower_id:
                    display_name = "Brave Browser (Spotify Web)"
                elif 'chrome' in lower_id:
                    display_name = "Google Chrome (Spotify Web)"
                elif 'edge' in lower_id:
                    display_name = "Microsoft Edge (Spotify Web)"
                elif 'firefox' in lower_id:
                    display_name = "Mozilla Firefox (Spotify Web)"

                if c_tit:
                    display_name += f" — [{c_art} - {c_tit}]"

                sources.append({'name': display_name, 'id': app_id})

        except Exception as e:
            log_event(f"[Source Scan Exception] {e}")

        return sources

    def _normalize_title(self, raw: str) -> str:
        """Normalizes Unicode dashes (–, —), bullets (•), and spaces in window titles."""
        if not raw:
            return ""
        s = raw.strip()
        # Replace En Dash (\u2013), Em Dash (\u2014), Bullet (\u2022) with ASCII hyphen '-'
        s = s.replace('\u2013', '-').replace('\u2014', '-').replace('\u2022', '-')
        # Normalize multiple spaces around hyphens
        s = re.sub(r'\s*-\s*', ' - ', s)
        return s.strip()

    def _clean_track_info(self, raw_title: str, raw_artist: str) -> Tuple[str, str]:
        """Parses and cleans up track titles and artists from Spotify Desktop, Web Player, and Browsers."""
        title = self._normalize_title(raw_title)
        artist = (raw_artist or '').strip()

        # Strip browser suffixes (Brave, Chrome, Edge, Firefox, etc.)
        for browser_suffix in [' - Brave', ' - Google Chrome', ' - Microsoft Edge', ' - Mozilla Firefox', ' - Opera']:
            if title.endswith(browser_suffix):
                title = title[:-len(browser_suffix)].strip()

        # Strip common web player suffixes
        for suffix in [' | Spotify', ' - Spotify', ' - Web Player: Music for everyone', ' - Web Player', ' - YouTube Music']:
            if title.endswith(suffix):
                title = title[:-len(suffix)].strip()

        if ' - song and lyrics by ' in title:
            parts = title.split(' - song and lyrics by ', 1)
            title = parts[0].strip()
            if not artist:
                artist = parts[1].strip()
        elif not artist and ' - ' in title:
            parts = title.split(' - ')
            if len(parts) >= 2:
                # In Web Spotify tab titles ("Song Name - Artist Name"), part 0 is title, part 1 is artist
                title = parts[0].strip()
                artist = " - ".join(parts[1:]).strip()

        # Strip extra tags like "- TikTok", "(TikTok)", "(Remix)", "(Official Video)", etc.
        extra_tag_patterns = [
            r'\s*-\s*TikTok.*$', r'\s*\((?:TikTok|Remix|Official Video|Lyric Video|Radio Edit|Video|Audio|Deluxe|Bonus).*?\)',
            r'\s*\[(?:TikTok|Remix|Official Video|Lyric Video|Radio Edit|Video|Audio|Deluxe|Bonus).*?\]'
        ]
        for pat in extra_tag_patterns:
            title = re.sub(pat, '', title, flags=re.IGNORECASE).strip()

        return artist, title

    def _fetch_window_title_fallback(self) -> Dict[str, Any]:
        """
        Secondary fallback: Scans active Windows window titles for Spotify Desktop App or Spotify Web (Brave, Chrome, Edge, Firefox).
        Handles Unicode dashes, bullets, and web browser tab formats.
        """
        result = {
            'title': None, 'artist': None, 'position': 0.0,
            'duration': 0.0, 'status': 'Unknown', 'is_running': False
        }
        if not self._is_windows:
            return result

        try:
            import win32gui

            found_title = None

            ignored_keywords = [
                'default ime', 'msctfime ui', 'task view', 'spotify free',
                'spotify premium', 'web player: music for everyone', 'new tab',
                'settings', 'extensions', 'bookmarks', 'downloads'
            ]

            def enum_cb(hwnd, _):
                nonlocal found_title
                if win32gui.IsWindowVisible(hwnd):
                    t = win32gui.GetWindowText(hwnd)
                    if t:
                        norm_t = self._normalize_title(t)
                        if ' - ' in norm_t or ' | ' in norm_t:
                            lower_t = norm_t.lower().strip()
                            if not any(ign in lower_t for ign in ignored_keywords):
                                if self._target_source != "Auto-Detect":
                                    lower_tgt = self._target_source.lower().strip()
                                    # Same rule as the GSMTC matcher: a target
                                    # that is a specific session id must match the
                                    # title exactly; otherwise any Brave/Chrome
                                    # window (e.g. a movie-streaming tab) would be
                                    # mistaken for the Spotify track.
                                    is_session_id = '_crx_' in lower_tgt or '.exe' in lower_tgt
                                    if (lower_tgt in lower_t or lower_t in lower_tgt or
                                            (not is_session_id and any(b in lower_tgt and b in lower_t for b in ['brave', 'spotify', 'chrome', 'edge', 'firefox']))):
                                        found_title = norm_t
                                else:
                                    # Matches Brave, Chrome, Edge, Firefox, or Spotify window titles
                                    if any(browser in lower_t for browser in ['brave', 'chrome', 'edge', 'firefox', 'opera', 'spotify']):
                                        found_title = norm_t
                                    elif ' - song and lyrics by ' in lower_t or 'spotify' in lower_t:
                                        found_title = norm_t

            win32gui.EnumWindows(enum_cb, None)

            if found_title:
                c_art, c_tit = self._clean_track_info(found_title, '')
                # Require both artist and title to prevent matching random generic window titles (e.g. Inbox - Gmail)
                if c_art and c_tit and c_tit.lower() not in ['spotify', 'spotify free', 'spotify premium', 'web player']:
                    track_id = f"{c_art} - {c_tit}"
                    now = time.time()

                    with self._state_lock:
                        if track_id != self._last_track_id:
                            self._last_track_id = track_id
                            self._last_raw_pos = 0.0
                            self._last_update_time = now
                            calc_pos = 0.0
                        else:
                            elapsed = now - self._last_update_time
                            calc_pos = self._last_raw_pos + elapsed

                    log_once(f"window_title_match_{track_id}", f"[Window Title Match] Found '{found_title}' -> Artist: '{c_art}', Title: '{c_tit}'")

                    return {
                        'title': c_tit,
                        'artist': c_art,
                        'position': max(0.0, calc_pos),
                        'duration': 0.0,
                        'status': 'Playing',
                        'is_running': True
                    }
        except Exception as e:
            log_event(f"[Window Title Fallback Exception] {e}")

        return result

    async def _fetch_winrt_async(self) -> Dict[str, Any]:
        """
        Main WinRT GSMTC async fetch. Runs on the worker thread.
        Thread-safe interpolation state updates via self._state_lock.
        """
        result = {
            'title': None, 'artist': None, 'position': 0.0,
            'duration': 0.0, 'status': 'Unknown', 'is_running': False
        }
        try:
            # Reuse cached manager to avoid 12.5 Hz request_async IPC flooding
            if not hasattr(self, '_gsm_manager') or self._gsm_manager is None:
                try:
                    self._gsm_manager = await self._wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
                except Exception as ex:
                    log_event(f"[GSMTC Manager Request Exception] {ex}", force=True)
                    return result

            manager = self._gsm_manager
            if not manager:
                return result

            session = None
            props = None
            clean_artist = ""
            clean_title = ""

            sessions = manager.get_sessions()
            session_count = len(sessions)
            spotify_empty_session_found = False

            log_once("session_count", f"[Media Sessions] Total active GSMTC sessions: {session_count}")

            # Scan all sessions — prioritize music sessions with valid artist & title
            best_session = None
            best_quality = -1

            try:
                for i, s in enumerate(sessions):
                    app_id = getattr(s, 'source_app_user_model_id', '').lower()
                    p = await s.try_get_media_properties_async()
                    p_title = p.title if p else ""
                    p_artist = p.artist if p else ""
                    c_art, c_tit = self._clean_track_info(p_title, p_artist)

                    if c_tit:
                        info = s.get_playback_info()
                        status_num = int(info.playback_status) if info else 0

                        log_once(f"session_{i}_{app_id}", f"  -> Session {i}: app_id='{app_id}' status={status_num} title='{p_title}' artist='{p_artist}' clean='{c_art} - {c_tit}'")

                        if 'spotify' in app_id and not c_tit:
                            spotify_empty_session_found = True

                        # Rate session quality:
                        # Quality 3 = Playing with both artist & title (or Spotify app)
                        # Quality 2 = Paused with both artist & title (or Spotify app)
                        # Quality 1 = Playing with title only (e.g. browser tab)
                        # Quality 0 = Paused with title only
                        has_artist = bool(c_art or p_artist)
                        is_spotify = 'spotify' in app_id
                        is_music = has_artist or is_spotify

                        if is_music:
                            quality = 3 if status_num == 4 else 2
                        else:
                            quality = 1 if status_num == 4 else 0

                        # Target source matching
                        if self._target_source != "Auto-Detect":
                            lower_target = self._target_source.lower().strip()
                            is_session_id = '_crx_' in lower_target or '.exe' in lower_target
                            if (lower_target in app_id or app_id in lower_target or
                                    (not is_session_id and (('brave' in lower_target and 'brave' in app_id) or ('spotify' in lower_target and 'spotify' in app_id)))):
                                session, props = s, p
                                clean_artist, clean_title = c_art, c_tit
                                break
                        else:
                            # Auto-Detect: select the session with highest quality score
                            if quality > best_quality:
                                best_quality = quality
                                best_session = (s, p, c_art, c_tit)

                if not session and self._target_source == "Auto-Detect" and best_session:
                    session, props, clean_artist, clean_title = best_session

            except Exception as e:
                log_event(f"[Session Scan Error] {e}")

            # Fallback to system current session
            if not session and self._target_source == "Auto-Detect":
                curr = manager.get_current_session()
                if curr:
                    p = await curr.try_get_media_properties_async()
                    if p:
                        c_art, c_tit = self._clean_track_info(p.title, p.artist)
                        if c_tit:
                            session, props = curr, p
                            clean_artist, clean_title = c_art, c_tit

            if not session or not clean_title:
                # Try window title fallback
                fallback_res = self._fetch_window_title_fallback()
                if fallback_res.get('title'):
                    return fallback_res

                if spotify_empty_session_found:
                    # Only log this notice once
                    if self._last_logged_status != "empty_spotify_notice":
                        self._last_logged_status = "empty_spotify_notice"
                        log_event("[NOTICE] Spotify is running but Windows is hiding track metadata.")
                        log_event("   -> Fix: Spotify Settings -> Display -> Enable 'Show desktop overlay'.")

                return result

            info = session.get_playback_info()
            timeline = session.get_timeline_properties()

            status_num = int(info.playback_status) if info else 0
            if status_num == 4:
                status_str = "Playing"
            elif status_num == 5:
                status_str = "Paused"
            else:
                status_str = "Stopped"

            raw_pos = 0.0
            duration = 0.0
            last_updated_offset = 0.0
            if timeline:
                if timeline.position:
                    raw_pos = timeline.position.total_seconds()
                if timeline.end_time:
                    duration = timeline.end_time.total_seconds()
                if hasattr(timeline, 'last_updated_time') and timeline.last_updated_time:
                    try:
                        import datetime
                        now_utc = datetime.datetime.now(datetime.timezone.utc)
                        last_updated_offset = max(0.0, (now_utc - timeline.last_updated_time).total_seconds())
                    except Exception:
                        last_updated_offset = 0.0

            # If playing, factor in elapsed time since Windows GSMTC recorded last_updated_time
            if status_str == "Playing":
                effective_raw_pos = raw_pos + last_updated_offset
            else:
                effective_raw_pos = raw_pos

            track_id = f"{clean_artist} - {clean_title}"
            now = time.time()

            # Thread-safe position interpolation
            with self._state_lock:
                if track_id != self._last_track_id:
                    self._last_track_id = track_id
                    self._last_raw_pos = effective_raw_pos
                    self._last_update_time = now
                    self._track_duration = duration
                    calc_pos = effective_raw_pos
                    log_event(f"[Detected Track] '{clean_artist} - {clean_title}' (Status: {status_str}, Pos: {effective_raw_pos:.2f}s, Duration: {duration:.0f}s)")
                elif status_str == "Playing":
                    if abs(effective_raw_pos - self._last_raw_pos) > 0.5:
                        # Position updated from GSMTC (e.g. seek or progress update)
                        self._last_raw_pos = effective_raw_pos
                        self._last_update_time = now
                        calc_pos = effective_raw_pos
                    else:
                        elapsed = now - self._last_update_time
                        calc_pos = self._last_raw_pos + elapsed
                    if duration > 0:
                        self._track_duration = duration
                else:
                    self._last_update_time = now
                    calc_pos = self._last_raw_pos if self._last_raw_pos > 0 else effective_raw_pos

                # Cap position against track duration to prevent unbounded drift
                if self._track_duration > 0 and calc_pos > self._track_duration:
                    calc_pos = self._track_duration

            # Throttled status logging — only log on status change
            if status_str != self._last_logged_status:
                self._last_logged_status = status_str
                log_event(f"[Playback] Status changed to: {status_str} at {calc_pos:.2f}s")

            return {
                'title': clean_title,
                'artist': clean_artist,
                'position': max(0.0, calc_pos),
                'duration': duration,
                'status': status_str,
                'is_running': True
            }
        except Exception as e:
            self._gsm_manager = None  # Reset manager so next call re-requests a fresh session manager
            log_event(f"[GSMTC Fetch Exception] {type(e).__name__}: {e}", force=True)
            return result

    # ─── Linux Backends ─────────────────────────────────────────────────

    def _get_info_dbus_python(self) -> Dict[str, Any]:
        result = {
            'title': None, 'artist': None, 'position': 0.0,
            'duration': 0.0, 'status': 'Unknown', 'is_running': False
        }
        try:
            session_bus = self._dbus.SessionBus()
            spotify_service = None

            for name in session_bus.list_names():
                name_str = str(name)
                if name_str.startswith("org.mpris.MediaPlayer2.spotify"):
                    spotify_service = name_str
                    break

            if not spotify_service:
                for name in session_bus.list_names():
                    name_str = str(name)
                    if name_str.startswith("org.mpris.MediaPlayer2.") and "spotify" in name_str.lower():
                        spotify_service = name_str
                        break

            if not spotify_service:
                return result

            spotify_obj = session_bus.get_object(spotify_service, "/org/mpris/MediaPlayer2")
            props_iface = self._dbus.Interface(spotify_obj, "org.freedesktop.DBus.Properties")

            metadata = props_iface.Get("org.mpris.MediaPlayer2.Player", "Metadata")
            playback_status = str(props_iface.Get("org.mpris.MediaPlayer2.Player", "PlaybackStatus"))
            position_us = int(props_iface.Get("org.mpris.MediaPlayer2.Player", "Position"))

            title = str(metadata.get('xesam:title', ''))
            artist_raw = metadata.get('xesam:artist', [])
            duration_us = int(metadata.get('mpris:length', 0))

            if isinstance(artist_raw, (list, tuple)):
                artist = ", ".join([str(a) for a in artist_raw])
            else:
                artist = str(artist_raw)

            result['title'] = title
            result['artist'] = artist
            result['position'] = float(position_us) / 1_000_000.0
            result['duration'] = float(duration_us) / 1_000_000.0
            result['status'] = playback_status
            result['is_running'] = True

        except Exception:
            pass

        return result

    def _get_info_gio(self) -> Dict[str, Any]:
        result = {
            'title': None, 'artist': None, 'position': 0.0,
            'duration': 0.0, 'status': 'Unknown', 'is_running': False
        }
        try:
            bus = self._gio.bus_get_sync(self._gio.BusType.SESSION, None)
            proxy = self._gio.DBusProxy.new_sync(
                bus,
                self._gio.DBusProxyFlags.NONE,
                None,
                "org.mpris.MediaPlayer2.spotify",
                "/org/mpris/MediaPlayer2",
                "org.freedesktop.DBus.Properties",
                None
            )

            status_variant = proxy.call_sync(
                "Get",
                self._glib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "PlaybackStatus")),
                self._gio.DBusCallFlags.NONE,
                -1,
                None
            )
            playback_status = status_variant.get_child_value(0).get_variant().get_string()

            pos_variant = proxy.call_sync(
                "Get",
                self._glib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "Position")),
                self._gio.DBusCallFlags.NONE,
                -1,
                None
            )
            position_us = pos_variant.get_child_value(0).get_variant().get_int64()

            meta_variant = proxy.call_sync(
                "Get",
                self._glib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "Metadata")),
                self._gio.DBusCallFlags.NONE,
                -1,
                None
            )
            metadata = meta_variant.get_child_value(0).get_variant()

            title = ""
            artist = ""
            duration_us = 0
            if metadata.contains("xesam:title"):
                title = metadata.lookup_value("xesam:title", None).get_string()
            if metadata.contains("xesam:artist"):
                artists_val = metadata.lookup_value("xesam:artist", None)
                artist = ", ".join([artists_val.get_child_value(i).get_string() for i in range(artists_val.n_children())])
            if metadata.contains("mpris:length"):
                duration_us = metadata.lookup_value("mpris:length", None).get_int64()

            result['title'] = title
            result['artist'] = artist
            result['position'] = float(position_us) / 1_000_000.0
            result['duration'] = float(duration_us) / 1_000_000.0
            result['status'] = playback_status
            result['is_running'] = True

        except Exception:
            pass

        return result

    def _get_info_playerctl(self) -> Dict[str, Any]:
        result = {
            'title': None, 'artist': None, 'position': 0.0,
            'duration': 0.0, 'status': 'Unknown', 'is_running': False
        }
        try:
            cmd = ["playerctl", "--player=spotify", "metadata", "--format",
                   "{{title}}|||{{artist}}|||{{position}}|||{{status}}|||{{mpris:length}}"]
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
            parts = output.split("|||")
            if len(parts) >= 4:
                result['title'] = parts[0]
                result['artist'] = parts[1]
                pos_val = float(parts[2]) if parts[2] else 0.0
                result['position'] = pos_val / 1_000_000.0 if pos_val > 10000 else pos_val
                result['status'] = parts[3]
                result['is_running'] = True
                if len(parts) >= 5 and parts[4]:
                    dur_val = float(parts[4])
                    result['duration'] = dur_val / 1_000_000.0 if dur_val > 10000 else dur_val
        except Exception:
            pass

        return result
