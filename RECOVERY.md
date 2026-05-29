# 🛟 복구 설명서 (RECOVERY)

Apple Music 터치바 가사 시스템이 망가졌을 때 보고 따라 하세요.
증상별로 필요한 부분만 보면 됩니다.

---

## 📌 먼저 — 무엇이 망가졌는지 1줄로 진단

터미널에 붙여넣고 실행:

```bash
echo "데몬: $(pgrep -f lyrics_daemon.py >/dev/null && echo 실행중 || echo 꺼짐)"; \
echo "BTT: $(pgrep -x BetterTouchTool >/dev/null && echo 실행중 || echo 꺼짐)"; \
echo "위젯연결: $(grep -q '자동탐색 성공' /tmp/lyricsbar.log 2>/dev/null && echo OK || echo 못찾음)"; \
echo "현재가사: [$(cat /tmp/current_lyric.txt 2>/dev/null)]"
```

- **위젯연결: 못찾음** → 가장 흔한 경우. 아래 **상황 1**.
- **데몬: 꺼짐** → **상황 3**.
- 폴더(`~/lyrics_bar`) 자체가 사라짐 / 새 맥 → **상황 4**.

---

## 상황 1 — 터치바에 가사만 안 나옴 (BTT 위젯이 날아감) ★가장 흔함

BTT가 업데이트/초기화되면 위젯이 사라집니다. 데몬·코드는 멀쩡해요.
**위젯만 다시 만들면** 데몬이 30초 안에 자동으로 다시 연결합니다.

1. **BetterTouchTool** 열기 → **Touch Bar** 탭
2. 왼쪽 사이드바에서 **All Apps(🌐 모든 앱)** 선택
3. 하단 **`+`** → **`Shell Script / Task Widget`** 선택
4. 오른쪽 **Script** 칸에 정확히 입력:
   ```
   bash /Users/apple/lyrics_bar/lyric_widget.sh
   ```
5. **위젯 이름(Widget Name)을 반드시 `Lyrics` 로** 지정 ← 제일 중요! (데몬이 이 이름으로 찾음)
6. **Update Interval** `0.5`초, **배경색 투명**, 텍스트 **왼쪽 정렬**

> 끝나면 30초 안에 가사가 뜹니다. 바로 확인하려면:
> ```bash
> launchctl kickstart -k gui/$(id -u)/com.lyricsbar.daemon
> ```

### (선택) esc/X 버튼 숨기기
BTT Settings → **"왼쪽 닫기 / X 버튼 숨기기"** 체크 → BTT 재시작.

---

## 상황 2 — 다른 앱 쓰면 가사가 사라짐

위젯이 특정 앱에만 묶여있어서 그래요.
**상황 1의 2번**처럼 위젯을 **All Apps(모든 앱)** 칸으로 옮기면 됩니다.

---

## 상황 3 — 데몬이 꺼짐 (가사 파일이 갱신 안 됨)

```bash
# 재시작 (LaunchAgent가 KeepAlive로 자동 재기동)
launchctl kickstart -k gui/$(id -u)/com.lyricsbar.daemon

# 안 되면 등록부터 다시
bash ~/lyrics_bar/setup.sh

# 로그 확인
tail -20 /tmp/lyricsbar.log
```

---

## 상황 4 — 폴더째 사라짐 / 새 맥에 처음 설치

```bash
# 1) 코드 받기 (GitHub Private 저장소)
git clone https://github.com/edgehee/apple-music-touchbar-lyrics.git ~/lyrics_bar

# 2) 필요한 파이썬 패키지 설치
/usr/local/bin/python3 -m pip install colorthief pillow syncedlyrics

# 3) 설치 스크립트 실행 (LaunchAgent 등록 + 자동시작)
bash ~/lyrics_bar/setup.sh

# 4) BTT 위젯 만들기 → 상황 1 참고 (이름은 Lyrics)
```

---

## 구성 요약 (참고)

| 파일/요소 | 위치 | 역할 |
|-----------|------|------|
| `lyrics_daemon.py` | `~/lyrics_bar/` | 메인 데몬: 위치추적·가사fetch·색추출·BTT push |
| `lyric_widget.sh` | `~/lyrics_bar/` | BTT 위젯이 부르는 폴백 스크립트(JSON 출력) |
| `setup.sh` | `~/lyrics_bar/` | LaunchAgent 등록·자동시작 설정 |
| LaunchAgent | `~/Library/LaunchAgents/com.lyricsbar.daemon.plist` | 데몬 자동시작(KeepAlive) |
| BTT 위젯 `Lyrics` | BTT 자체 DB | 터치바에 그리는 주체 (**git에 백업 불가** → 날아가면 재생성) |
| 가사/색 파일 | `/tmp/current_lyric.txt`, `/tmp/current_color.txt` | 데몬↔위젯 통신용(휘발성) |

**핵심 규칙:** 위젯 이름은 항상 **`Lyrics`**. 데몬은 `/usr/local/bin/python3`로 실행
(`/usr/bin/python3`엔 colorthief/pillow 없음). BTT는 유료 라이선스 필요(체험 만료 시 표시 멈춤).
