# Changelog — Lyrune

All notable changes to the Lyrune project are documented in this file.

## [2.0.0] - 2026-08-12 — Lyrune (renamed from LyricScript)

The first release under the **Lyrune** name. Earlier 2.x changelog entries below were recorded under the old *LyricScript* name.

### Changed
- **Project renamed to Lyrune**: the app ships as the `lyrune` Python package; documentation, installers, and release artifacts all use the Lyrune name.
- **Packaged layout**: application modules moved into the `lyrune/` package with a thin root `main.py` entry point (`python main.py` or `python -m lyrune`).
- **Settings storage**: config now lives in `%APPDATA%/Lyrune` (Windows) or `~/.config/Lyrune` (Linux).
- **GitHub Releases**: the CI workflow builds and attaches `Lyrune-Windows-x64.zip`, `Lyrune-Standalone-x64.exe`, and `Lyrune-Linux-x64.tar.gz` on version tags.

### Fixed
- **Settings dialog footer buttons**: the OK button no longer renders as invisible dark-on-dark text — the footer's inline stylesheet created a Qt style-sheet boundary that broke the `btn_primary` green styling.
- **Overlay hover jitter**: the hover border is now painter-drawn and auto-resize-height defers while the pointer is over the overlay, so the window stays put under the cursor.
- **Release pipeline**: fixed the CI entry point (`lyricscript/main.py` → `main.py`) that would have failed every release build.

### Housekeeping
- Removed duplicate root-level modules and tracked bytecode/cache files; cleaned unused imports; added MIT `LICENSE` and a release-ready `.gitignore`.

## [2.1.3] - 2026-08-12

### Fixed
- **Manual Search Dialog TypeError**: Added a public `search_lyrics(artist, title)` method to `LRCLibClient` in [lrclib_client.py](file:///c:/Table%20Of%20Contents/Musics/LyricScript/lrclib_client.py#L236-L252) and updated `_do_search()` in [settings_dialog.py](file:///c:/Table%20Of%20Contents/Musics/LyricScript/settings_dialog.py#L183-L198), fixing the argument keyword collision (`TypeError: _api_search() got multiple values for argument 'artist'`).

## [2.1.2] - 2026-08-12

### Fixed
- **Settings Dialog Media Source Enumeration**: Added `get_active_media_sessions()` alias to `SpotifyPlayer` in [spotify_player.py](file:///c:/Table%20Of%20Contents/Musics/LyricScript/spotify_player.py#L320-L325) and updated `_refresh_media_sources()` in [settings_dialog.py](file:///c:/Table%20Of%20Contents/Musics/LyricScript/settings_dialog.py#L753-L765) to safely check both `get_available_media_sources()` and `get_active_media_sessions()`, resolving the `AttributeError` crash when opening Settings.

---

## [2.1.1] - 2026-08-12

### Fixed (Settings Dialog De-AI Pass — Round 2)
- **De-AI Icon Cleanup**: Replaced `ph.sparkle` on the Animations tab with `ph.wave-sine` motion wave line icon, and replaced `ph.text-aa` on the Typography tab with thin vector line icon `ph.text-t` (`ui_theme.py`).
- **Selective Accent Color**: Tab icons are now neutral (`text_secondary`) at rest, highlighting with `accent` amber ONLY on the active selected tab. Fixed static "Theme Presets:" text to neutral `text_primary` (`settings_dialog.py`).
- **Input Border QSS Refinement**: Input/dropdown hover border changed to neutral `text_secondary`, ensuring accent amber appears strictly on keyboard `:focus` (`ui_theme.py`).
- **Qt Ampersand Mnemonic Escaping**: Escaped ampersands as `&&` in Qt labels (`Behavior && Source`, `Show Song Title && Artist Sub-label`, `Context Lines (Before && After):`), restoring visible `&` characters on screen (`settings_dialog.py`).
- **Distinct Action Icons**: Gave the "OK" button a distinct checkmark icon (`ph.check`) separate from "Apply"'s floppy-disk icon (`settings_dialog.py`).

---

## [2.1.0] - 2026-08-12

### Fixed (Bugs & Architectural Risks)
- **COM Lifecycle & Thread Safety**: Handled `HRESULT` return codes for `CoInitializeEx` on Windows in `MediaWorkerThread`, ensuring `CoUninitialize` is only called when COM was initialized by the worker thread (`spotify_player.py`).
- **WinRT Session Manager Recovery**: Added automatic manager reset (`self._gsm_manager = None`) on exception to recover from stale Windows Media service handles (`spotify_player.py`).
- **LRCLIB Search Match Validation**: Introduced title token similarity validation in `_api_search()` to prevent fuzzy search from binding lyrics to wrong tracks with identical single-word titles (`lrclib_client.py`).
- **Thread-Safe Logging**: Wrapped all logger state mutations (`history`, `_last_message`, `_suppressed_count`, `_seen_keys`) inside `with self._lock:` blocks in `AppLogger` (`logger.py`).
- **App Data Config Migration**: Settings are now saved to `%APPDATA%/Lyrune/settings.json` (or `~/.config/Lyrune/settings.json`) with legacy local file migration and `aboutToQuit` exit hooks (`settings_manager.py`).
- **Atomic Cache & Settings Writes**: Replaced raw file writes with temporary file generation + `os.replace` atomic commits for disk cache (`lrclib_client.py`) and settings (`settings_manager.py`).
- **LRC `[offset:]` Tag Support**: Added parsing for LRC header `[offset: +/-ms]` metadata tags, shifting all timestamps dynamically (`lrc_parser.py`).
- **Animation Fighting Prevention**: Explicitly stopped running `_scroll_anim` instances when new lyric lines or status messages are set (`animation_engine.py`).
- **Multi-Monitor Luminance Sampling**: Extended screen grab logic to support negative coordinates and multi-monitor screen geometry (`animation_engine.py`).
- **Settings Live Preview Component Parity**: Embedded actual `LyricsRenderer` instance in Settings dialog preview container, eliminating rendering drift (`settings_dialog.py`).
- **Window Title False Positives**: Required valid `Artist` and `Title` parts to avoid misidentifying generic non-music windows as active tracks (`spotify_player.py`).

### Changed (Code Quality & Maintainability)
- Replaced raw console `print()` calls in `main.py` with structured `log_event()` logging.
- Added upper version bounds to `requirements.txt` (`PyQt6<7.0.0`, `requests<3.0.0`, `qtawesome<2.0.0`).
- Added duplicate hotkey detection in `settings_dialog.py` to warn when conflicting shortcuts are assigned.

### Added (Features & Enhancements)
- **Per-Track Persistent Sync Offset**: Persistent ±ms timing nudges stored per track ID (`settings_manager.py`, `lyrics_widget.py`).
- **Click-Through Mode**: Toggleable mouse-transparent overlay mode (`Qt.WindowType.WindowTransparentForInput`) in Settings and Tray Menu.
- **Screen Capture Exclusion**: Option to exclude overlay from OBS, Discord, and Windows screen recordings using `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` on Windows.
- **Auto-Hide on Pause**: Optional auto-hiding when playback is paused or stopped.
- **Copy System Diagnostics**: 1-click diagnostic report exporter in Settings (OS, Python/PyQt6 versions, active target source, cache count, recent logs).
