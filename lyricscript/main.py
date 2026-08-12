import sys
import warnings

# Suppress harmless urllib3 / requests dependency warnings (targeted, not blanket)
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"urllib3")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"requests")

from PyQt6.QtWidgets import QApplication
from lyricscript.lyrics_widget import LyricsWidget
from lyricscript.logger import log_event

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

    log_event("==================================================================")
    log_event("[*] LyricScript Desktop Widget is running!")
    log_event("[*] Access Settings, toggle Always-on-Top, or Exit by right-clicking")
    log_event("    the icon in your Windows System Tray (bottom right near clock).")
    log_event("[*] Keyboard shortcut: Ctrl+H to toggle visibility.")
    log_event("==================================================================")

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
