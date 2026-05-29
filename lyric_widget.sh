#!/bin/bash
# BTT 폴백 폴링 스크립트. 평소엔 데몬 push가 표시를 담당하고,
# 이 스크립트는 0.5s마다 /tmp 파일을 읽어 같은 내용을 출력(데몬이 죽어도 표시 유지).
L=$(cat /tmp/current_lyric.txt 2>/dev/null)
L="${L//\\/\\\\}"
L="${L//\"/\\\"}"
ICON=""
[ -f /tmp/note_icon.png ] && ICON=',"icon_path":"/tmp/note_icon.png"'
printf '{"text":"%s","font_color":"255,255,255,255","background_color":"0,0,0,0"%s}' "$L" "$ICON"
