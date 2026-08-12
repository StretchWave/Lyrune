#!/usr/bin/env bash
# Lyrune Linux One-Line Installer

set -e

echo "🎵 Installing Lyrune..."

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required. Please install python3 first."
    exit 1
fi

INSTALL_DIR="$HOME/.local/share/Lyrune"
BIN_DIR="$HOME/.local/bin"

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

echo "📦 Cloning Lyrune repository..."
if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull
else
    git clone https://github.com/StretchWave/Lyrune.git "$INSTALL_DIR"
fi

echo "🐍 Setting up virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Create launcher script in ~/.local/bin
cat << 'EOF' > "$BIN_DIR/lyrune"
#!/usr/bin/env bash
SCRIPT_DIR="$HOME/.local/share/Lyrune"
exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
EOF

chmod +x "$BIN_DIR/lyrune"

echo "✅ Lyrune successfully installed!"
echo "👉 Run 'lyrune' from your terminal to launch."
