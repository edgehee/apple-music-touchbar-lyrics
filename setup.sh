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

# python3 확인 — colorthief/pillow(앨범색 추출)가 설치된 인터프리터를 골라야 함.
# /usr/bin/python3(시스템)엔 보통 없으므로 Homebrew python 우선.
PYTHON=""
for cand in /usr/local/bin/python3 /opt/homebrew/bin/python3 "$(command -v python3)"; do
    if [ -x "$cand" ] && "$cand" -c "import colorthief, PIL" 2>/dev/null; then
        PYTHON="$cand"; break
    fi
done
if [ -z "$PYTHON" ]; then
    # 의존성이 깔린 python이 없으면, Homebrew python에 자동 설치 시도
    echo "==> colorthief/pillow 미설치 — 자동 설치 시도"
    for cand in /usr/local/bin/python3 /opt/homebrew/bin/python3 "$(command -v python3)"; do
        if [ -x "$cand" ]; then
            echo "    $cand 에 설치 중..."
            "$cand" -m pip install --user colorthief pillow syncedlyrics 2>/dev/null \
              || "$cand" -m pip install colorthief pillow syncedlyrics 2>/dev/null || true
            if "$cand" -c "import colorthief, PIL" 2>/dev/null; then
                PYTHON="$cand"; break
            fi
        fi
    done
fi
if [ -z "$PYTHON" ]; then
    echo "ERROR: colorthief/pillow 설치 실패. 수동 설치하세요:"
    echo "       /usr/local/bin/python3 -m pip install colorthief pillow syncedlyrics"
    exit 1
fi
echo "==> python3 확인: $PYTHON ($($PYTHON --version))"

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
        <string>$PYTHON</string>
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
echo "  2. Touch Bar 탭 → + → Shell Script / Task Widget"
echo "  3. Script 입력:"
echo "     bash /Users/$USERNAME/lyrics_bar/lyric_widget.sh"
echo "  4. 위젯 이름(Widget Name)을 반드시  Lyrics  로 지정"
echo "     (데몬이 이 이름으로 위젯을 자동 탐색해 연결함)"
echo "  5. Update Interval: 0.5초 / 배경색 투명"
echo "──────────────────────────────────────────"
