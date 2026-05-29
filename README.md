# 🎵 Apple Music Touch Bar Lyrics

맥북 **터치바**에 Apple Music에서 재생 중인 곡의 **실시간 싱크 가사**를 띄워주는 도구.
앨범 색에 맞춘 음표(♪) 아이콘 + 흰색 가사, 투명 배경.

> macOS · 터치바 탑재 MacBook Pro · [BetterTouchTool](https://folivora.ai) 필요

---

## ✨ 기능

- **실시간 싱크 가사** — 노래 위치에 맞춰 한 줄씩 표시 (monotonic 시계 보간으로 부드럽게)
- **앨범색 음표 아이콘** — 재생 곡 앨범 아트에서 색을 추출해 ♪ 색 자동 변경
- **간주/인트로 표시** — 3초 이상 긴 간주엔 `제목 - 아티스트`, 짧은 쉼은 빈 화면
- **다중 소스 가사** — lrclib.net → Musixmatch → NetEase 순으로 폴백
- **크레딧 자동 제거** — `作词:` `작사:` `Produced by:` 같은 제작진 줄은 가사에서 제외
- **자동 시작** — LaunchAgent로 로그인 시 자동 실행, 꺼지면 자동 재기동

---

## 📋 요구 사항

| 항목 | 설명 |
|------|------|
| macOS | 터치바 탑재 MacBook Pro |
| [BetterTouchTool](https://folivora.ai) | 터치바 렌더링 담당 (**유료**, 체험판 가능) |
| Apple Music 앱 | 재생 소스 |
| Python 3 | Homebrew 권장 (`brew install python`) |

---

## 🚀 설치

```bash
git clone https://github.com/edgehee/apple-music-touchbar-lyrics.git ~/lyrics_bar
bash ~/lyrics_bar/install.sh
```

`install.sh`가 의존성 설치(colorthief·pillow·syncedlyrics) + 자동시작 등록까지 처리합니다.

### 마지막 단계 — BTT 위젯 만들기 (1회)

1. **BetterTouchTool** 열기 → **Touch Bar** 탭 → **All Apps(모든 앱)** 선택
2. **`+`** → **`Shell Script / Task Widget`**
3. **Script** 칸:
   ```
   bash ~/lyrics_bar/lyric_widget.sh
   ```
   (`~`를 실제 경로로, 예: `bash /Users/사용자명/lyrics_bar/lyric_widget.sh`)
4. **위젯 이름(Widget Name)** 을 반드시 **`Lyrics`** 로 지정 — 데몬이 이 이름으로 위젯을 자동 탐색합니다.
5. **Update Interval** `0.5`초 · 배경 투명 · 텍스트 왼쪽 정렬

> Apple Music에서 노래를 재생하면 터치바에 가사가 뜹니다.

---

## ⚙️ 커스터마이징

`lyrics_daemon.py` 상단 상수만 바꾸면 됩니다.

| 상수 | 기본값 | 의미 |
|------|:---:|------|
| `LEAD_SECONDS` | `0.2` | 가사 미리/늦게 표시 (빠르면 ↓, 느리면 ↑) |
| `GAP_TITLE_THRESHOLD` | `3.0` | 이 초 이상 간주에만 제목-아티스트 표시 |
| `BTT_WIDGET_NAME` | `Lyrics` | 자동 탐색할 위젯 이름 |

수정 후 적용:
```bash
launchctl kickstart -k gui/$(id -u)/com.lyricsbar.daemon
```

---

## 🛟 문제 해결

증상별 복구 가이드는 **[RECOVERY.md](RECOVERY.md)** 참고.
가장 흔한 경우(터치바에 가사만 안 나옴) → BTT에서 위젯을 `Lyrics` 이름으로 다시 만들면 자동 재연결됩니다.

---

## 📝 참고

- 터치바 표시는 **BetterTouchTool**이 담당합니다. BTT 체험 만료 시 라이선스 구매가 필요해요(가사 표시가 멈춤).
- 가사 데이터가 없는 곡은 `제목 - 아티스트`만 표시됩니다.
- 커스텀 폰트 변경은 BTT 제약으로 불가능합니다(시스템 폰트 고정).
