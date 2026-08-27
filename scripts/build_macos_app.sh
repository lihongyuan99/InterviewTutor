#!/bin/bash

# 构建 macOS .app 应用包（含品牌图标 icns，双击即可启动桌面模式）
# 产物：dist/InterviewTutor.app
# 说明：.app 内嵌本项目绝对路径，移动项目目录后需重新运行本脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
APP_NAME="InterviewTutor"
ICON_PNG="$PROJECT_DIR/assets/icon.png"
ICON_SVG="$PROJECT_DIR/assets/icon.svg"
APP_ROOT="$PROJECT_DIR/dist"
APP_DIR="$APP_ROOT/${APP_NAME}.app"
CONTENTS="$APP_DIR/Contents"

# 优先从 SVG 源重新渲染 PNG（更新图标后只需重跑此脚本）
# qlmanage 会强制白底 + 裁掉边距，故改用 Chrome headless 渲染并保留透明通道
ICON_SRC="$ICON_PNG"
if [ -f "$ICON_SVG" ]; then
    echo "🔄 从 $ICON_SVG 重新渲染 PNG（Chrome headless，保透明）..."
    CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if [ -x "$CHROME" ]; then
        "$CHROME" --headless=new --screenshot="$ICON_PNG" \
            --window-size=1024,1024 --default-background-color=00000000 \
            --hide-scrollbars "file://$ICON_SVG" >/dev/null 2>&1
    else
        # 回退：qlmanage（会强制白底，仅作兜底）
        echo "⚠️  未找到 Chrome，回退到 qlmanage（会强制白底）"
        mkdir -p "$APP_ROOT"
        qlmanage -t -s 1024 -o "$APP_ROOT" "$ICON_SVG" >/dev/null
        mv "$APP_ROOT/$(basename "$ICON_SVG").png" "$ICON_PNG"
    fi
elif [ ! -f "$ICON_SRC" ]; then
    echo "❌ 缺少图标源文件：$ICON_SVG 或 $ICON_PNG"
    exit 1
fi

echo "🏗️  构建 $APP_DIR ..."

# ===== 1. 生成 icns（多分辨率图标集）=====
ICONSET="$APP_ROOT/AppIcon.iconset"
rm -rf "$ICONSET" "$APP_DIR"
mkdir -p "$ICONSET" "$CONTENTS/Resources" "$CONTENTS/MacOS"

for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$CONTENTS/Resources/AppIcon.icns"
rm -rf "$ICONSET"

# ===== 2. Info.plist =====
cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>InterviewTutor</string>
    <key>CFBundleDisplayName</key><string>InterviewTutor</string>
    <key>CFBundleIdentifier</key><string>com.interviewtutor.desktop</string>
    <key>CFBundleVersion</key><string>1.0.0</string>
    <key>CFBundleShortVersionString</key><string>1.0.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>InterviewTutor</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
</dict>
</plist>
PLIST

# ===== 3. 启动器（内嵌项目绝对路径）=====
cat > "$CONTENTS/MacOS/$APP_NAME" <<LAUNCHER
#!/bin/bash
# 本文件由 scripts/build_macos_app.sh 生成；移动项目目录后请重新生成
exec "$PROJECT_DIR/tutor/bin/python" "$PROJECT_DIR/desktop.py"
LAUNCHER
chmod +x "$CONTENTS/MacOS/$APP_NAME"

echo "✅ 构建完成：$APP_DIR"
echo "   双击启动，或执行：open \"$APP_DIR\""
echo "   提示：可将其拖入 Dock 右侧或 Command+拖拽到桌面建立替身"
