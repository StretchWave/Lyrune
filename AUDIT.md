# LyricScript — Comprehensive Code Audit & Feature Roadmap

> **Audit Date:** August 12, 2026  
> **Auditor:** AntiGravity AI (Pair Programming Audit)  
> **Target Codebase:** `LyricScript` (Desktop Lyrics Overlay for Spotify & Web Browsers)

---

## 1. Bugs & Architectural Risk Audit

The table below outlines confirmed bugs, concurrency vulnerabilities, COM lifecycle risks, and edge cases discovered during a line-by-line inspection of the core codebase.

| Severity | File : Line | Description | Suggested Fix |
| :--- | :--- | :--- | :--- |
| **High** | [spotify_player.py:48-96](file:///c:/Table%20Of%20Contents/Musics/LyricScript/spotify_player.py#L48-L96) | **Unbalanced COM Lifecycle in `MediaWorkerThread`**: `CoInitializeEx` is called at thread start, but `CoUninitialize` is executed in `finally:` without checking if initialization succeeded or returned `RPC_E_CHANGED_MODE`. | Check `HRESULT` return code of `CoInitializeEx`. Only call `CoUninitialize()` if COM was successfully initialized on this thread. |
| **High** | [spotify_player.py:491-496](file:///c:/Table%20Of%20Contents/Musics/LyricScript/spotify_player.py#L491-L496) | **Stale WinRT Session Manager Handle**: `self._gsm_manager` is cached on the player. If Windows Media service resets or crashes, the cached COM reference becomes invalid and permanently breaks media queries until app restart. | Handle COM errors by resetting `self._gsm_manager = None` and re-requesting a fresh `GlobalSystemMediaTransportControlsSessionManager` instance on failure. |
| **High** | [lrclib_client.py:218-247](file:///c:/Table%20Of%20Contents/Musics/LyricScript/lrclib_client.py#L218-L247) | **Fuzzy Search Unvalidated Binding**: `_api_search()` binds the *first* search result containing `syncedLyrics` without checking artist/title similarity or track duration, causing wrong lyrics to attach to common track titles. | Add duration checking (±5s tolerance) and string similarity thresholding before accepting fuzzy LRCLIB search matches. |
| **High** | [logger.py:28-82](file:///c:/Table%20Of%20Contents/Musics/LyricScript/logger.py#L28-L82) | **Unsafe Multi-Thread State Mutations in Logger**: Methods `log()`, `_emit_entry()`, and `log_once()` modify `self.history`, `self._last_message`, `self._suppressed_count`, and `self._seen_keys` across worker threads without acquiring `_lock`. | Enforce `with self._lock:` inside `log()`, `_emit_entry()`, and `log_once()` to guarantee thread safety across GUI and media worker threads. |
| **High** | [settings_manager.py:6-156](file:///c:/Table%20Of%20Contents/Musics/LyricScript/settings_manager.py#L6-L156) | **PyInstaller Path Resolution & Exit Data Loss**: Resolving `settings.json` relative to `__file__` breaks when frozen with PyInstaller (writes to temp `_MEIxxxx` dir). Also, sudden exit inside 500ms debounce loses unsaved settings. | Store settings in platform app data directory (`%APPDATA%/LyricScript/settings.json`) and register `QApplication.aboutToQuit` signal to call `save_immediate()`. |
| **Medium** | [spotify_player.py:54-90](file:///c:/Table%20Of%20Contents/Musics/LyricScript/spotify_player.py#L54-L90) | **Orphaned WinRT Async Tasks on Thread Stop**: Calling `stop_worker_thread()` terminates the `QThread` and closes `asyncio` event loop while WinRT async operations are in flight, throwing closed-loop exceptions. | Cancel all running `asyncio.Task` instances gracefully before invoking `loop.close()`. |
| **Medium** | [spotify_player.py:517-561](file:///c:/Table%20Of%20Contents/Musics/LyricScript/spotify_player.py#L517-L561) | **Multi-Session Ambiguity in Auto-Detect**: When multiple apps play audio simultaneously (e.g. Spotify Desktop and Brave tab), whichever session appears first in GSMTC list wins arbitrarily. | Introduce a target media source priority list (e.g. Spotify Desktop > Web Spotify > Browsers) rather than taking the first active session. |
| **Medium** | [spotify_player.py:423-451](file:///c:/Table%20Of%20Contents/Musics/LyricScript/spotify_player.py#L423-L451) | **Window Title Fallback False Positives**: `_clean_track_info` handles titles without ` - ` by setting title to full window name and artist to `""`. Generic windows (e.g. `Inbox - Gmail` or browser tabs) match as playing songs. | Require a valid `Artist - Title` separator or explicit player keyword before considering a window title a media playback source. |
| **Medium** | [lrclib_client.py:88-95](file:///c:/Table%20Of%20Contents/Musics/LyricScript/lrclib_client.py#L88-L95) | **Non-Atomic Disk Cache Writes**: `_save_disk_cache` uses direct `open(path, "w")`. Rapid song skips or abnormal exit during write causes partial/corrupted JSON cache files. | Write cache entries to a temporary file in `.lyrics_cache/` first, then atomically replace using `os.replace()`. |
| **Medium** | [lrc_parser.py:25-75](file:///c:/Table%20Of%20Contents/Musics/LyricScript/lrc_parser.py#L25-L75) | **Missing LRC `[offset:]` Metadata Parsing**: Standard `.lrc` global timestamp offset tags (e.g. `[offset:+500]`) are ignored, causing persistent timing misalignments for affected tracks. | Parse global `[offset: +/-ms]` tags during header scanning and apply the shift to all timestamp pairs. |
| **Medium** | [animation_engine.py:149-302](file:///c:/Table%20Of%20Contents/Musics/LyricScript/animation_engine.py#L149-L302) | **Unstopped `_scroll_anim` on Rapid Track Skips**: Calling `set_lines()` resets `_scroll_y` to 0 but does not stop `_scroll_anim`. An active scroll animation continues driving scroll y to the previous song's target. | Explicitly stop `self._scroll_anim.stop()` inside `set_lines()` and `set_status()`. |
| **Medium** | [settings_dialog.py:67-717](file:///c:/Table%20Of%20Contents/Musics/LyricScript/settings_dialog.py#L67-L717) | **Settings Live Preview Component Drift**: The preview box uses a basic `QLabel` + `QGraphicsDropShadowEffect`, completely bypassing `LyricsRenderer` and misrepresenting multi-line/opacity behavior. | Embed a scaled instance of `LyricsRenderer` inside the Live Preview frame so preview visuals accurately mirror overlay behavior. |
| **Low** | [lrclib_client.py:67-186](file:///c:/Table%20Of%20Contents/Musics/LyricScript/lrclib_client.py#L67-L186) | **Cache Key Mismatch on Cleaned Titles**: `_cache_key` hashes raw title strings. When step 7 cleans tags (remix/feat/TikTok), results are saved under uncleaned keys, causing duplicate misses on subsequent queries. | Normalize track titles consistently (stripping common noise tags, punctuation, and extra whitespace) before generating cache keys. |
| **Low** | [lrclib_client.py:134-194](file:///c:/Table%20Of%20Contents/Musics/LyricScript/lrclib_client.py#L134-L194) | **60s Failure TTL Blocks Manual Retry**: Failed lookups are stored in `_failure_cache` for 60s. User manual refresh / search retry is ignored if performed within this 60s window. | Invalidate `_failure_cache[key]` whenever a manual refresh, search correction, or track cache purge is triggered. |
| **Low** | [animation_engine.py:98-125](file:///c:/Table%20Of%20Contents/Musics/LyricScript/animation_engine.py#L98-L125) | **Adaptive Contrast Multi-Monitor Coordinate Bug**: `_check_bg_luminance` clamps coordinates with `max(0, pos.x() - 15)`. On monitors located at negative virtual desktop coordinates (e.g. `x = -1920`), sampling clamps to 0 (wrong monitor). | Support negative screen coordinates and multi-monitor geometry when capturing background luminance samples. |

---

## 2. Code Quality & Maintainability Audit

1. **Unresolved `print()` Debug Statements**: `main.py:23-28` prints startup banner directly to stdout using `print()` instead of `log_event()`.
2. **Silent Exception Suppression**:
   - `spotify_player.py`: Bare `except Exception:` / `pass` blocks in D-Bus (`line 722`), Gio (`line 789`), and `playerctl` (`line 814`) backends suppress system error tracebacks.
   - `lrclib_client.py`: Silent `except Exception: pass` during disk cache load (`line 84`), save (`line 94`), and clear (`line 260`, `273`).
   - `settings_manager.py`: Silent fallback on corrupted `settings.json` (`lines 129, 140`) without logging a warning.
3. **Dependency Version Constraints**: `requirements.txt` lacks upper version bounds or exact pins (`PyQt6>=6.4.0`, `requests>=2.28.0`), leaving the codebase vulnerable to upstream breaking changes.
4. **Hardcoded Configuration Constants**: Polling intervals (80ms worker, 50ms GUI timer, 400ms luminance timer) and timeout limits (3.5s HTTP) are scattered across files as magic numbers rather than centralized.
5. **Hotkey Conflict Detection**: `settings_dialog.py` allows users to assign duplicate key sequences to different actions without validation or warning.

---

## 3. Feature Backlog & Enhancement Roadmap

| Feature | Impact | Effort | Technical Notes |
| :--- | :---: | :---: | :--- |
| **Per-Track Sync Offset Persistence** | **High** | **S** | Store track-specific ±ms offsets in a persistent dictionary alongside song title/artist, auto-applying on track change. |
| **Manual Lyric Search & Correction UI** | **High** | **M** | Interactive dialog in Settings/Tray to search LRCLIB manually, view results, and override automatically bound lyrics. |
| **Click-Through / Mouse-Transparent Mode** | **High** | **S** | Toggle `Qt.WindowType.WindowTransparentForInput` flag to allow clicks to pass through overlay to games/desktop. |
| **Auto-Hide on Pause / Idle with Fade** | **High** | **M** | Timer-based fade-out when music is paused or stopped, smoothly fading back in when playback resumes. |
| **Screen Capture Exclusion** | **High** | **S** | Implement `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` on Windows so overlay is hidden from OBS/Discord screenshares. |
| **Target Media Source Priority List** | **Medium** | **M** | User-configurable priority ordering (e.g. Spotify Desktop > Web Spotify > Chrome > Brave) to resolve multi-session audio conflicts. |
| **Word-Level / Karaoke Highlighting** | **Medium** | **L** | Parse word-level timestamp tags `<mm:ss.xx>` and extend `LyricsRenderer` to highlight individual words progressively. |
| **Unsynced Lyrics Smooth Auto-Ticker** | **Medium** | **M** | Implement smooth automatic vertical scrolling for plain text (unsynced) lyrics based on track duration. |
| **Compact Single-Line Ticker Mode** | **Medium** | **S** | Toggleable UI mode collapsing multi-line display into a sleek 1-line horizontal/vertical scrolling ticker. |
| **Windows 11 Mica / Acrylic Backdrop** | **Medium** | **M** | Native DWM composition effect integration (`DwmEnableBlurBehindWindow` / `SetWindowCompositionAttribute`) for translucent glass backdrop. |
| **Start with System Integration** | **Medium** | **S** | Windows Registry key (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`) toggle in Settings dialog. |
| **Disk Cache Viewer & Pruning Control** | **Low** | **S** | UI section displaying total cached songs, disk space used, and buttons to view or prune old cache files. |
| **Copy System Diagnostics Tool** | **Low** | **S** | One-click button in Settings to copy OS version, Python version, PyWin32 availability, active session details, and recent log history. |
| **Custom Theme Builder** | **Low** | **M** | Custom theme creator supporting user-defined text/background/shadow colors saved as custom user presets. |

---

## 4. Checkpoint & Next Steps

> [!IMPORTANT]  
> **Phase 4 Mandatory Stop Gate:** This audit report (`AUDIT.md`) has been generated and saved to the repository root. **No source code implementation has been performed yet.**  
>   
> Please review the audit findings above and select which items (bug fixes, code quality improvements, or features) you would like to prioritize for implementation.
