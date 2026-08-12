import warnings

# Suppress harmless urllib3 / requests dependency warnings (targeted, not blanket)
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"urllib3")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"requests")

from lyrune.main import main  # noqa: E402 (warnings filter above must run first)

if __name__ == "__main__":
    main()
