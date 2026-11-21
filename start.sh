#!/bin/zsh
# Mở StemSplitter: chạy server nếu chưa chạy, rồi mở trình duyệt.
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:$PATH"
URL="http://127.0.0.1:7861"
if ! curl -s -o /dev/null "$URL"; then
  cd "$DIR"
  NO_BROWSER=1 nohup "$DIR/.venv/bin/python" "$DIR/server.py" > "$DIR/app.log" 2>&1 &
  for i in {1..60}; do curl -s -o /dev/null "$URL" && break; sleep 1; done
fi
open "$URL"
