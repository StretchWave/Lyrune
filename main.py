import sys
import warnings

# Suppress harmless urllib3 / requests dependency warnings
warnings.filterwarnings("ignore")

from PyQt6.QtWidgets import QApplication
from lyrics_widget import LyricsWidget

def main():
    """
    Main entry point for LyricScript Desktop Widget.
    Runs in background system tray.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("LyricScript Desktop Widget")
    app.setQuitOnLastWindowClosed(False)

    widget = LyricsWidget()
    widget.show()

    # Use ASCII-safe output for cp1252 Windows consoles
    print("==================================================================")
    print("[*] LyricScript Desktop Widget is running!")
    print("[*] Access Settings, toggle Always-on-Top, or Exit by right-clicking")
    print("    the icon in your Windows System Tray (bottom right near clock).")
    print("[*] Keyboard shortcut: Ctrl+Shift+L to toggle visibility.")
    print("==================================================================")

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
