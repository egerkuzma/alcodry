#!/bin/sh
# Собирает alcodry.app и alcodry.dmg. Нужны только Command Line Tools —
# ни Xcode, ни сторонних зависимостей.
set -e
cd "$(dirname "$0")"

APP=build/alcodry.app
rm -rf build
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -swift-version 5 -target arm64-apple-macos13 \
       -o "$APP/Contents/MacOS/alcodry" Sources/main.swift -framework Cocoa

cp Info.plist "$APP/Contents/Info.plist"
cp Resources/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

# Подпись «для себя»: на Apple Silicon без неё бинарник просто не запустится.
# Для нотаризации нужен платный Apple Developer, домашнему приложению ни к чему.
codesign --force --sign - "$APP"

mkdir -p build/dmg
cp -R "$APP" build/dmg/
ln -s /Applications build/dmg/Applications
hdiutil create -volname alcodry -srcfolder build/dmg -ov -quiet -format UDZO build/alcodry.dmg
rm -rf build/dmg

echo "готово:"
echo "  $(pwd)/$APP"
echo "  $(pwd)/build/alcodry.dmg"
