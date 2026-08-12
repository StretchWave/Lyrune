# LyricScript 🎵

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/UI-PyQt6-green?style=for-the-badge&logo=qt&logoColor=white" alt="PyQt6">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-orange?style=for-the-badge&logo=windows&logoColor=white" alt="Platform">
  <img src="https://img.shields.io/badge/Lyrics-LRCLIB-purple?style=for-the-badge" alt="LRCLIB">
  <img src="https://img.shields.io/badge/License-MIT-brightgreen?style=for-the-badge" alt="License">
</p>

**LyricScript** is a sleek, lightweight desktop lyrics overlay for **Spotify** and Web Media Players (Brave, Chrome, Edge, Firefox, Opera). It automatically detects what you're playing, fetches synchronized timestamped lyrics from [LRCLIB](https://lrclib.net), and presents them in a modern, frameless, Spotify-styled overlay.

---

## 🌟 Highlights & Features

- 🎤 **Synchronized LRC Lyrics** — O(log n) real-time timestamp matching with Spotify-style smooth vertical scrolling.
- 🎵 **Multi-Source Playback Detection**:
  - **Windows**: Native System Media Transport Controls (WinRT GSMTC) + Window Title fallback.
  - **Linux**: MPRIS protocol over D-Bus (`dbus-python`, Gio, `playerctl`).
- 🎨 **Modern Customizable Overlay**:
  - Spotify Dark, Cinematic Cyan, Neon Pink, High Contrast presets.
  - Custom font family, font size, bold toggles, alignment (Left/Center/Right).
  - Background color & opacity, drop shadow, text contour outline.
  - Per-pixel adaptive contrast color inversion over light/dark backgrounds.
- ⚙️ **Rich Behavior Controls**:
  - **Click-Through Mode**: Clicks pass through the overlay to games/desktop.
  - **Auto-Hide on Pause**: Smoothly hides when media stops/pauses.
  - **Screen Capture Exclusion**: Hides overlay from OBS / Discord screen sharing (`SetWindowDisplayAffinity`).
  - **Auto-Resize Height**: Dynamically adapts window height to visible context lines.
  - **Track-Specific Timing Nudges**: Adjust lyric offset live with `Ctrl+Left` / `Ctrl+Right`.
- 🔍 **Manual Lyric Search & Correction**: Interactive dialog to query LRCLIB and bind custom lyrics to any track.
- 💾 **Disk & Memory Caching**: Offline persistence for fetched lyrics in `.lyrics_cache/`.

---

## 📦 Easy Installation (Zero Setup Needed)

### 🪟 For Windows Users (1-Click Executable)

1. Download **`LyricScript-Windows-x64.zip`** from the latest [GitHub Release](https://github.com/StretchWave/LyricScript/releases).
2. Extract the `.zip` folder.
3. Double-click **`LyricScript.exe`** — **No Python or command-line required!**

---

### 🐧 For Linux Users (One-Line Installer)

Open your terminal and run this single command:

```bash
curl -sSL https://raw.githubusercontent.com/StretchWave/LyricScript/main/install.sh | bash
```

Launch LyricScript anytime by typing:
```bash
lyricscript
```

---

### 🐍 For Python Developers (`pip`)

```bash
pip install lyricscript
```

Or run directly from source:
```bash
git clone https://github.com/StretchWave/LyricScript.git
cd LyricScript
pip install -r requirements.txt
python main.py
```

3. **Install Requirements:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch Application:**
   ```bash
   python main.py
   ```

---

### Option 3: Building a Standalone `.exe` for Windows (No Python Needed)

You can freeze LyricScript into a portable single-file executable using **PyInstaller**:

1. **Install PyInstaller:**
   ```bash
   pip install pyinstaller
   ```

2. **Build Portable Executable:**
   ```bash
   pyinstaller --noconfirm --onedir --windowed --name "LyricScript" main.py
   ```

3. Find your ready-to-run package in `dist/LyricScript/LyricScript.exe`!

---

## 🚀 Usage Guide

1. **Launch LyricScript** — The app starts minimized in your **System Tray** (bottom right near clock).
2. **Play Music** — Start playing any track on Spotify Desktop or supported web browser.
3. **Control & Customize**:
   - Right-click the **System Tray Icon** or overlay to open **Settings**.
   - Drag to reposition (when unlocked); resize using bottom-right corner grip.

### ⌨️ Default Hotkeys

| Shortcut | Action |
|---|---|
| `Ctrl+H` | Toggle Overlay Visibility |
| `Ctrl+R` / `F5` | Force Refresh / Reload Lyrics for current song |
| `Ctrl+Left` | Nudge timing **−250ms** (lyrics appear earlier) |
| `Ctrl+Right` | Nudge timing **+250ms** (lyrics appear later) |

---

## 🛠️ Project Structure

```text
LyricScript/
├── lyricscript/               # Core application package
│   ├── __init__.py            # Package metadata & version
│   ├── __main__.py            # Module CLI entry point (python -m lyricscript)
│   ├── main.py                # Main Qt Application setup & System Tray initialization
│   ├── lyrics_widget.py       # Floating transparent overlay window & mouse event handlers
│   ├── settings_dialog.py     # Frameless settings dialog with live preview & logs drawer
│   ├── settings_manager.py    # Atomic persistent JSON config manager & debounced save
│   ├── animation_engine.py    # Spotify-style custom QPainter smooth scrolling engine
│   ├── lrclib_client.py       # LRCLIB API client, search fallback & disk cache manager
│   ├── spotify_player.py      # Cross-platform media playback detector (WinRT / MPRIS)
│   ├── lrc_parser.py          # Fast bisect-based LRC timestamp parser
│   ├── logger.py              # Thread-safe RLock logger & live diagnostic listener
│   └── ui_theme.py            # Dark Slate palette, qtawesome vector icons & custom widgets
├── main.py                    # Root entry point launcher
├── pyproject.toml             # Standard PEP 517 build & packaging definition
├── requirements.txt           # Python dependencies list
└── README.md                  # Project documentation
```

---

## 🤝 Contributing

Contributions, bug reports, and feature requests are welcome!
1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for details.
