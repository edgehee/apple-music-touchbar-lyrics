#!/usr/bin/env python3
"""
lyrics_daemon.py
Apple Music 재생 위치를 추적하고 lrclib.net(+syncedlyrics)에서 LRC 가사를 가져와
/tmp/current_lyric.txt (가사) 와 /tmp/current_color.txt (앨범색) 에 기록.
앨범색으로 음표 아이콘 PNG(/tmp/note_icon.png)도 생성.
BTT 위젯이 이 파일들을 읽어 [앨범색 음표 + 흰 가사]를 터치바에 표시.
"""

import subprocess
import json
import os
import re
import urllib.request
import urllib.parse
import time
import sys
import logging
import colorsys
from typing import Optional, List, Tuple

CACHE_DIR = os.path.expanduser("~/lyrics_bar/cache")
LYRIC_FILE = "/tmp/current_lyric.txt"
COLOR_FILE = "/tmp/current_color.txt"
NOTE_ICON = "/tmp/note_icon.png"
ART_FILE = "/tmp/album_art_btt.jpg"
LOG_FILE = "/tmp/lyricsbar.log"
FONT_PATH = "/System/Library/Fonts/Apple Symbols.ttf"
# 위젯 이름(BTT UI에서 이 이름으로 만들면 데몬이 자동으로 UUID를 찾아 연결).
# BTT가 초기화돼도 같은 이름으로 위젯만 다시 만들면 코드 수정 없이 복구됨.
BTT_WIDGET_NAME = "Lyrics"
# 자동 탐색 실패 시 폴백으로 쓰는 마지막으로 알려진 UUID.
BTT_WIDGET_UUID = "609EACFB-40DB-4AAB-904C-7B355C7237A9"
_BTT_PUSH_SCRIPT = "/tmp/btt_push.applescript"
# 표시 파이프라인 지연(위치읽기+push ≈ 0.46s) 보정용 미리보기 초.
# 가사가 늦게 뜨면 늘리고, 너무 빨리 뜨면 줄이세요.
LEAD_SECONDS = 0.5

os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

_current_color = "255,255,255,255"
_current_rgb = (230, 230, 230)

# 가사 이미지 렌더링 설정
LYRIC_IMG = "/tmp/lyric_img.png"
SCALE = 2                       # 레티나 2배
TEXT_PT = 16                    # 글자 크기(pt)
BAR_H_PT = 30                   # 터치바 위젯 높이(pt)
LYRIC_FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
LYRIC_FONT_INDEX = 2            # 굵은 가중치 (0~ : 가는것→굵은것)


def generate_note_icon(rgb: Tuple[int, int, int]):
    """앨범색 ♪ 음표 PNG 생성 (폴백용)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        r, g, b = rgb
        img = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        font = ImageFont.truetype(FONT_PATH, 34)
        d.text((6, 2), "♪", font=font, fill=(r, g, b, 255))
        img.save(NOTE_ICON)
    except Exception as e:
        logging.debug(f"generate_note_icon: {e}")


def render_lyric_image(text: str):
    """[앨범색 ♪] + [흰 굵은 가사] 를 이미지로 렌더 → LYRIC_IMG.
    커스텀 폰트/굵기/색을 자유롭게 쓰기 위해 텍스트를 이미지로 그림."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        r, g, b = _current_rgb
        H = BAR_H_PT * SCALE
        size = TEXT_PT * SCALE
        try:
            font = ImageFont.truetype(LYRIC_FONT, size, index=LYRIC_FONT_INDEX)
        except Exception:
            font = ImageFont.truetype(LYRIC_FONT, size)
        note_font = ImageFont.truetype(FONT_PATH, size)

        measure = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        nw = measure.textlength("♪", font=note_font)
        gap = 7 * SCALE
        tw = measure.textlength(text, font=font) if text else 0
        W = max(int(nw + gap + tw + 12 * SCALE), 40 * SCALE)

        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        ascent, descent = font.getmetrics()
        y = (H - (ascent + descent)) // 2
        d.text((2, y), "♪", font=note_font, fill=(r, g, b, 255))
        if text:
            d.text((int(nw) + gap, y), text, font=font, fill=(255, 255, 255, 255))
        img.save(LYRIC_IMG)
    except Exception as e:
        logging.debug(f"render_lyric_image: {e}")


def save_album_art() -> bool:
    """현재 트랙 앨범아트를 파일로 저장."""
    script = f'''
tell application "Music"
    if player state is playing or player state is paused then
        try
            set d to raw data of artwork 1 of current track
            set f to open for access "{ART_FILE}" with write permission
            set eof f to 0
            write d to f
            close access f
        end try
    end if
end tell
'''
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        return os.path.exists(ART_FILE)
    except Exception:
        return False


def get_album_color() -> str:
    """앨범 아트에서 밝고 선명한 색 추출 → 'r,g,b,255'. _current_rgb도 갱신."""
    global _current_rgb
    default = (230, 230, 230)
    if not save_album_art() or not os.path.exists(ART_FILE):
        _current_rgb = default
        generate_note_icon(default)
        return "230,230,230,255"
    try:
        from colorthief import ColorThief
        palette = ColorThief(ART_FILE).get_palette(color_count=8, quality=1)
        best, best_score = None, -1
        for r, g, b in palette:
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            score = s * 0.6 + v * 0.4
            if v > 0.35 and s > 0.25 and score > best_score:
                best_score, best = score, (r, g, b)
        if best is None:
            best = max(palette, key=lambda c: sum(c))
        r, g, b = best
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if v < 0.6:  # 너무 어두우면 밝기 보정
            r2, g2, b2 = colorsys.hsv_to_rgb(h, s, 0.85)
            r, g, b = int(r2 * 255), int(g2 * 255), int(b2 * 255)
        _current_rgb = (r, g, b)
        generate_note_icon((r, g, b))
        return f"{r},{g},{b},255"
    except Exception as e:
        logging.debug(f"get_album_color: {e}")
        _current_rgb = default
        generate_note_icon(default)
        return "230,230,230,255"


def resolve_widget_uuid() -> Optional[str]:
    """BTT에 등록된 트리거 중 BTT_WIDGET_NAME 위젯을 찾아 UUID 반환.
    BTT가 초기화돼 위젯을 다시 만들어도(같은 이름) 코드 수정 없이 연결됨."""
    global BTT_WIDGET_UUID
    script = 'tell application "BetterTouchTool" to get_triggers'
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=6)
        data = json.loads(r.stdout)
    except Exception as e:
        logging.warning(f"resolve_widget_uuid: {e}")
        return None
    if not isinstance(data, list):
        return None
    name_l = BTT_WIDGET_NAME.lower()
    fallback = None
    for t in data:
        if not isinstance(t, dict):
            continue
        uuid = t.get("BTTUUID")
        if not uuid:
            continue
        # 쉘 스크립트 위젯(642) 우선, 이름이 일치하면 즉시 채택
        nm = (t.get("BTTWidgetName") or t.get("BTTTriggerName") or "").lower()
        if name_l in nm:
            if t.get("BTTTriggerType") == 642:
                BTT_WIDGET_UUID = uuid
                logging.info(f"위젯 UUID 자동탐색 성공: {uuid} ({t.get('BTTWidgetName')})")
                return uuid
            fallback = fallback or uuid
    if fallback:
        BTT_WIDGET_UUID = fallback
        logging.info(f"위젯 UUID(이름매칭, 타입미확인): {fallback}")
        return fallback
    logging.warning(f"'{BTT_WIDGET_NAME}' 위젯을 BTT에서 못 찾음 — 폴백 UUID 사용")
    return None


def push_to_btt(text: str):
    """가사 줄이 바뀌는 즉시 BTT 위젯에 직접 push (텍스트 + 앨범색 음표 아이콘)."""
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    icon = f' icon_path "{NOTE_ICON}"' if os.path.exists(NOTE_ICON) else ""
    script = (f'tell application "BetterTouchTool" to update_touch_bar_widget '
              f'"{BTT_WIDGET_UUID}" text "{safe}"{icon}')
    try:
        with open(_BTT_PUSH_SCRIPT, "w", encoding="utf-8") as f:
            f.write(script)
        subprocess.run(["osascript", _BTT_PUSH_SCRIPT], capture_output=True, timeout=3)
    except Exception as e:
        logging.debug(f"push_to_btt: {e}")


def write_files(text: str):
    """가사 + 색상 파일 기록(폴백) + BTT 즉시 push."""
    try:
        with open(LYRIC_FILE, "w", encoding="utf-8") as f:
            f.write(text)
        with open(COLOR_FILE, "w", encoding="utf-8") as f:
            f.write(_current_color)
    except Exception as e:
        logging.debug(f"write_files: {e}")
    push_to_btt(text)


def get_music_state() -> Optional[dict]:
    script = """
    tell application "Music"
        if player state is playing or player state is paused then
            set pos to player position
            set t to name of current track
            set ar to artist of current track
            set al to album of current track
            return (pos as string) & "|||" & t & "|||" & ar & "|||" & al
        else
            return "stopped"
        end if
    end tell
    """
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=4)
        raw = r.stdout.strip()
        if raw == "stopped" or not raw:
            return None
        parts = raw.split("|||")
        if len(parts) < 4:
            return None
        return {"position": float(parts[0]), "track": parts[1],
                "artist": parts[2], "album": parts[3]}
    except Exception as e:
        logging.warning(f"get_music_state: {e}")
        return None


def parse_lrc(lrc_text: str) -> List[Tuple[float, str]]:
    lines = []
    for line in lrc_text.split("\n"):
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", line)
        if m:
            ts = int(m.group(1)) * 60 + float(m.group(2))
            lines.append((ts, m.group(3).strip()))
    return sorted(lines, key=lambda x: x[0])


def get_lyric_at(lines: List[Tuple[float, str]], position: float) -> str:
    current = ""
    for ts, text in lines:
        if ts <= position:
            current = text
        else:
            break
    return current


def _norm(s: str) -> set:
    """이름을 소문자 영숫자 토큰 집합으로 정규화 (아티스트 비교용)."""
    return set(re.findall(r"[a-z0-9가-힣]+", (s or "").lower()))


def _artist_ok(result_artist: str, expected: str) -> bool:
    """검색 결과 아티스트가 기대 아티스트와 충분히 겹치는지 확인."""
    a, b = _norm(result_artist), _norm(expected)
    if not a or not b:
        return False
    return len(a & b) > 0  # 토큰 하나라도 겹치면 동일 아티스트로 인정


def _lrclib(url: str, expected_artist: Optional[str] = None) -> Optional[str]:
    """expected_artist 주어지면 검색 결과 중 아티스트 일치하는 것만 채택."""
    try:
        req = urllib.request.Request(url, headers={"Lrclib-Client": "LyricsBar/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
        if isinstance(data, list):
            for item in data:
                s = item.get("syncedLyrics") or ""
                if not s.strip():
                    continue
                if expected_artist and not _artist_ok(item.get("artistName", ""), expected_artist):
                    continue  # 엉뚱한 동명 곡 방지
                return s
            return None
        s = data.get("syncedLyrics") or ""
        return s.strip() or None
    except urllib.error.HTTPError:
        return None
    except Exception as e:
        logging.warning(f"lrclib: {e}")
        return None


def fetch_lrc(artist: str, track: str, album: str) -> Optional[str]:
    cache_key = re.sub(r"[^\w\-]", "_", f"{artist}_{track}")[:100]
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.lrc")
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            c = f.read()
        return c if c != "NO_LYRICS" else None

    logging.info(f"Fetching lyrics: {artist} - {track}")
    synced = _lrclib("https://lrclib.net/api/get?" + urllib.parse.urlencode(
        {"artist_name": artist, "track_name": track, "album_name": album}))
    if not synced:
        synced = _lrclib("https://lrclib.net/api/get?" + urllib.parse.urlencode(
            {"artist_name": artist, "track_name": track}))
    if not synced:  # 검색 폴백 — 아티스트 일치하는 결과만 채택
        synced = _lrclib("https://lrclib.net/api/search?" + urllib.parse.urlencode(
            {"q": f"{track} {artist}"}), expected_artist=artist)
    if not synced:
        synced = _lrclib("https://lrclib.net/api/search?" + urllib.parse.urlencode(
            {"q": track}), expected_artist=artist)
    if not synced:
        try:
            import syncedlyrics
            synced = (syncedlyrics.search(f"{artist} {track}")
                      or syncedlyrics.search(f"{track} {artist}"))
            # 주의: track만으로는 검색 안 함 (엉뚱한 동명곡 방지)
        except Exception as e:
            logging.debug(f"syncedlyrics: {e}")

    if synced:
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(synced)
        logging.info(f"Cached: {artist} - {track}")
        return synced
    with open(cache_file, "w") as f:
        f.write("NO_LYRICS")
    logging.info(f"No synced lyrics: {artist} - {track}")
    return None


def truncate(text: str, n: int = 120) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def main():
    global _current_color
    current_track_id = None
    lrc_lines: List = []
    last_text = None

    _current_color = "230,230,230,255"
    generate_note_icon((230, 230, 230))
    resolve_widget_uuid()  # 시작 시 위젯 UUID 자동 탐색
    write_files("")
    logging.info("lyrics_daemon started")

    loops = 0
    while True:
        # 위젯이 아직 없거나 재생성된 경우 대비해 주기적으로(약 30초) 재탐색
        loops += 1
        if loops % 300 == 0:
            resolve_widget_uuid()

        state = get_music_state()

        if state is None:
            if current_track_id is not None:
                write_files("")
                current_track_id = None
                lrc_lines = []
                last_text = None
            time.sleep(0.5)
            continue

        track_id = f"{state['artist']}|||{state['track']}"
        if track_id != current_track_id:
            current_track_id = track_id
            last_text = None
            _current_color = get_album_color()
            logging.info(f"색상 {_current_color}: {state['artist']} - {state['track']}")
            write_files("")
            lrc_text = fetch_lrc(state["artist"], state["track"], state["album"])
            lrc_lines = parse_lrc(lrc_text) if lrc_text else []

        title_artist = truncate(f"{state['track']} - {state['artist']}", 80)
        if lrc_lines:
            lyric = get_lyric_at(lrc_lines, state["position"] + LEAD_SECONDS)
            # 가사 줄이 있으면 가사, 간주/인트로(빈 줄)면 제목-아티스트
            text = truncate(lyric) if lyric else title_artist
        else:
            text = title_artist

        if text != last_text:
            last_text = text
            write_files(text)

        time.sleep(0.1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        write_files("")
        sys.exit(0)
