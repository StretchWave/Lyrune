# Lyrune 🎵

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/UI-PyQt6-green?style=for-the-badge&logo=qt&logoColor=white" alt="PyQt6">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-orange?style=for-the-badge&logo=windows&logoColor=white" alt="Platform">
  <img src="https://img.shields.io/badge/Lyrics-LRCLIB-purple?style=for-the-badge" alt="LRCLIB">
  <img src="https://img.shields.io/badge/License-MIT-brightgreen?style=for-the-badge" alt="License">
</p>

**Lyrune** is a sleek, lightweight desktop lyrics overlay and audio visualizer for **Spotify** and Web Media Players (Brave, Chrome, Edge, Firefox, Zen, Opera). It automatically detects what you're playing, fetches synchronized timestamped lyrics from [LRCLIB](https://lrclib.net), and renders them alongside a real-time, Mel-scale audio visualizer in a modern, frameless, customizable interface.

---

## 🌟 Highlights & Features

- 🎤 **Synchronized LRC Lyrics** — $O(\log n)$ real-time timestamp matching with Spotify-style smooth vertical scrolling and customizable active/context line contrast.
- 📊 **Real-Time Audio Visualizer** — High-resolution 4096-point FFT spectral analysis engine with Mel-scale perceptual frequency grouping, hybrid multi-band AGC, and gradient styling.
- 🎵 **Multi-Source Playback Detection**:
  - **Windows**: Native System Media Transport Controls (WinRT GSMTC) + Window Title fallback.
  - **Linux**: Dynamic MPRIS protocol auto-discovery over D-Bus (`dbus-python`, Gio, `playerctl`).
- 🪟 **Flexible Window Layer Stacking**:
  - **✨ Always on Top (Foreground)**: Pins the overlay and visualizer above all windows and games.
  - **🪟 Normal Window**: Behaves like a standard desktop window.
  - **🖼️ Background / Desktop Layer**: Sits behind all active apps directly on your wallpaper.
- 🎨 **Modern Customizable Styling**:
  - Spotify Dark, Cinematic Cyan, Neon Pink, High Contrast presets.
  - Custom font family, font size, bold toggles, alignment (Left/Center/Right).
  - Background color & opacity, drop shadow, text contour outline.
  - Per-pixel adaptive contrast color inversion over light/dark backgrounds.
- ⚙️ **Rich Behavior Controls**:
  - **Click-Through Mode**: Clicks pass directly through the overlay to underlying windows or games.
  - **Auto-Hide on Pause**: Smoothly hides when media stops/pauses.
  - **Screen Capture Exclusion**: Hides overlay from OBS / Discord screen sharing (`SetWindowDisplayAffinity` on Windows).
  - **Auto-Resize Height**: Dynamically adapts window height to visible context lines.
  - **Track-Specific Timing Nudges**: Adjust lyric offset live with `Ctrl+Left` / `Ctrl+Right`.
- 🔍 **Manual Lyric Search & Correction**: Interactive dialog to query LRCLIB and bind custom lyrics to any track.
- 💾 **Disk & Memory Caching**: Offline persistence for fetched lyrics in `.lyrics_cache/`.

---

## 📦 Installation Guide

### 🐧 For Linux Users

#### 1. One-Line Installer (Recommended)

Open your terminal and run:

```bash
curl -sSL https://raw.githubusercontent.com/StretchWave/Lyrune/main/install.sh | bash
```

Launch Lyrune anytime by running:

```bash
lyrune
```

---

#### 2. Manual / From Source

##### System Prerequisites

| Distribution               | Required System Packages                                                                                             |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **Arch Linux / Manjaro**   | `sudo pacman -S python python-pip python-pyqt6 pulseaudio-utils libpulse pipewire-pulse dbus glib2`                  |
| **Ubuntu / Debian / Mint** | `sudo apt update && sudo apt install python3 python3-pip python3-venv libdbus-1-dev libglib2.0-dev pulseaudio-utils` |
| **Fedora / RHEL**          | `sudo dnf install python3 python3-pip dbus-devel glib2-devel pulseaudio-utils`                                       |

##### Setup Virtual Environment & Run

```bash
git clone https://github.com/StretchWave/Lyrune.git
cd Lyrune

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run Lyrune
python main.py
```

---

### 🪟 For Windows Users (1-Click Executable)

1. Download **`Lyrune-Windows-x64.zip`** from the latest [GitHub Release](https://github.com/StretchWave/Lyrune/releases).
2. Extract the `.zip` folder.
3. Double-click **`Lyrune.exe`** — **No Python or command-line setup required!**

---

## 🪟 Linux Window Manager & Wayland Guide

Lyrune is built with full support for **Wayland** (Hyprland, Sway, KWin, GNOME) and **X11** (i3, bspwm, XFCE).

### 🚀 Hyprland Configuration

Under tiling window managers like **Hyprland**, add the following window rules to your `~/.config/hypr/hyprland.conf` to ensure Lyrune windows float cleanly without tiling:

```ini
# Lyrune Overlay & Visualizer Rules
windowrule {
    name = lyrune-overlay
    match:class = ^(lyrune)$
    float = 1
    no_blur = 1
    border_size = 0
    no_shadow = 1
    no_initial_focus = 1
}
```

_Or using the `windowrulev2` format:_

```ini
windowrulev2 = float, class:^(lyrune)$
windowrulev2 = noblur, class:^(lyrune)$
windowrulev2 = border_size 0, class:^(lyrune)$
windowrulev2 = noinitialfocus, class:^(lyrune)$
```

### 📐 Adjusting Window Size & Position on Linux

1. **Mouse Dragging**: Left-click and drag anywhere on the lyrics background or visualizer to move it freely.
2. **Corner Resize**: Drag the bottom-right corner grip on the lyrics overlay.
3. **Hyprland Direct Resize**: Hold **`Super` + Right-Click Drag** over any Lyrune window to dynamically stretch or shrink it.
4. **Settings Dialog**:
   - Open **Settings** → **Behavior** to set exact pixel widths/heights and use quick position presets (`Center Bottom`, `Center Top`, `Center Screen`, `Reset Default`).
   - Open **Settings** → **Visualizer Studio** to adjust visualizer logical length, thickness, bar width, and edge attachments.
5. **Auto-Persistence**: Coordinates and sizes are automatically remembered and restored from `~/.config/Lyrune/settings.json`.

---

## ⌨️ Default Hotkeys

| Shortcut        | Action                                                   |
| --------------- | -------------------------------------------------------- |
| `Ctrl+H`        | Toggle Lyrics Overlay Visibility                         |
| `Ctrl+Shift+V`  | Toggle Audio Visualizer Visibility                       |
| `Ctrl+Shift+G`  | Toggle Game Overlay Mode (Pinned on active game monitor) |
| `Ctrl+R` / `F5` | Force Refresh / Reload Lyrics for current song           |
| `Ctrl+Left`     | Nudge timing **−250ms** (lyrics appear earlier)          |
| `Ctrl+Right`    | Nudge timing **+250ms** (lyrics appear later)            |

---

## 🛠️ Project Structure

```text
Lyrune/
├── lyrune/                    # Core application package
│   ├── __init__.py            # Package metadata & version
│   ├── __main__.py            # Module CLI entry point (python -m lyrune)
│   ├── main.py                # Main Qt Application setup & System Tray initialization
│   ├── lyrics_widget.py       # Floating transparent overlay window & mouse handlers
│   ├── settings_dialog.py     # Frameless settings dialog with live preview & logs drawer
│   ├── settings_manager.py    # Atomic persistent JSON config manager & debounced save
│   ├── animation_engine.py    # Spotify-style custom QPainter smooth scrolling engine
│   ├── lrclib_client.py       # LRCLIB API client, search fallback & disk cache manager
│   ├── spotify_player.py      # Cross-platform media playback detector (WinRT / MPRIS)
│   ├── lrc_parser.py          # Fast bisect-based LRC timestamp parser
│   ├── logger.py              # Thread-safe RLock logger & live diagnostic listener
│   ├── ui_theme.py            # Dark palette, qtawesome vector icons & custom widgets
│   ├── window_utils.py        # Multi-monitor geometry, snapping, & Hyprland/Wayland IPC
│   └── visualizer/            # Real-time audio visualizer subsystem
│       ├── __init__.py        # Visualizer exports
│       ├── audio_source.py    # PipeWire/PulseAudio parec capture & AudioDSP FFT engine
│       ├── bar_visualizer.py  # QPainter Pill/Bar renderer with spring physics
│       ├── visualizer_window.py # Independent floating visualizer window
│       └── visualizer_manager.py # Multi-monitor game overlay & layout coordinator
├── main.py                    # Root entry point launcher
├── Lyrune.spec                # PyInstaller onedir build config
├── Lyrune-Standalone.spec     # PyInstaller single-file build config
├── pyproject.toml             # PEP 517 build & packaging definition
├── requirements.txt           # Python dependencies list
├── install.sh                 # Linux one-line installer script
├── installer.iss              # Windows Inno Setup installer script
├── .github/workflows/         # CI/CD: builds Windows & Linux release artifacts on tags
├── CHANGELOG.md               # Version history
├── AUDIT.md                   # Code audit & roadmap
├── LICENSE                    # MIT License
└── README.md                  # Project documentation
```

---

## 📦 Building Releases

```bash
# Package onedir release for Linux:
pyinstaller --noconfirm --onedir --windowed --name "Lyrune" main.py
tar -czvf Lyrune-Linux-x64.tar.gz -C dist/Lyrune .

# Package standalone release for Windows:
pyinstaller --noconfirm Lyrune-Standalone.spec
```

---

## 🤝 Contributing

Contributions, bug reports, and feature requests are welcome!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for details.
