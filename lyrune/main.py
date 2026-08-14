import os
import sys
import warnings

# Suppress harmless urllib3 / requests dependency warnings (targeted, not blanket)
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"urllib3")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"requests")

from PyQt6.QtWidgets import QApplication  # noqa: E402 (warnings filter above must run first)
from lyrune.lyrics_widget import LyricsWidget  # noqa: E402
from lyrune.logger import log_event  # noqa: E402


def _check_single_instance():
    """Enforce single instance of Lyrune.

    On Windows: uses a named kernel mutex (survives across consoles/sessions).
    On other platforms: uses a PID lockfile in the user config directory.

    Returns a handle/path that must be kept alive for the process lifetime,
    or calls sys.exit(0) if another instance is already running.
    """
    if sys.platform == "win32":
        import ctypes
        mutex_name = "Global\\LyruneDesktopWidgetMutex"
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        ERROR_ALREADY_EXISTS = 183
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            print("[Lyrune] Another instance is already running. Exiting.")
            sys.exit(0)
        return handle  # Must keep reference alive
    else:
        # Lockfile-based approach for Linux/macOS
        config_dir = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        lock_dir = os.path.join(config_dir, 'Lyrune')
        os.makedirs(lock_dir, exist_ok=True)
        lock_path = os.path.join(lock_dir, 'lyrune.lock')

        if os.path.exists(lock_path):
            try:
                with open(lock_path, 'r') as f:
                    old_pid = int(f.read().strip())
                # Check if old process is still alive
                os.kill(old_pid, 0)
                # Process exists — another instance is running
                print("[Lyrune] Another instance is already running. Exiting.")
                sys.exit(0)
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                pass  # Stale lockfile, proceed

        with open(lock_path, 'w') as f:
            f.write(str(os.getpid()))

        import atexit
        atexit.register(lambda: os.remove(lock_path) if os.path.exists(lock_path) else None)
        return lock_path


def main():
    """
    Main entry point for Lyrune Desktop Widget.
    Runs in background system tray.
    """
    # Enforce single instance before creating the GUI
    _instance_lock = _check_single_instance()  # noqa: F841 (must keep reference alive)

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("stretchwave.lyrune.app.2.0")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Lyrune Desktop Widget")
    app.setDesktopFileName("lyrune")          # Sets WM_CLASS for compositor window rules
    app.setQuitOnLastWindowClosed(False)

    from lyrune.ui_theme import get_app_icon
    app.setWindowIcon(get_app_icon())

    widget = LyricsWidget()
    widget.show()

    log_event("==================================================================")
    log_event("[*] Lyrune Desktop Widget is running!")
    log_event("[*] Access Settings, toggle Always-on-Top, or Exit by right-clicking")
    log_event("    the icon in your Windows System Tray (bottom right near clock).")
    log_event("[*] Keyboard shortcut: Ctrl+H to toggle visibility.")
    log_event("==================================================================")

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
