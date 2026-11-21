#!/bin/zsh
# Tắt StemSplitter (giải phóng RAM)
PIDS=$(lsof -ti tcp:7861 -sTCP:LISTEN)
if [ -n "$PIDS" ]; then kill $PIDS && echo "Đã tắt StemSplitter."; else echo "StemSplitter không chạy."; fi
