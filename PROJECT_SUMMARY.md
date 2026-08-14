# Lyrune — Complete Project Overview & Technical Architecture

## 1. Executive Summary
**Lyrune** is an ultra-modern, cross-platform (Windows & Linux) desktop lyrics overlay widget. It detects the currently playing song in real time from **Spotify Desktop, Spotify Web, YouTube Music, and Web Browsers (Brave, Chrome, Edge, Firefox, Opera)**, fetches synchronized timestamped LRC lyrics from **LRCLIB**, and renders them as a sleek, translucent, always-on-top, Spotify-style floating overlay directly on the desktop.

---

## 2. Tech Stack & Dependencies
- **Language**: Python 3.10+ (Tested up to Python 3.13)
- **GUI & Rendering Framework**: PyQt6 (Qt6) — Custom QPainter-based renderer with QPropertyAnimation and transclucent hardware-accelerated surfaces.
- **Media Session Interfacing**:
  - **Windows**: `winrt-Windows.Media.Control` (GSMTC - Global System Media Transport Controls) + `pywin32` (win32gui window title fallback).
  - **Linux**: `dbus-python` / `Gio` / `playerctl` (MPRIS D-Bus interface).
- **Networking & API**: `requests` interacting with [LRCLIB](https://lrclib.net).
- **Packaging & Installation**: `PyInstaller` (.spec configurations) + `Inno Setup` (`installer.iss` for Windows setup wizard).

---

## 3. Project Directory Structure
```
LyricScript/
├── assets/
│   ├── logo.png                   # High-res master application logo
│   └── logo.ico                   # Multi-resolution Windows icon (16x16 to 256x256)
├── lyrune/                        # Core Python Package
│   ├── __init__.py                # Version (__version__ = "2.0.0") and app metadata
│   ├── __main__.py                # Package execution entry point
│   ├── main.py                    # App bootstrap, single-instance mutex, AppUserModelID
│   ├── lyrics_widget.py           # Main overlay window, tray icon, snap math, event handlers
│   ├── animation_engine.py        # QPainter Spotify-style renderer, vertical scroll animation
│   ├── spotify_player.py          # Windows WinRT GSMTC & Linux MPRIS playback engine
│   ├── lrclib_client.py           # LRCLIB client with memory & disk cache + async worker
│   ├── lrc_parser.py              # LRC timestamp parser with binary search time synchronization
│   ├── settings_manager.py        # Atomic JSON persistence (%APPDATA%/Lyrune), debounced writes
│   ├── settings_dialog.py         # Frameless settings window, live preview, diagnostics log
│   ├── ui_theme.py                # Custom widgets (ToggleSwitch, ValueSlider, ColorSwatch, etc.)
│   └── logger.py                  # Singleton thread-safe event logger with Qt signal emission
├── build_installer.bat            # One-click PyInstaller + Inno Setup build script
├── installer.iss                  # Inno Setup Windows installer configuration
├── Lyrune.spec                    # PyInstaller directory distribution spec
├── Lyrune-Standalone.spec         # PyInstaller single-executable spec
├── pyproject.toml                 # PEP 517/518 build metadata & dependencies
├── requirements.txt               # Direct pip requirements
├── settings.json                  # Active user configuration schema
└── README.md                      # Public documentation and feature guide
```

---

## 4. Detailed Module Architecture

### 4.1. `lyrune/main.py` (Application Lifecycle & Single Instance)
- **Single Instance Enforcement**: Uses a named Windows kernel mutex (`Global\LyruneDesktopWidgetMutex` via `ctypes.windll.kernel32.CreateMutexW`) or a POSIX PID lockfile. If an instance is already running, subsequent launches terminate silently with exit code 0.
- **Windows Taskbar Integration**: Invokes `SetCurrentProcessExplicitAppUserModelID("stretchwave.lyrune.app.2.0")` so Windows taskbar groups windows correctly under the custom logo instead of generic `python.exe`.
- **Warning Suppression**: Selectively filters harmless urllib3/requests version warnings.

### 4.2. `lyrune/lyrics_widget.py` (Desktop Overlay & Window Logic)
- **Window Characteristics**: Frameless (`Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool`), translucent (`WA_TranslucentBackground`), mouse tracking enabled.
- **Border & Corner Snapping**: When dragging the overlay and releasing within 50px of any screen boundary:
  - Snapping to left/right side keeps the current vertical Y position.
  - Snapping to top/bottom edge keeps the current horizontal X position.
  - Snapping near both axes positions the window flush in the corner.
- **Auto-Hide on Pause/Stop**: Automatically hides the overlay when playback pauses, stops, or Spotify closes, and restores visibility when playback resumes (while respecting manual `Ctrl+H` toggle).
- **Auto-Resize Height**: Dynamically fits the window height to the visible context lines, deferred during mouse hover so the window surface never jumps under the cursor.
- **Screen Capture Exclusion**: Toggles `SetWindowDisplayAffinity(hwnd, 0x11)` (`WDA_EXCLUDEFROMCAPTURE`) with fallback to `0x01` (`WDA_MONITOR`) to exclude lyrics from OBS / Discord stream captures.
- **3-Stage Retry Logic**: If lyrics are slow/loading, triggers 3 automatic retries at 3-second intervals, displaying contextual status: `"Lyrics not found"` (404/empty) vs `"Lyrics aren't being loaded"` (timeout/connection failure).

### 4.3. `lyrune/animation_engine.py` (LyricsRenderer)
- **Custom Spotify-Style Renderer**: Custom Qt QWidget executing vector drawing via `QPainter` with antialiasing and subpixel layout calculation.
- **Smooth Vertical Scroll**: Driven by `QPropertyAnimation` over `scroll_y_prop` using cubic easing curves (`InOutCubic`).
- **High-Contrast Text Contour Outline**: Generates an 8-direction contour stroke around the active line to ensure crisp legibility over bright, colorful, or complex wallpapers.
- **Drop Shadows & Opacity Hierarchy**: Active line displays at user-defined opacity (`active_line_opacity`); context lines smoothly fall off proportionally based on line distance from active line.
- **Adaptive Contrast Inversion**: A 400ms background timer samples desktop luminance behind the overlay and automatically switches text color between dark (`#111111`) and light (`#FFFFFF`).

### 4.4. `lyrune/spotify_player.py` (Media Engine)
- **Windows WinRT GSMTC**: Communicates asynchronously with Windows Global System Media Transport Controls running inside a dedicated `MediaWorkerThread` (QThread) with proper COM lifecycle management (`CoInitializeEx` / `CoUninitialize`).
- **Target Media Source Routing**: Can auto-detect the active player or lock specifically to a chosen browser tab or desktop application (e.g. Brave, Chrome, Edge, Spotify.exe).
- **Window Title Fallback**: Secondary win32gui scraper that reads browser tab names (`Title - Artist - Browser`) when GSMTC is unavailable.
- **Track Metadata Cleaner**: Cleans track noise (removes `[Official Video]`, `(Remix)`, ` - TikTok`, feat tags, browser titles).

### 4.5. `lyrune/lrclib_client.py` & `lrc_parser.py` (Lyrics Fetching & Sync)
- **Multi-Tier API Lookup**:
  1. In-Memory Cache (Instant O(1)).
  2. Disk Cache (`%APPDATA%/Lyrune/.lyrics_cache/<hash>.json`).
  3. LRCLIB Exact Query (`/api/get?artist_name=...&track_name=...`).
  4. LRCLIB Fuzzy Query (`/api/search?q=...`).
  5. Swapped Artist/Title Query.
  6. Cleaned / Stripped Regex Query.
- **Parser Engine**: Parses timestamp tags `[mm:ss.xx]` and performs binary search lookup (`bisect_right`) against live playback position.

### 4.6. `lyrune/settings_manager.py` & `settings_dialog.py` (Settings & UI)
- **Atomic Disk Writes**: Saves JSON settings to APPDATA via temporary file replacement (`os.replace`) to eliminate file corruption.
- **Settings Dialog UI**:
  - Custom frameless title bar with Now Playing preview pill and window controls.
  - Tabbed sidebar navigation: *Appearance*, *Typography*, *Behavior & Source*, *Animations*, *Shortcuts*, *Advanced & Cache*.
  - Live preview canvas showing instant visual feedback.
  - Dynamic live linking of Active & Context opacity sliders.
  - Manual lyric search & binding dialog (`ManualSearchDialog`).
  - Real-time diagnostic console log with copy tools.

---

## 5. Configuration Schema (`settings.json`)

| Setting Key | Default | Description |
|---|---|---|
| `font_family` | `"Segoe UI"` | Font family for lyric text rendering |
| `font_size` | `24` | Font size in points (12 to 48 pt) |
| `font_bold` | `true` | Bold typography toggle |
| `text_color` | `"#FFFFFF"` | Primary lyric text color |
| `bg_color` | `"#000000"` | Background container color |
| `bg_opacity` | `0` | Background container opacity percentage (0 to 100%) |
| `border_enabled` | `false` | Overlay window subtle 1px border toggle |
| `shadow_enabled` | `true` | Drop shadow rendering toggle |
| `shadow_color` | `"#000000"` | Drop shadow color |
| `shadow_blur` | `8` | Shadow blur radius in pixels (0 to 30 px) |
| `text_align` | `"Center"` | Text alignment: `"Left"`, `"Center"`, `"Right"` |
| `show_song_info` | `true` | Visibility of "Artist - Title" sub-label |
| `always_on_top` | `true` | Keeps overlay above all desktop windows |
| `lock_position` | `false` | Locks window position against mouse dragging |
| `window_width` | `800` | Overlay width in pixels |
| `window_height` | `220` | Overlay height in pixels |
| `window_x` / `window_y` | `-1` | Saved screen coordinates (-1 for default center) |
| `selected_media_source`| `"Auto-Detect"`| Target media source session ID |
| `sync_offset_ms` | `0` | Global timing nudge in milliseconds (-5000 to +5000 ms) |
| `context_lines` | `2` | Number of context lines shown before and after active line |
| `auto_resize_height` | `true` | Auto-fits overlay height to context lines |
| `animation_speed_ms` | `400` | Duration of vertical scroll animation in milliseconds |
| `adaptive_color` | `false` | Smart desktop luminance contrast color inversion |
| `active_text_outline` | `true` | 8-directional contour outline on active lyric |
| `active_line_opacity` | `100` | Opacity percentage of active playing lyric |
| `context_line_opacity`| `45` | Opacity percentage of surrounding context lyrics |
| `link_opacity_levels` | `true` | Scales context opacity proportionally with active opacity |
| `shortcut_toggle_overlay`| `"Ctrl+H"`| Hotkey to show/hide lyrics overlay |
| `shortcut_refresh` | `"Ctrl+R"` | Hotkey to reload lyrics |
| `shortcut_nudge_minus`| `"Ctrl+Left"`| Hotkey to nudge sync earlier (-250ms) |
| `shortcut_nudge_plus` | `"Ctrl+Right"`| Hotkey to nudge sync later (+250ms) |
| `click_through` | `false` | Passes all mouse clicks through overlay |
| `auto_hide_on_pause` | `false` | Auto-hides overlay when media is paused/stopped |
| `exclude_from_capture`| `false` | Hides overlay from OBS / Discord screen captures |
| `track_sync_offsets` | `{}` | Persistent per-song timing offset dictionary |
| `snap_to_corners` | `false` | Snaps overlay to screen borders & corners on release |

---

## 6. Build & Packaging Pipeline
1. **Asset Generation**: `build_installer.bat` converts `assets/logo.png` to multi-size `assets/logo.ico` using Pillow.
2. **PyInstaller Compilation**: Builds `dist\Lyrune\` containing `Lyrune.exe` with bundled assets and dependencies.
3. **Inno Setup Installer**: Compiles `installer.iss` to produce `dist\Lyrune-Setup-v2.0.0.exe` complete with desktop shortcut, start menu entry, and optional Windows startup launch.
