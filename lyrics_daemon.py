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
import ssl
from typing import Optional, List, Tuple

# Homebrew python은 시스템 CA가 없어 lrclib SSL 인증이 실패할 수 있음.
# certifi 인증서로 검증 컨텍스트를 만들어 모든 https 요청에 사용 (없으면 기본값).
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = None

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
LEAD_SECONDS = 0.3         # 살짝 빠르게(가사가 노래보다 아주 조금 먼저)

# ===== 효과 설정 (끄려면 False) =====
KARAOKE = True             # 가사가 노래 진행에 맞춰 단어/글자별로 차오름 (발라드는 자동으로 끔)
NOTE_ANIM = True           # 음표 아이콘 ♪♫♬♩ 애니메이션
NOTE_SYMBOLS = ["♪", "♫", "♬", "♩"]
NOTE_FRAMES = [f"/tmp/note_{i}.png" for i in range(len(NOTE_SYMBOLS))]

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
    """앨범색 음표 PNG들 생성.
    NOTE_FRAMES[i] = 각 음표 심볼(♪♫♬♩, 살짝 크기 펄스), NOTE_ICON = 폴백용 기본."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        r, g, b = rgb
        for i, sym in enumerate(NOTE_SYMBOLS):
            size = 34 if i % 2 == 0 else 29   # 짝/홀 프레임 크기 차이로 펄스 느낌
            font = ImageFont.truetype(FONT_PATH, size)
            img = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.text((6, 2 + (34 - size) // 2), sym, font=font, fill=(r, g, b, 255))
            img.save(NOTE_FRAMES[i])
            if i == 0:
                img.save(NOTE_ICON)  # 폴백 스크립트/기본용
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


def push_to_btt(text: str, icon_path: str = NOTE_ICON):
    """BTT 위젯에 직접 push (텍스트 + 지정한 음표 프레임 아이콘)."""
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    icon = f' icon_path "{icon_path}"' if icon_path and os.path.exists(icon_path) else ""
    script = (f'tell application "BetterTouchTool" to update_touch_bar_widget '
              f'"{BTT_WIDGET_UUID}" text "{safe}"{icon}')
    try:
        with open(_BTT_PUSH_SCRIPT, "w", encoding="utf-8") as f:
            f.write(script)
        subprocess.run(["osascript", _BTT_PUSH_SCRIPT], capture_output=True, timeout=3)
    except Exception as e:
        logging.debug(f"push_to_btt: {e}")


def write_files(text: str, icon_path: str = NOTE_ICON):
    """가사 + 색상 파일 기록(폴백) + BTT 즉시 push."""
    try:
        with open(LYRIC_FILE, "w", encoding="utf-8") as f:
            f.write(text)
        with open(COLOR_FILE, "w", encoding="utf-8") as f:
            f.write(_current_color)
    except Exception as e:
        logging.debug(f"write_files: {e}")
    push_to_btt(text, icon_path)


def get_music_state() -> Optional[dict]:
    script = """
    tell application "Music"
        if player state is playing or player state is paused then
            set pos to player position
            set t to name of current track
            set ar to artist of current track
            set al to album of current track
            set ps to (player state as string)
            set gn to (genre of current track)
            return (pos as string) & "|||" & t & "|||" & ar & "|||" & al & "|||" & ps & "|||" & gn
        else
            return "stopped"
        end if
    end tell
    """
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=6)
        raw = r.stdout.strip()
        if raw == "stopped" or not raw:
            return None
        parts = raw.split("|||")
        if len(parts) < 4:
            return None
        playing = (len(parts) >= 5 and "play" in parts[4].lower())
        genre = parts[5] if len(parts) >= 6 else ""
        return {"position": float(parts[0]), "track": parts[1],
                "artist": parts[2], "album": parts[3],
                "playing": playing, "genre": genre}
    except Exception as e:
        logging.warning(f"get_music_state: {e}")
        return None


# 가사가 아니라 제작진 크레딧인 줄 (作词:/作曲:/编曲:/작사:/Produced by: 등)
_CREDIT_RE = re.compile(
    r"^\s*("
    r"作\s*词|作\s*詞|作\s*曲|编\s*曲|編\s*曲|制\s*作|製\s*作|监\s*制|監\s*製|"
    r"混\s*音|母\s*带|录\s*音|錄\s*音|和\s*声|和\s*聲|出\s*品|发\s*行|發\s*行|"
    r"작사|작곡|편곡|프로듀[서스]|"
    r"lyrics?|composed?|composer|arrang(?:e|ed|er)|produced?|producer|"
    r"mix(?:ed|ing)?|master(?:ed|ing)?|written|music|vocals?|guitars?|"
    r"bass|drums?|piano|engineer"
    r")\b.*[:：]",
    re.IGNORECASE,
)


def _is_credit(text: str) -> bool:
    return bool(text) and bool(_CREDIT_RE.match(text))


def parse_lrc(lrc_text: str) -> List[Tuple[float, str]]:
    lines = []
    for line in lrc_text.split("\n"):
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", line)
        if m:
            ts = int(m.group(1)) * 60 + float(m.group(2))
            txt = m.group(3).strip()
            if _is_credit(txt):
                continue  # 제작진 크레딧 줄은 가사로 표시하지 않음
            lines.append((ts, txt))
    return sorted(lines, key=lambda x: x[0])


def get_lyric_at(lines: List[Tuple[float, str]], position: float) -> str:
    current = ""
    for ts, text in lines:
        if ts <= position:
            current = text
        else:
            break
    return current


# 이 시간(초) 이상 가사 없이 비는 구간(간주/인트로)에만 제목-아티스트 표시
GAP_TITLE_THRESHOLD = 3.0

# 발라드/잔잔한 장르 (Apple Music 장르 태그는 부정확해서 보조용으로만 사용)
BALLAD_GENRES = ["발라드", "ballad", "어쿠스틱", "acoustic"]

# 가사 밀도(초당 단어 수) 기준 — 이 값 이상이면 빠른 곡(카라오케), 미만이면 발라드(전체줄).
# 장르 태그가 엉터리(발라드도 K-Pop으로 표기)라, 실제 가사 속도로 판단하는 게 더 정확함.
FAST_WPS_THRESHOLD = 1.4


def is_ballad(genre: str) -> bool:
    g = (genre or "").lower()
    return any(k in g for k in BALLAD_GENRES)


def is_fast_song(lines: List[Tuple[float, str]]) -> bool:
    """가사 밀도로 빠른 곡(랩/팝) 여부 판단. 정보 부족하면 True(기본 카라오케)."""
    texts = [(ts, t) for ts, t in lines if t]
    if len(texts) < 4:
        return True
    span = texts[-1][0] - texts[0][0]
    if span <= 0:
        return True
    words = sum(len(t.split()) for _, t in texts)
    return (words / span) >= FAST_WPS_THRESHOLD


def song_wps(lines: List[Tuple[float, str]]) -> float:
    """로그용 초당 단어 수."""
    texts = [(ts, t) for ts, t in lines if t]
    if len(texts) < 2:
        return 0.0
    span = texts[-1][0] - texts[0][0]
    if span <= 0:
        return 0.0
    return sum(len(t.split()) for _, t in texts) / span


def _karaoke_reveal(text: str, frac: float) -> str:
    """진행률 frac(0~1)만큼 가사를 공개. 단어 단위(공백 있으면)·글자 단위(없으면)."""
    frac = max(0.0, min(1.0, frac / 0.75))  # 줄 구간 앞 75%에서 다 공개되도록
    words = text.split(" ")
    if len(words) > 1:
        n = max(1, int(round(len(words) * frac)))
        return " ".join(words[:n])
    # 공백 없는 한 덩어리 → 글자 단위로 공개
    n = max(1, int(round(len(text) * frac)))
    return text[:n]


def get_display_at(lines: List[Tuple[float, str]], position: float, karaoke: bool = True):
    """현재 위치에 표시할 내용을 결정.
    - 가사 줄이 진행 중   → 그 가사 텍스트 (karaoke면 진행률만큼 공개)
    - 짧은 쉼(3초 미만)   → "" (그냥 쉼, 음표만)
    - 긴 간주(3초 이상)   → None (호출측에서 제목-아티스트 표시)
    """
    if not lines:
        return None
    cur_ts, cur_text, cur_idx = None, "", -1
    for i, (ts, text) in enumerate(lines):
        if ts <= position:
            cur_ts, cur_text, cur_idx = ts, text, i
        else:
            break
    if cur_text:
        if not karaoke:
            return cur_text
        # 이 줄의 시간 창(다음 줄 시작까지)에서 진행률 계산
        next_ts = lines[cur_idx + 1][0] if cur_idx + 1 < len(lines) else cur_ts + 4.0
        dur = max(0.4, next_ts - cur_ts)
        return _karaoke_reveal(cur_text, (position - cur_ts) / dur)
    # 빈 줄(쉼) 구간 — 다음 '실제 가사'까지의 간격으로 길이 판단
    next_lyric_ts = None
    for ts, text in lines:
        if ts > position and text:
            next_lyric_ts = ts
            break
    if next_lyric_ts is None:
        return None  # 곡 끝/아웃트로 → 제목-아티스트
    gap_start = cur_ts if cur_ts is not None else 0.0
    gap_len = next_lyric_ts - gap_start
    return None if gap_len >= GAP_TITLE_THRESHOLD else ""


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
        with urllib.request.urlopen(req, timeout=6, context=_SSL_CTX) as resp:
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


_no_lyrics_session = set()  # 이번 실행에서 가사 못 찾은 곡 (디스크엔 안 남김 → 재시작 시 재시도)


def fetch_lrc(artist: str, track: str, album: str) -> Optional[str]:
    cache_key = re.sub(r"[^\w\-]", "_", f"{artist}_{track}")[:100]
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.lrc")
    if cache_key in _no_lyrics_session:
        return None
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            c = f.read()
        if c == "NO_LYRICS":
            os.remove(cache_file)  # 예전 영구 실패 캐시 정리 → 아래서 재시도
        else:
            return c

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
    _no_lyrics_session.add(cache_key)  # 디스크 영구 캐싱 안 함 → 재시작 시 재시도
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

    # 느린 osascript 위치 읽기는 RESYNC_INTERVAL마다 한 번만.
    # 그 사이는 내부 단조시계(monotonic)로 위치를 보간해 부드럽게 추적.
    RESYNC_INTERVAL = 1.0
    state = None
    base_pos = 0.0          # 마지막으로 읽은 실제 재생 위치
    base_mono = 0.0         # 그 위치를 읽기 직전의 monotonic 시각
    playing = False
    last_resync = -999.0
    last_resolve = 0.0
    miss_count = 0          # Music 상태 읽기 연속 실패 횟수
    last_frame = -1         # 마지막으로 push한 음표 애니메이션 프레임
    use_karaoke = True      # 현재 곡의 카라오케 사용 여부 (장르 따라 결정)

    while True:
        now = time.monotonic()

        # --- 30초마다 위젯 UUID 재탐색 ---
        if now - last_resolve >= 30.0:
            resolve_widget_uuid()
            last_resolve = now

        # --- 1초마다 실제 위치/곡 정보 재동기화 (느린 호출) ---
        if now - last_resync >= RESYNC_INTERVAL:
            call_start = time.monotonic()
            new_state = get_music_state()
            last_resync = time.monotonic()
            if new_state is None:
                # 시스템이 바쁘면 osascript가 일시적으로 실패할 수 있음.
                # 한두 번 실패로 가사를 지우지 말고, 연속 3회(약 3초) 실패해야 '정지'로 간주.
                miss_count += 1
                if miss_count >= 3 and state is not None:
                    write_files("")
                    state = None
                    current_track_id = None
                    lrc_lines = []
                    last_text = None
                # 일시적 실패면 기존 상태 유지 → 아래 표시 로직이 보간으로 계속 진행
            else:
                miss_count = 0
                state = new_state
                base_pos = new_state["position"]
                base_mono = call_start  # 위치 읽기 시작 시점 기준으로 보간
                playing = new_state["playing"]

                track_id = f"{new_state['artist']}|||{new_state['track']}"
                if track_id != current_track_id:
                    current_track_id = track_id
                    last_text = None
                    lrc_lines = []
                    # 곡이 바뀌면 빈 화면 대신 즉시 제목-아티스트를 띄움
                    # (가사 받아오는 동안 터치바가 비지 않게)
                    write_files(truncate(f"{new_state['track']} - {new_state['artist']}", 80))
                    # 가사를 먼저 받아 최대한 빨리 표시 (색 추출은 느리므로 뒤로)
                    lrc_text = fetch_lrc(new_state["artist"], new_state["track"], new_state["album"])
                    lrc_lines = parse_lrc(lrc_text) if lrc_text else []
                    # 카라오케 on/off 결정: 명시적 발라드 장르거나 가사가 느리면(발라드) 전체줄
                    genre = new_state.get("genre", "")
                    use_karaoke = KARAOKE and not is_ballad(genre) and is_fast_song(lrc_lines)
                    _current_color = get_album_color()  # 음표 색 (가사보다 덜 급함)
                    mode = "카라오케" if use_karaoke else "전체줄(발라드)"
                    logging.info(f"{mode} (wps={song_wps(lrc_lines):.2f}, 장르'{genre}'): {new_state['artist']} - {new_state['track']}")

        if state is None:
            time.sleep(0.2)
            continue

        # --- 보간된 현재 위치 (재생 중일 때만 시간 흐름 반영) ---
        est_pos = base_pos + ((time.monotonic() - base_mono) if playing else 0.0)

        title_artist = truncate(f"{state['track']} - {state['artist']}", 80)
        if lrc_lines:
            disp = get_display_at(lrc_lines, est_pos + LEAD_SECONDS, use_karaoke)
            # disp 가사 → 가사 / "" → 짧은 쉼(음표만) / None → 긴 간주(제목-아티스트)
            text = title_artist if disp is None else truncate(disp)
        else:
            text = title_artist

        # 음표 애니메이션: 재생 중일 때 ~0.4초마다 다음 프레임으로 순환
        if NOTE_ANIM and playing:
            frame = int(time.monotonic() / 0.4) % len(NOTE_FRAMES)
        else:
            frame = 0

        # 텍스트가 바뀌거나 음표 프레임이 바뀌면 push
        if text != last_text or frame != last_frame:
            last_text = text
            last_frame = frame
            # 폴백 스크립트(0.5s 폴링)도 같은 프레임을 보도록 NOTE_ICON 동기화
            try:
                with open(NOTE_FRAMES[frame], "rb") as src, open(NOTE_ICON, "wb") as dst:
                    dst.write(src.read())
            except Exception:
                pass
            write_files(text, NOTE_FRAMES[frame])

        time.sleep(0.08)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        write_files("")
        sys.exit(0)
