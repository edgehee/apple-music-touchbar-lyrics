#!/bin/bash
# lyrics_bar 설치 스크립트
# 실행: bash ~/lyrics_bar/setup.sh

set -e

PLIST="$HOME/Library/LaunchAgents/com.lyricsbar.daemon.plist"
SCRIPT="$HOME/lyrics_bar/lyrics_daemon.py"
USERNAME=$(whoami)

echo "==> lyrics_bar 설치 시작 (사용자: $USERNAME)"

# 실행 권한 부여
chmod +x "$SCRIPT"

# python3 확인
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3가 없습니다. 'brew install python' 또는 Xcode CLI 도구를 설치하세요."
    exit 1
fi
echo "==> python3 확인: $(python3 --version)"

# LaunchAgent plist 생성
cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lyricsbar.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/$USERNAME/lyrics_bar/lyrics_daemon.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>/tmp/lyricsbar_out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/lyricsbar_err.log</string>
</dict>
</plist>
EOF

echo "==> LaunchAgent plist 생성: $PLIST"

# 이미 로드된 경우 언로드 후 재로드
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "✅ 설치 완료!"
echo ""
echo "데몬 상태 확인: launchctl list | grep lyricsbar"
echo "로그 확인:      tail -f /tmp/lyricsbar.log"
echo "가사 확인:      cat /tmp/current_lyric.txt"
echo ""
echo "──────────────────────────────────────────"
echo "다음 단계: BetterTouchTool 위젯 설정"
echo ""
echo "  1. BetterTouchTool 열기"
echo "  2. Touch Bar → Add Widget → Shell Script / Task Widget"
echo "  3. Script 입력:"
echo '     cat /tmp/current_lyric.txt 2>/dev/null || echo "♪"'
echo "  4. Refresh Interval: 500ms"
echo "  5. 폰트/배경색 자유롭게 설정"
echo "──────────────────────────────────────────"
