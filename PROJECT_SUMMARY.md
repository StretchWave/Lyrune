# Lyrune — Complete Project Overview & Technical Architecture

## 1. Executive Summary
**Lyrune** is an ultra-modern, cross-platform (Windows & Linux) desktop lyrics overlay and standalone audio visualizer system. It detects the currently playing song in real time from **Spotify Desktop, Spotify Web, YouTube Music, and Web Browsers (Brave, Chrome, Edge, Firefox, Opera)**, fetches synchronized timestamped LRC lyrics from **LRCLIB**, and renders them as a sleek, translucent, Spotify-style floating overlay directly on the desktop. It also features a decoupled, standalone floating **Audio Visualizer** with live WASAPI loopback DSP spectral analysis, multi-edge snapping with automatic 90° rotation, a customization studio, and a non-intrusive **Game Overlay Mode** designed for borderless fullscreen gaming.

---

## 2. Tech Stack & Dependencies
- **Language**: Python 3.10+ (Tested up to Python 3.13)
- **GUI & Rendering Framework**: PyQt6 (Qt6) — Custom QPainter-based renderer with QPropertyAnimation, vector drawing, and translucent hardware-accelerated surfaces.
- **Audio DSP & Capture Engine**:
  - **Windows**: Native WASAPI loopback capture (`IAudioClient` / `IAudioCaptureClient` via 64-bit `ctypes`).
  - **Spectral Analysis**: NumPy FFT with logarithmic frequency grouping (32 logarithmic bins spanning 20Hz–20kHz), dynamic range compression, and temporal attack/decay envelope smoothing.
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
│   ├── window_utils.py            # Multi-monitor detection, edge-snapping, 64-bit Win32 Z-guard
│   ├── logger.py                  # Singleton thread-safe event logger with Qt signal emission
│   └── visualizer/                # Standalone Audio Visualizer Subsystem
│       ├── __init__.py            # Package exports (VisualizerManager, VisualizerWindow, etc.)
│       ├── base.py                # BaseVisualizer & BaseAudioSource abstractions
│       ├── audio_source.py        # Native WASAPI loopback & DSP spectral analysis engine
│       ├── bar_visualizer.py      # Rounded bar, pill, and square bar vector renderer
│       ├── visualizer_window.py   # Independent frameless floating visualizer window
│       └── visualizer_manager.py  # Visualizer coordinator, game tracker, and snapshot manager
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
- **Single Instance Enforcement**: Uses a named Windows kernel mutex (`Global\LyruneDesktopWidgetMutex` via `ctypes.windll.kernel32.CreateMutexW`) or a POSIX PID lockfile.
- **Windows Taskbar Integration**: Invokes `SetCurrentProcessExplicitAppUserModelID("stretchwave.lyrune.app.2.0")` for clean taskbar grouping.
- **Warning Suppression**: Selectively filters harmless urllib3/requests version warnings.

### 4.2. `lyrune/lyrics_widget.py` (Desktop Lyrics Overlay)
- **Window Characteristics**: Frameless (`Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus`), translucent (`WA_TranslucentBackground`), non-activating (`WA_ShowWithoutActivating`).
- **Border & Corner Snapping**: Snapping within 50px of any screen boundary respects work areas across multi-monitor setups.
- **Screen Capture Exclusion**: Toggles `SetWindowDisplayAffinity(hwnd, 0x11)` (`WDA_EXCLUDEFROMCAPTURE`) to hide lyrics from OBS / Discord stream captures.
- **Native Z-Guard Engine**: Dynamically monitors and maintains topmost Z-order position above fullscreen games without stealing keyboard focus.

### 4.3. `lyrune/visualizer/` (Standalone Audio Visualizer Subsystem)
- **Independent Floating Window**: `VisualizerWindow` operates as its own top-level window, completely decoupled from `LyricsWidget`.
- **Live WASAPI Loopback DSP**: `AdaptiveAudioSource` captures real Windows loopback audio buffers directly from WASAPI, runs FFT frequency extraction across 32 logarithmic bands, dynamic range compression, and noise floor gating.
- **Edge Snapping & 90° Rotation**:
  - Snapping to screen top/bottom sets horizontal orientation (bars grow upward or downward).
  - Snapping to screen left/right sets vertical orientation (bars grow inward to the right or left).
  - Snapping to screen borders automatically adjusts window dimensions ($L \times T \leftrightarrow T \times L$).
- **Customization Studio**:
  - Bar shapes: *Pill*, *Rounded Bar*, *Square Bar*.
  - Gradient Engine: Multi-stop linear gradients with customizable stops and directions (Vertical, Horizontal, Inward, Outward).
  - Bar count: Auto-calculated by window dimensions or manual override ($8\text{--}128$ bars).
  - Spacing, thickness, base opacity, attack/decay speeds.
- **Game Overlay Mode**:
  - Specialized desktop HUD mode for borderless fullscreen games.
  - Multi-monitor target screen routing (*Active Game Monitor*, *Primary Monitor*, *Monitor X*).
  - Preset screen positions (*Top*, *Bottom*, *Left*, *Right*, *Top-Left*, etc.) with configurable margin slider ($0\text{--}60\text{ px}$).
  - Non-destructive state snapshots: seamlessly preserves user's normal desktop position and settings when toggling Game Overlay Mode (`Ctrl+Shift+G`).

### 4.4. `lyrune/window_utils.py` (Z-Order & Multi-Monitor Utilities)
- **64-bit Win32 Native Interop**: Fully typed `argtypes` and `restype` for `SetWindowPos`, `GetWindowLongW`, `SetWindowLongW`, `GetWindow`, and `GetTopWindow`.
- **Native Styles**: `apply_native_overlay_styles()` configures `WS_EX_TOPMOST`, `WS_EX_TOOLWINDOW`, `WS_EX_LAYERED`, `WS_EX_NOACTIVATE`, and `WS_EX_TRANSPARENT`.
- **Focus Preservation**: All Z-order reassertions use `SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW`.
- **Lightweight Conflict Detection**: `is_window_below_any_topmost()` detects occlusion by borderless games while avoiding internal reassertion competition between Lyrune windows.

---

## 5. Configuration Schema (`settings.json`)

| Setting Key | Default | Description |
|---|---|---|
| `always_on_top` | `true` | Keeps lyrics overlay above all desktop windows |
| `click_through` | `false` | Passes all mouse clicks through lyrics overlay |
| `exclude_from_capture` | `false` | Hides lyrics overlay from OBS / Discord screen captures |
| `visualizer_enabled` | `true` | Standalone audio visualizer master toggle |
| `visualizer_always_on_top` | `true` | Keeps visualizer window topmost |
| `visualizer_click_through` | `false` | Passes mouse clicks through visualizer window |
| `visualizer_exclude_from_capture`| `false` | Hides visualizer from OBS / Discord screen captures |
| `visualizer_overlay_mode` | `"Normal"` | Mode selector: `"Normal"` or `"Game Overlay"` |
| `visualizer_overlay_screen` | `"Active Game Monitor"` | Target display for Game Overlay mode |
| `visualizer_overlay_position` | `"Bottom"` | HUD preset anchor for Game Overlay mode |
| `visualizer_overlay_margin` | `15` | Edge margin distance in pixels for Game Overlay mode |
| `visualizer_style` | `"Pill Bars"` | Visualizer style strategy |
| `visualizer_shape` | `"Pill"` | Bar shape: `"Pill"`, `"Rounded Bar"`, `"Square Bar"` |
| `visualizer_color_mode` | `"Gradient"` | Color rendering mode: `"Solid"`, `"Gradient"`, `"Rainbow"` |
| `visualizer_gradient_stops` | `[...]` | List of `[position, hex_color]` stops for multi-stop gradient |
| `visualizer_gradient_direction` | `"Vertical"` | Direction: `"Vertical"`, `"Horizontal"`, `"Inward"`, `"Outward"` |
| `visualizer_auto_bar_count` | `true` | Automatically computes bar count from window length & thickness |
| `visualizer_bar_count` | `32` | Manual bar count override ($8\text{--}128$) |
| `shortcut_toggle_game_overlay` | `"Ctrl+Shift+G"` | Hotkey to toggle visualizer Game Overlay mode |
| `shortcut_toggle_visualizer` | `"Ctrl+Shift+V"` | Hotkey to show/hide standalone visualizer |

---

## 6. Build & Packaging Pipeline
1. **Asset Generation**: `build_installer.bat` converts `assets/logo.png` to multi-size `assets/logo.ico` using Pillow.
2. **PyInstaller Compilation**: Builds `dist\Lyrune\` containing `Lyrune.exe` with bundled assets and dependencies.
3. **Inno Setup Installer**: Compiles `installer.iss` to produce `dist\Lyrune-Setup-v2.0.0.exe` complete with desktop shortcut, start menu entry, and optional Windows startup launch.
