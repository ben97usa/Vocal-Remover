#!/bin/zsh
# Rebuild StemSplitter on a (new) Apple Silicon Mac.
# Usage: ./setup.sh            (uses python3.12 from PATH, or PYTHON=/path/to/python3.12)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
export PATH="/opt/homebrew/bin:$PATH"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.12 /opt/homebrew/bin/python3.12 /opt/anaconda3/bin/python3.12; do
    command -v "$c" >/dev/null 2>&1 && { PY="$(command -v "$c")"; break; }
  done
fi
[ -z "$PY" ] && { echo "Python 3.12 not found. Install: brew install python@3.12"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg not found. Install: brew install ffmpeg"; exit 1; }

echo "Using $PY"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
mkdir -p models
# Models (~2 GB) are downloaded automatically by audio-separator into ./models on first use.
"$DIR/tools/make_app.sh"
echo "Done. Double-click StemSplitter on the Desktop to start."
