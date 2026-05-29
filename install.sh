#!/bin/bash
# ============================================================
#  Apple Music Touch Bar Lyrics — 원클릭 설치 스크립트
#  사용법:
#    git clone https://github.com/edgehee/apple-music-touchbar-lyrics.git ~/lyrics_bar
#    bash ~/lyrics_bar/install.sh
# ============================================================
set -e

REPO="https://github.com/edgehee/apple-music-touchbar-lyrics.git"
DIR="$HOME/lyrics_bar"

echo "🎵  Apple Music Touch Bar Lyrics 설치"
echo "────────────────────────────────────────"

# 0) macOS 확인
if [ "$(uname)" != "Darwin" ]; then
    echo "❌ 이 프로그램은 macOS 전용입니다."; exit 1
fi

# 1) 저장소가 없으면 clone
if [ ! -f "$DIR/lyrics_daemon.py" ]; then
    echo "==> 저장소 받기: $DIR"
    git clone "$REPO" "$DIR"
fi
cd "$DIR"

# 2) python3 확인 (없으면 안내)
if ! command -v python3 &>/dev/null && [ ! -x /usr/local/bin/python3 ] && [ ! -x /opt/homebrew/bin/python3 ]; then
    echo "❌ python3가 없습니다. 먼저 설치하세요:  brew install python"
    exit 1
fi

# 3) 의존성 + LaunchAgent 등록 (setup.sh가 처리: colorthief/pillow 자동설치 포함)
echo "==> 의존성 설치 + 자동시작 등록"
bash "$DIR/setup.sh"

# 4) BetterTouchTool 설치 여부 확인 (없으면 안내만)
if ! mdfind "kMDItemCFBundleIdentifier == 'com.hegenberg.BetterTouchTool'" 2>/dev/null | grep -q . \
   && [ ! -d "/Applications/BetterTouchTool.app" ] && [ ! -d "$HOME/Applications/BetterTouchTool.app" ]; then
    echo ""
    echo "⚠️  BetterTouchTool이 설치되어 있지 않습니다."
    echo "    터치바 표시는 BTT가 담당하므로 반드시 필요합니다:"
    echo "    → https://folivora.ai 에서 설치 (유료, 체험 가능)"
fi

echo ""
echo "✅ 설치 완료!  마지막 한 단계 — BTT 위젯 만들기:"
echo "────────────────────────────────────────"
echo "  1. BetterTouchTool 열기 → Touch Bar 탭 → All Apps(모든 앱) 선택"
echo "  2. +  →  Shell Script / Task Widget"
echo "  3. Script 칸:   bash $DIR/lyric_widget.sh"
echo "  4. 위젯 이름(Widget Name)을  Lyrics  로 지정  ← 필수!"
echo "  5. Update Interval 0.5초 / 배경 투명 / 왼쪽 정렬"
echo "────────────────────────────────────────"
echo "  문제가 생기면  $DIR/RECOVERY.md  참고"
