#!/bin/zsh
# Create ~/Applications/StemSplitter.app (+ Desktop alias) that runs start.sh from this folder.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/StemSplitter.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/StemSplitter" <<EOS
#!/bin/zsh
exec "$ROOT/start.sh"
EOS
chmod +x "$APP/Contents/MacOS/StemSplitter"
cat > "$APP/Contents/Info.plist" <<'EOS'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>StemSplitter</string>
<key>CFBundleDisplayName</key><string>StemSplitter</string>
<key>CFBundleIdentifier</key><string>local.stemsplitter</string>
<key>CFBundleExecutable</key><string>StemSplitter</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1.0</string>
<key>LSUIElement</key><true/>
</dict></plist>
EOS
cp "$ROOT/tools/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
ln -sfn "$APP" "$HOME/Desktop/StemSplitter.app"
echo "Launcher: $APP"
