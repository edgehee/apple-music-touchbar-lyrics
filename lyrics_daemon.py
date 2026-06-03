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
import math
import ssl
import threading
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
GLOW_FILE = "/tmp/glow_color.txt"   # 탭 시 쓸 밝은 네온 톤(앨범색을 흰빛으로 띄움)
NOTE_ICON = "/tmp/note_icon.png"
ART_FILE = "/tmp/album_art_btt.jpg"
LOG_FILE = "/tmp/lyricsbar.log"
# 화면 가사창(lyrics_window.py)용 출력:
#  LINES_FILE: 곡이 바뀔 때 1회 — 전체 가사 줄(+단어 타이밍)·색·제목.
#  POS_FILE:   ~0.2초마다 — 현재 재생위치/재생여부/샘플시각/곡ID (창이 보간해서 부드럽게).
LINES_FILE = "/tmp/lyrics_lines.json"
POS_FILE = "/tmp/lyrics_pos.txt"
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
NOTE_ANIM = False          # 음표 심볼 바꿈(♪♫♬♩) — 과해서 끔. ♪ 고정.
NOTE_SYMBOLS = ["♪", "♫", "♬", "♩"]
NOTE_FRAMES = [f"/tmp/note_{i}.png" for i in range(len(NOTE_SYMBOLS))]
NEON_GLOW = True           # 음표/썸네일에 앨범색 네온 발광 효과
ALBUM_THUMB = True         # 아이콘에 실제 앨범 커버 썸네일 표시 (없으면 음표)
ALBUM_THUMB_FILE = "/tmp/album_thumb.png"
PROGRESS_BAR = True        # 긴 간주에 곡 진행 바 표시
COUNTDOWN = True           # 가사 시작 직전 카운트다운 점(●)
COUNTDOWN_SECS = 4.0       # 다음 가사까지 이 시간 이내면 카운트다운 표시
TAP_EFFECT = True          # 위젯 탭하면 불꽃 터지는 임팩트 효과
TAP_FILE = "/tmp/lyric_tap"   # 위젯 탭 시 이 파일이 touch됨 → 데몬이 감지
TAP_BURST_SECS = 0.6       # 불꽃 효과 지속 시간
FIREWORK_FRAMES = [f"/tmp/fw_{i}.png" for i in range(6)]  # 불꽃 폭발 애니메이션 프레임

os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

_current_color = "255,255,255,255"
_current_rgb = (230, 230, 230)
_glow_color = "255,255,255,255"


def _compute_glow(rgb: Tuple[int, int, int]) -> str:
    """앨범색을 흰빛 쪽으로 띄운 '빛나는' 네온 톤 → 'r,g,b,255'."""
    r, g, b = rgb
    mix = 0.55  # 흰색과 섞는 비율(클수록 더 밝게 빛남)
    gr = int(r + (255 - r) * mix)
    gg = int(g + (255 - g) * mix)
    gb = int(b + (255 - b) * mix)
    return f"{gr},{gg},{gb},255"

# 가사 이미지 렌더링 설정
LYRIC_IMG = "/tmp/lyric_img.png"
SCALE = 2                       # 레티나 2배
TEXT_PT = 16                    # 글자 크기(pt)
BAR_H_PT = 30                   # 터치바 위젯 높이(pt)
LYRIC_FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
LYRIC_FONT_INDEX = 2            # 굵은 가중치 (0~ : 가는것→굵은것)


def generate_note_icon(rgb: Tuple[int, int, int]):
    """앨범색 음표 PNG들 생성 (네온 글로우 옵션).
    NOTE_FRAMES[i] = 각 음표 심볼(♪♫♬♩, 살짝 크기 펄스), NOTE_ICON = 폴백용 기본."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
        r, g, b = rgb
        for i, sym in enumerate(NOTE_SYMBOLS):
            size = 34 if i % 2 == 0 else 29   # 짝/홀 프레임 크기 차이로 펄스 느낌
            font = ImageFont.truetype(FONT_PATH, size)
            pos = (6, 2 + (34 - size) // 2)
            img = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
            if NEON_GLOW:
                # 글로우: 같은 글자를 그려 블러 → 발광처럼 깔고 그 위에 본체
                glow = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
                ImageDraw.Draw(glow).text(pos, sym, font=font, fill=(r, g, b, 255))
                glow = glow.filter(ImageFilter.GaussianBlur(2.5))
                img = Image.alpha_composite(img, glow)
                img = Image.alpha_composite(img, glow)  # 두 번 겹쳐 더 밝게
            ImageDraw.Draw(img).text(pos, sym, font=font, fill=(255, 255, 255, 255)
                                     if NEON_GLOW else (r, g, b, 255))
            img.save(NOTE_FRAMES[i])
            if i == 0:
                img.save(NOTE_ICON)  # 폴백 스크립트/기본용
    except Exception as e:
        logging.debug(f"generate_note_icon: {e}")


def generate_album_thumb(rgb: Tuple[int, int, int]) -> bool:
    """앨범 아트를 둥근 썸네일 + 앨범색 네온 테두리로 만들고, 우하단에 고정 ♪ 배지를
    그려 ALBUM_THUMB_FILE 저장. 성공하면 True. 앨범아트 없으면 False."""
    if not ALBUM_THUMB or not os.path.exists(ART_FILE):
        return False
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
        r, g, b = rgb
        S = 40
        art = Image.open(ART_FILE).convert("RGBA").resize((S, S), Image.LANCZOS)
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=9, fill=255)

        # 앨범 커버 + 네온 테두리
        img = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
        if NEON_GLOW:
            glow = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
            ImageDraw.Draw(glow).rounded_rectangle([2, 2, 41, 41], radius=10,
                                                   fill=(r, g, b, 255))
            glow = glow.filter(ImageFilter.GaussianBlur(2.5))
            img = Image.alpha_composite(img, glow)
        img.paste(art, (2, 2), mask)

        # 우하단 고정 ♪ 배지 (어두운 반투명 원판 + 음표, 애니메이션 없음)
        badge = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
        ImageDraw.Draw(badge).ellipse([26, 26, 43, 43], fill=(0, 0, 0, 150))
        img = Image.alpha_composite(img, badge)
        note = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
        ImageDraw.Draw(note).text((29, 25), "♪", font=ImageFont.truetype(FONT_PATH, 17),
                                  fill=(r, g, b, 255))
        if NEON_GLOW:
            img = Image.alpha_composite(img, note.filter(ImageFilter.GaussianBlur(1.5)))
        img = Image.alpha_composite(img, note)
        img.save(ALBUM_THUMB_FILE)
        return True
    except Exception as e:
        logging.debug(f"generate_album_thumb: {e}")
        return False


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
    """앨범 아트에서 밝고 선명한 색 추출 → 'r,g,b,255'. _current_rgb / _glow_color도 갱신."""
    global _current_rgb, _glow_color
    default = (230, 230, 230)
    if not save_album_art() or not os.path.exists(ART_FILE):
        _current_rgb = default
        _glow_color = _compute_glow(default)
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
        _glow_color = _compute_glow((r, g, b))
        generate_note_icon((r, g, b))
        return f"{r},{g},{b},255"
    except Exception as e:
        logging.debug(f"get_album_color: {e}")
        _current_rgb = default
        _glow_color = _compute_glow(default)
        generate_note_icon(default)
        return "230,230,230,255"


def generate_firework_frames(rgb: Tuple[int, int, int]):
    """탭 시 보여줄 불꽃 폭발 애니메이션 프레임들 생성 (앨범색 스파크 + 흰 코어)."""
    try:
        from PIL import Image, ImageDraw, ImageFilter
        r, g, b = rgb
        cx, cy = 22, 22
        rays = 11
        n = len(FIREWORK_FRAMES)
        for i in range(n):
            prog = i / (n - 1)                 # 0 → 1
            rad = 3 + prog * 18                # 바깥으로 퍼짐
            alpha = int(255 * (1 - prog * 0.65))  # 점점 흐려짐
            img = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            for k in range(rays):
                ang = (2 * math.pi / rays) * k + prog * 0.5
                xo, yo = cx + math.cos(ang) * rad * 0.45, cy + math.sin(ang) * rad * 0.45
                x, y = cx + math.cos(ang) * rad, cy + math.sin(ang) * rad
                d.line([xo, yo, x, y], fill=(r, g, b, alpha), width=2)
                d.ellipse([x - 1.6, y - 1.6, x + 1.6, y + 1.6],
                          fill=(255, 255, 255, alpha))
            core = int(220 * (1 - prog))       # 가운데 섬광
            if core > 0:
                d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(255, 255, 255, core))
            if NEON_GLOW:
                img = Image.alpha_composite(img.filter(ImageFilter.GaussianBlur(1.3)), img)
            img.save(FIREWORK_FRAMES[i])
    except Exception as e:
        logging.debug(f"generate_firework_frames: {e}")


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


def write_files(text: str, icon_path: str = NOTE_ICON, push: bool = True):
    """가사 + 색상 파일 기록(폴백). push=True면 BTT에 즉시 push.
    (탭 버스트 중엔 push=False로 — 폴링이 앨범색 글자를 칠하게 두기 위해)"""
    try:
        with open(LYRIC_FILE, "w", encoding="utf-8") as f:
            f.write(text)
        with open(COLOR_FILE, "w", encoding="utf-8") as f:
            f.write(_current_color)
        with open(GLOW_FILE, "w", encoding="utf-8") as f:
            f.write(_glow_color)
    except Exception as e:
        logging.debug(f"write_files: {e}")
    if push:
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
            set dur to (duration of current track)
            return (pos as string) & "|||" & t & "|||" & ar & "|||" & al & "|||" & ps & "|||" & gn & "|||" & (dur as string)
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
        try:
            duration = float(parts[6]) if len(parts) >= 7 else 0.0
        except ValueError:
            duration = 0.0
        return {"position": float(parts[0]), "track": parts[1],
                "artist": parts[2], "album": parts[3],
                "playing": playing, "genre": genre, "duration": duration}
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


# 단어별 타임스탬프 태그 <mm:ss.xx> (enhanced LRC)
_WORD_TAG_RE = re.compile(r"<(\d+):(\d+(?:\.\d+)?)>([^<]*)")


def parse_lrc(lrc_text: str):
    """줄 단위 LRC → [(ts, text, None)]. (words=None = 단어 타이밍 없음)"""
    lines = []
    for line in lrc_text.split("\n"):
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", line)
        if m:
            ts = int(m.group(1)) * 60 + float(m.group(2))
            txt = m.group(3).strip()
            if _is_credit(txt):
                continue
            lines.append((ts, txt, None))
    return sorted(lines, key=lambda x: x[0])


def parse_enhanced_lrc(lrc_text: str):
    """단어별 LRC([..] <..>단어 <..>단어) → [(ts, text, [(word_ts, word), ...])].
    단어 태그 없는 줄은 words=None."""
    lines = []
    for line in lrc_text.split("\n"):
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", line)
        if not m:
            continue
        line_ts = int(m.group(1)) * 60 + float(m.group(2))
        rest = m.group(3)
        words = []
        for wm in _WORD_TAG_RE.finditer(rest):
            wts = int(wm.group(1)) * 60 + float(wm.group(2))
            words.append((wts, wm.group(3)))
        if words:
            full = re.sub(r"\s+", " ", "".join(w for _, w in words)).strip()
            if _is_credit(full):
                continue
            lines.append((line_ts, full, words))
        else:
            txt = rest.strip()
            if _is_credit(txt):
                continue
            lines.append((line_ts, txt, None))
    return sorted(lines, key=lambda x: x[0])


def parse_lyrics(text: str):
    """단어별 태그가 있으면 enhanced 파싱(진짜 박자 동기화), 없으면 줄 단위."""
    if _WORD_TAG_RE.search(text):
        return parse_enhanced_lrc(text)
    return parse_lrc(text)


def get_lyric_at(lines, position: float) -> str:
    current = ""
    for ts, text, _ in lines:
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


def is_fast_song(lines) -> bool:
    """가사 밀도로 빠른 곡(랩/팝) 여부 판단. 정보 부족하면 True(기본 카라오케)."""
    texts = [(ts, t) for ts, t, _ in lines if t]
    if len(texts) < 4:
        return True
    span = texts[-1][0] - texts[0][0]
    if span <= 0:
        return True
    words = sum(len(t.split()) for _, t in texts)
    return (words / span) >= FAST_WPS_THRESHOLD


def song_wps(lines) -> float:
    """로그용 초당 단어 수."""
    texts = [(ts, t) for ts, t, _ in lines if t]
    if len(texts) < 2:
        return 0.0
    span = texts[-1][0] - texts[0][0]
    if span <= 0:
        return 0.0
    return sum(len(t.split()) for _, t in texts) / span


# 카라오케가 줄 구간의 이 비율 지점에서 다 채워짐 (클수록 천천히/노래에 맞게, 작을수록 빠르게)
KARAOKE_REVEAL_FRACTION = 0.77


def _karaoke_reveal(text: str, frac: float) -> str:
    """진행률 frac(0~1)만큼 가사를 공개. 단어 단위(공백 있으면)·글자 단위(없으면)."""
    frac = max(0.0, min(1.0, frac / KARAOKE_REVEAL_FRACTION))
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
    cur_ts, cur_text, cur_words, cur_idx = None, "", None, -1
    for i, (ts, text, words) in enumerate(lines):
        if ts <= position:
            cur_ts, cur_text, cur_words, cur_idx = ts, text, words, i
        else:
            break
    if cur_text:
        if not karaoke:
            return cur_text
        if cur_words:
            # 단어별 타임스탬프 → 진짜 박자 동기화 (해당 시각 지난 단어만 공개)
            shown = "".join(w for wts, w in cur_words if wts <= position)
            shown = re.sub(r"\s+", " ", shown).strip()
            return shown or cur_text.split(" ")[0]
        # 단어 타이밍 없으면 줄 구간에서 진행률로 근사
        next_ts = lines[cur_idx + 1][0] if cur_idx + 1 < len(lines) else cur_ts + 4.0
        dur = max(0.4, next_ts - cur_ts)
        return _karaoke_reveal(cur_text, (position - cur_ts) / dur)
    # 빈 줄(쉼) 구간 — 다음 '실제 가사'까지의 간격으로 길이 판단
    next_lyric_ts = None
    for ts, text, _ in lines:
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


# 한글 아티스트명 ↔ lrclib 영문명 매핑 (lrclib은 영문명으로 저장된 경우가 많음).
# 필요하면 계속 추가하세요.
ARTIST_EN = {
    "아이유": "IU", "방탄소년단": "BTS", "블랙핑크": "BLACKPINK", "뉴진스": "NewJeans",
    "세븐틴": "SEVENTEEN", "트와이스": "TWICE", "에스파": "aespa", "르세라핌": "LE SSERAFIM",
    "아이브": "IVE", "여자아이들": "I-DLE", "스트레이키즈": "Stray Kids", "엑소": "EXO",
    "레드벨벳": "Red Velvet", "빅뱅": "BIGBANG", "하이키": "H1-KEY", "코르티스": "CORTIS",
    "데이식스": "DAY6", "투모로우바이투게더": "TXT", "샤이니": "SHINee", "태연": "TAEYEON",
    "지드래곤": "G-DRAGON", "악동뮤지션": "AKMU", "백예린": "Yerin Baek", "폴킴": "Paul Kim",
    # BTS 솔로
    "지민": "Jimin", "정국": "Jung Kook", "뷔": "V", "슈가": "SUGA", "어거스트디": "Agust D",
    "제이홉": "j-hope", "진": "Jin", "알엠": "RM", "남준": "RM",
    # BLACKPINK 솔로 + 기타 솔로
    "지수": "JISOO", "제니": "JENNIE", "로제": "ROSÉ", "리사": "LISA",
    "화사": "Hwasa", "청하": "CHUNG HA", "비비": "BIBI", "선미": "SUNMI",
    "헤이즈": "Heize", "백현": "BAEKHYUN", "카이": "KAI", "도경수": "DOH KYUNG SOO",
    "임영웅": "Lim Young Woong", "아이엠": "I.M", "박재범": "Jay Park", "크러쉬": "Crush",
    "딘": "DEAN", "george": "George", "죠지": "George", "기리보이": "Giriboy",
}


def _expand_artist(expected: str) -> set:
    """기대 아티스트 토큰 + 한글→영문 매핑까지 포함해 비교 폭을 넓힘(아이유→IU)."""
    toks = _norm(expected)
    e = expected or ""
    for ko, en in ARTIST_EN.items():
        if ko in e:
            toks |= _norm(en)
    return toks


def _artist_ok(result_artist: str, expected: str) -> bool:
    """검색 결과 아티스트가 기대 아티스트와 충분히 겹치는지 확인(한↔영 매핑 포함)."""
    a, b = _norm(result_artist), _expand_artist(expected)
    if not a or not b:
        return False
    return len(a & b) > 0  # 토큰 하나라도 겹치면 동일 아티스트로 인정


def _norm_title(s: str) -> str:
    """제목 비교용 정규화: 괄호 안 내용 제거 + 영숫자/한글만 남김(공백·기호 제거)."""
    s = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", s or "")
    return re.sub(r"[^a-z0-9가-힣]", "", s.lower())


def _title_ok(result_title: str, want: str) -> bool:
    """제목이 충분히 일치하는지(한↔영 아티스트명이 달라도 곡을 식별하기 위함)."""
    a, b = _norm_title(result_title), _norm_title(want)
    if not a or not b or len(b) < 2:
        return False
    return a == b or a in b or b in a


def _lrclib_by_title(track: str, artist: str) -> Optional[str]:
    """제목으로 검색해, 아티스트가 겹치거나(우선) 제목이 일치하는 첫 동기화 가사를 채택.
    한글 아티스트(아이유)와 lrclib 영문명(IU)이 달라 아티스트 매칭이 실패하는 곡 구제용."""
    try:
        url = "https://lrclib.net/api/search?" + urllib.parse.urlencode({"q": track})
        req = urllib.request.Request(url, headers={"Lrclib-Client": "LyricsBar/1.0"})
        with urllib.request.urlopen(req, timeout=6, context=_SSL_CTX) as resp:
            data = json.loads(resp.read())
        if not isinstance(data, list):
            return None
        # 제목이 일치하고 동기화 가사가 있는 후보만 추림
        cands = [it for it in data
                 if (it.get("syncedLyrics") or "").strip()
                 and _title_ok(it.get("trackName", ""), track)]
        # 1순위: 아티스트도 겹치는 결과(한↔영 매핑 포함)
        for it in cands:
            if _artist_ok(it.get("artistName", ""), artist):
                return it["syncedLyrics"]
        # 2순위: 제목 후보들의 아티스트가 '모두 동일'할 때만 채택(애매하면 포기 → 엉뚱한 곡 방지)
        arts = {_norm_title(it.get("artistName", "")) for it in cands}
        if cands and len(arts) == 1:
            return cands[0]["syncedLyrics"]
        return None
    except Exception as e:
        logging.debug(f"_lrclib_by_title: {e}")
    return None


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


def _lrclib_en_artist(track: str, artist: str) -> Optional[str]:
    """lrclib 검색으로 영어 아티스트명을 알아냄 (한글 아티스트 뉴진스→NewJeans).
    단어별 가사는 영어명으로만 있는 경우가 많음. 곡명은 원래 것을 그대로 쓰므로 아티스트만 추출."""
    try:
        url = "https://lrclib.net/api/search?" + urllib.parse.urlencode({"q": f"{track} {artist}"})
        req = urllib.request.Request(url, headers={"Lrclib-Client": "LyricsBar/1.0"})
        with urllib.request.urlopen(req, timeout=6, context=_SSL_CTX) as resp:
            data = json.loads(resp.read())
        for item in data:
            if _artist_ok(item.get("artistName", ""), artist):
                en_a = re.sub(r"\(.*?\)", "", item.get("artistName", "")).strip()
                if en_a:
                    return en_a
    except Exception as e:
        logging.debug(f"_lrclib_en_artist: {e}")
    return None


def _try_enhanced(query: str) -> Optional[str]:
    """syncedlyrics enhanced 검색 → 단어 태그가 있을 때만 반환."""
    try:
        import syncedlyrics
        r = syncedlyrics.search(query, enhanced=True)
        if r and _WORD_TAG_RE.search(r):
            return r
    except Exception as e:
        logging.debug(f"_try_enhanced: {e}")
    return None


def _lrc_first_text(lrc: str) -> str:
    """LRC에서 첫 실제 가사 텍스트 한 줄을 정규화해 추출(타임스탬프/단어태그 제거)."""
    for line in (lrc or "").splitlines():
        t = re.sub(r"\[[0-9:.]+\]", "", line)        # [00:12.34]
        t = re.sub(r"<[0-9:.]+>", "", t)              # <00:12.34> 단어태그
        t = re.sub(r"[^a-z0-9가-힣 ]", "", t.lower()).strip()
        t = re.sub(r"\s+", " ", t)
        if len(t) >= 4:
            return t[:30]
    return ""


def _enhanced_is_right(synced: str, artist: str, track: str) -> bool:
    """enhanced(단어별) 결과가 맞는 곡인지 lrclib 검증본의 첫 줄과 대조.
    검증본이 없으면 일단 신뢰(기존 동작 유지). 첫 줄이 명백히 다르면 동명곡으로 보고 폐기."""
    try:
        ref = _lrclib("https://lrclib.net/api/search?" + urllib.parse.urlencode(
            {"q": f"{track} {artist}"}), expected_artist=artist) or _lrclib_by_title(track, artist)
    except Exception:
        return True
    a, b = _lrc_first_text(synced), _lrc_first_text(ref or "")
    if not a or not b:
        return True
    return a[:12] == b[:12] or a in b or b in a


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
    # 0) 단어별(enhanced) 가사 우선 — 진짜 박자 동기화. 단어 태그가 있을 때만 채택.
    # 한글 아티스트는 영문명으로 먼저 검색(K-pop은 영문 메타가 정확 → 동명곡 오매칭 방지).
    en_known = next((en for ko, en in ARTIST_EN.items() if ko in (artist or "")), None)
    synced = None
    if en_known and en_known.lower() not in (artist or "").lower():
        synced = _try_enhanced(f"{en_known} {track}")
        if synced:
            logging.info(f"단어별(enhanced·영문명) 가사 사용: {en_known} - {track}")
    if not synced:
        synced = _try_enhanced(f"{artist} {track}")
        if synced:
            logging.info(f"단어별(enhanced) 가사 사용: {artist} - {track}")
    if not synced:
        # 매핑에 없는 한글 아티스트는 lrclib에서 영어명 동적 조회 후 재검색 (뉴진스→NewJeans).
        en_a = _lrclib_en_artist(track, artist)
        if en_a and en_a.lower() not in artist.lower():
            synced = _try_enhanced(f"{en_a} {track}")
            if synced:
                logging.info(f"단어별(영어명) 가사 사용: {en_a} - {track}")
    # enhanced는 아티스트 메타가 없어 동명곡을 잘못 집을 수 있음 → 검증본과 대조해 틀리면 폐기.
    if synced and not _enhanced_is_right(synced, artist, track):
        logging.info(f"enhanced 결과 검증 실패(동명 다른 곡 의심) → 폐기: {artist} - {track}")
        synced = None
    if not synced:
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

    # 받긴 했지만 타임스탬프 줄이 하나도 없으면(엉뚱/비동기 결과) 폐기하고 폴백 계속.
    if synced and not parse_lyrics(synced):
        synced = None

    # 제목에 (feat. …)/(with …)/[…] 등 괄호 꼬리표가 붙어 매칭 실패하는 경우가 많음.
    # 꼬리표를 떼고 깨끗한 제목으로 한 번 더 시도 (예: '에잇 (feat. SUGA)' → '에잇').
    track_clean = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*$", "", track).strip()
    if not synced and track_clean and track_clean != track:
        logging.info(f"꼬리표 제거 후 재시도: '{track}' → '{track_clean}'")
        synced = _try_enhanced(f"{artist} {track_clean}")
        if not synced:
            synced = _lrclib("https://lrclib.net/api/get?" + urllib.parse.urlencode(
                {"artist_name": artist, "track_name": track_clean}))
        if not synced:
            synced = _lrclib("https://lrclib.net/api/search?" + urllib.parse.urlencode(
                {"q": f"{track_clean} {artist}"}), expected_artist=artist)

    # 마지막 구제: 제목으로만 검색해 제목 일치하는 가사 채택(한↔영 아티스트명 불일치 대응)
    if not synced:
        synced = _lrclib_by_title(track_clean or track, artist)
        if synced:
            logging.info(f"제목 매칭으로 가사 채택: {artist} - {track_clean or track}")

    if synced and parse_lyrics(synced):   # 타임스탬프 줄이 실제로 있을 때만 채택/캐싱
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(synced)
        logging.info(f"Cached: {artist} - {track}")
        return synced
    _no_lyrics_session.add(cache_key)  # 디스크 영구 캐싱 안 함 → 재시작 시 재시도
    logging.info(f"No synced lyrics: {artist} - {track}")
    return None


def truncate(text: str, n: int = 120) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


PROGRESS_KNOB = "◦"   # 스크러버 손잡이 (● ♡ ◆ 등으로 바꿔도 됨)


def _fmt_time(t: float) -> str:
    m, s = divmod(int(max(0, t)), 60)
    return f"{m}:{s:02d}"


def make_progress_bar(pos: float, dur: float, cells: int = 11) -> str:
    """음악앱 스크러버 스타일. 예: 0:58 ━━━●───── 3:47
    지난 구간 ━(굵게), 손잡이 ●, 남은 구간 ─(가늘게)."""
    if dur <= 0:
        return ""
    frac = max(0.0, min(1.0, pos / dur))
    k = int(round(frac * (cells - 1)))
    track = "─" * k + PROGRESS_KNOB + "─" * (cells - 1 - k)
    # 오른쪽은 남은 시간(-) 표시 (음악앱 스타일): 1:07 ──◦──── -4:05
    return f"{_fmt_time(pos)} {track} -{_fmt_time(dur - pos)}"


def get_next_lyric_ts(lines, position: float) -> Optional[float]:
    """현재 위치 이후 첫 '실제 가사'(빈 줄 아님) 줄의 시작 시각."""
    for ts, text, _ in lines:
        if ts > position and text:
            return ts
    return None


def countdown_dots(secs_left: float) -> str:
    """가사 시작까지 남은 시간을 점으로. 가까울수록 점이 채워짐 (○○○ → ●●●)."""
    n = 3
    lit = n - int(max(0.0, min(float(n), secs_left)))  # 0~3개 점등
    return " ".join("●" if i < lit else "○" for i in range(n))


# 곡 자산(가사/색/썸네일) 백그라운드 로딩 — 느린 네트워크가 표시를 막지 않게.
_load_lock = threading.Lock()
_loaded = {"token": None, "lrc_lines": [], "use_karaoke": True, "has_thumb": False}


def write_lines_json(token: str, artist: str, track: str, lines):
    """화면 가사창용으로 전체 가사 줄을 JSON으로 내보냄 (곡 바뀔 때 1회).
    lines = [(ts, text, words_or_None)] → {"t":ts,"text":text,"words":[[wts,w],..] or null}."""
    try:
        payload = {
            "track_id": token,
            "title": track,
            "artist": artist,
            "color": _current_color,
            "lines": [
                {"t": ts, "text": text,
                 "words": ([[wts, w] for wts, w in words] if words else None)}
                for ts, text, words in lines
            ],
        }
        tmp = LINES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, LINES_FILE)   # 원자적 교체(창이 반쪽짜리 파일을 읽지 않게)
    except Exception as e:
        logging.debug(f"write_lines_json: {e}")


def write_pos(pos: float, playing: bool, token, dur: float = 0.0):
    """현재 재생 위치 비콘 (창이 로컬 시계로 보간).
    'pos|playing|sampled_unix|duration|track_id' (track_id엔 '|||'가 있어 맨 뒤에 둠)."""
    try:
        with open(POS_FILE, "w", encoding="utf-8") as f:
            f.write(f"{pos:.3f}|{1 if playing else 0}|{time.time():.3f}|{dur:.3f}|{token or ''}")
    except Exception as e:
        logging.debug(f"write_pos: {e}")


def load_track_assets(token: str, artist: str, track: str, album: str, genre: str):
    """느린 작업(가사 fetch + 색 추출 + 썸네일)을 백그라운드에서 수행 후 _loaded에 기록."""
    global _current_color
    try:
        lrc_text = fetch_lrc(artist, track, album)
        lines = parse_lyrics(lrc_text) if lrc_text else []
        karaoke = KARAOKE and not is_ballad(genre) and is_fast_song(lines)
        _current_color = get_album_color()        # _current_rgb / _glow_color도 갱신
        thumb = generate_album_thumb(_current_rgb)
        generate_firework_frames(_current_rgb)    # 탭 불꽃 프레임(앨범색)
        write_lines_json(token, artist, track, lines)  # 화면 가사창에 전체 가사 공급
        with _load_lock:
            _loaded.update(token=token, lrc_lines=lines,
                           use_karaoke=karaoke, has_thumb=thumb)
        mode = "카라오케" if karaoke else "전체줄(발라드)"
        logging.info(f"{mode} (wps={song_wps(lines):.2f}, 썸네일={thumb}, 장르'{genre}'): {artist} - {track}")
    except Exception as e:
        logging.warning(f"load_track_assets: {e}")


def main():
    global _current_color
    current_track_id = None
    lrc_lines: List = []
    last_text = None

    _current_color = "230,230,230,255"
    generate_note_icon((230, 230, 230))
    generate_firework_frames((230, 230, 230))
    resolve_widget_uuid()  # 시작 시 위젯 UUID 자동 탐색
    write_files("")
    logging.info("lyrics_daemon started")

    # 느린 osascript 위치 읽기는 RESYNC_INTERVAL마다 한 번만.
    # 그 사이는 내부 단조시계(monotonic)로 위치를 보간해 부드럽게 추적.
    RESYNC_INTERVAL = 1.0
    # BTT push(osascript)는 이 간격으로 합쳐서 호출 폭주를 막음(발열↓).
    # 가사 글자가 빨리 바뀌어도 이 주기로만 push → 최신값을 1번에 묶어 보냄.
    PUSH_MIN_INTERVAL = 0.15
    last_push_mono = -999.0  # 마지막으로 BTT push한 monotonic 시각
    state = None
    base_pos = 0.0          # 마지막으로 읽은 실제 재생 위치
    base_mono = 0.0         # 그 위치를 읽기 직전의 monotonic 시각
    playing = False
    last_resync = -999.0
    last_resolve = 0.0
    miss_count = 0          # Music 상태 읽기 연속 실패 횟수
    last_icon = None        # 마지막으로 push한 아이콘 경로
    use_karaoke = True      # 현재 곡의 카라오케 사용 여부 (장르 따라 결정)
    has_thumb = False       # 현재 곡 앨범 썸네일 생성 성공 여부
    last_burst = False      # 직전 루프의 탭 버스트 상태
    loaded_token = None     # 백그라운드 로딩 결과가 적용된 곡 토큰
    scrubber_mode = False   # 더블탭 토글: 가사 대신 스크러버만 표시
    last_tap_mtime = 0.0    # 마지막으로 본 탭 파일 시각(더블탭 감지용)
    last_pos_write = 0.0    # 화면 가사창용 위치 비콘 마지막 기록 시각

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
                    write_pos(0.0, False, None, 0.0)   # 가사창에 '정지' 알림
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
                    use_karaoke = True
                    has_thumb = False
                    loaded_token = None
                    # 곡이 바뀌면 즉시 제목-아티스트 표시(빈 화면 방지),
                    # 무거운 작업(가사 fetch+색+썸네일)은 백그라운드 스레드로 → 화면 안 멈춤
                    write_files(truncate(f"{new_state['track']} - {new_state['artist']}", 80))
                    threading.Thread(
                        target=load_track_assets,
                        args=(track_id, new_state["artist"], new_state["track"],
                              new_state["album"], new_state.get("genre", "")),
                        daemon=True).start()

        # 백그라운드 로딩이 끝났으면(현재 곡과 일치) 결과 적용
        with _load_lock:
            if _loaded["token"] == current_track_id and loaded_token != current_track_id:
                lrc_lines = _loaded["lrc_lines"]
                use_karaoke = _loaded["use_karaoke"]
                has_thumb = _loaded["has_thumb"]
                loaded_token = current_track_id

        if state is None:
            time.sleep(0.2)
            continue

        # --- 보간된 현재 위치 (재생 중일 때만 시간 흐름 반영) ---
        est_pos = base_pos + ((time.monotonic() - base_mono) if playing else 0.0)

        # 화면 가사창용 위치 비콘(~0.2초마다). LEAD 없는 원위치 → 창이 자체 보간.
        if now - last_pos_write >= 0.2:
            write_pos(est_pos, playing, current_track_id, state.get("duration", 0.0))
            last_pos_write = now

        title_artist = truncate(f"{state['track']} - {state['artist']}", 80)
        pos_lead = est_pos + LEAD_SECONDS
        dur = state.get("duration", 0.0)

        # 탭 감지: 불꽃(버스트) + 더블탭으로 스크러버 모드 토글
        tap_burst = False
        tap_age = 999.0
        if TAP_EFFECT:
            try:
                if os.path.exists(TAP_FILE):
                    tm = os.path.getmtime(TAP_FILE)
                    tap_age = time.time() - tm
                    tap_burst = tap_age < TAP_BURST_SECS
                    if tm > last_tap_mtime:           # 새 탭 발생
                        if last_tap_mtime and (tm - last_tap_mtime) < 0.45:
                            scrubber_mode = not scrubber_mode  # 빠른 두 번 탭 → 토글
                        last_tap_mtime = tm
            except Exception:
                pass

        def interlude_text():
            """긴 간주/무가사 구간: 가사 임박하면 카운트다운, 아니면 제목+진행바."""
            nxt = get_next_lyric_ts(lrc_lines, pos_lead) if lrc_lines else None
            if COUNTDOWN and nxt is not None and 0 < (nxt - pos_lead) <= COUNTDOWN_SECS:
                return countdown_dots(nxt - pos_lead)
            if PROGRESS_BAR and dur > 0:
                return truncate(title_artist + "   " + make_progress_bar(est_pos, dur), 120)
            return title_artist

        if scrubber_mode:
            # 더블탭 모드: 가사 숨기고 앨범+스크러버만
            text = make_progress_bar(est_pos, dur) if dur > 0 else title_artist
        elif lrc_lines:
            disp = get_display_at(lrc_lines, pos_lead, use_karaoke)
            # disp 가사 → 가사 / "" → 짧은 쉼(음표만) / None → 긴 간주
            text = interlude_text() if disp is None else truncate(disp)
        else:
            text = interlude_text()

        # 아이콘 결정: 탭 버스트 중이면 불꽃 프레임, 아니면 앨범썸네일/음표
        if tap_burst:
            fi = min(len(FIREWORK_FRAMES) - 1,
                     int(tap_age / (TAP_BURST_SECS / len(FIREWORK_FRAMES))))
            icon_path = FIREWORK_FRAMES[fi]
        elif has_thumb:
            icon_path = ALBUM_THUMB_FILE
        elif NOTE_ANIM and playing:
            icon_path = NOTE_FRAMES[int(time.monotonic() / 0.4) % len(NOTE_FRAMES)]
        else:
            icon_path = NOTE_FRAMES[0]

        # 텍스트/아이콘이 바뀌면(또는 버스트 진입/이탈 시) 갱신.
        # 단, BTT push는 PUSH_MIN_INTERVAL로 합쳐 호출 폭주를 막음. 간격이 안 찼으면
        # 이번 변경은 push하지 않고 보류 → 다음 자격 루프에서 '최신값'으로 한 번에 나감.
        changed = (text != last_text or icon_path != last_icon or tap_burst != last_burst)
        if changed and (now - last_push_mono) >= PUSH_MIN_INTERVAL:
            last_text = text
            last_icon = icon_path
            last_burst = tap_burst
            last_push_mono = now
            # 폴백 스크립트(폴링)도 같은 아이콘을 보도록 NOTE_ICON 동기화
            try:
                with open(icon_path, "rb") as src, open(NOTE_ICON, "wb") as dst:
                    dst.write(src.read())
            except Exception:
                pass
            write_files(text, icon_path)

        time.sleep(0.10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        write_files("")
        sys.exit(0)
