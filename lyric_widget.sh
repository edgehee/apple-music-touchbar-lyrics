#!/bin/bash
L=$(cat /tmp/current_lyric.txt 2>/dev/null)
# JSON 특수문자(따옴표, 백슬래시) 이스케이프
L="${L//\\/\\\\}"
L="${L//\"/\\\"}"
ICON=""
[ -f /tmp/note_icon.png ] && ICON=',"icon_path":"/tmp/note_icon.png"'
printf '{"text":"%s","font_color":"255,255,255,255","background_color":"0,0,0,0"%s}' "$L" "$ICON"
