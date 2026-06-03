<div align="center">

# 🎵 Apple Music Touch Bar Lyrics

### Real-time, word-by-word synced lyrics — right on your MacBook Touch Bar.

*Like a tiny YouTube-Music karaoke bar living in your function row.*

![Platform](https://img.shields.io/badge/platform-macOS-000000?logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)
![BetterTouchTool](https://img.shields.io/badge/needs-BetterTouchTool-ff6b6b)
![License](https://img.shields.io/badge/license-MIT-green)
![Made for Stardance](https://img.shields.io/badge/made%20for-Stardance%20%E2%9C%A8-9b6dff)

</div>

---

```
┌──────────────────────────────────────── Touch Bar ────────────────────────────────────────┐
│                                                                                            │
│   🟣  저 별빛 아래 우리 둘이서                                                               │
│       ▔▔▔▔▔▔▔▔▔▔▔▔▔  (words light up in real time, in sync with the beat)                  │
│                                                                                            │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

The album-colored ♪ on the left, white lyrics that fill in word-by-word as the singer sings,
a transparent background, and a glowing tap effect — all on the Touch Bar.

---

## ✨ Features

| | |
|---|---|
| 🎤 **Word-by-word sync** | Lyrics reveal in real time as the song plays — karaoke-style, using enhanced (word-level) LRC timing |
| 🎚️ **Beat-aware modes** | Ballads show full lines; fast pop/rap auto-switches to karaoke reveal (detected by lyric *density*, not unreliable genre tags) |
| 🎨 **Album-colored note** | Extracts the dominant color from the album art and tints the ♪ icon + a soft neon glow to match |
| 🖼️ **Album thumbnail** | Shows a rounded mini album cover as the widget icon |
| ⏯️ **Music-app scrubber** | Long interludes show a progress bar `1:07 ──◦──── -4:05`; double-tap to toggle a scrubber-only view |
| 🎆 **Tap to spark** | Tap the lyric and a firework bursts in the album's color |
| ⏳ **Intro countdown** | Counting dots `●` appear just before the vocals come in |
| 🎭 **Smart interludes** | 3 s+ instrumental breaks show `Title – Artist`; short rests stay clean |
| 🧹 **Credit filter** | Drops `作词 / 작사 / Produced by` production-credit lines that aren't really lyrics |
| 🌐 **Multi-source lyrics** | lrclib.net → Musixmatch → NetEase fallback, with Korean→English artist lookup for better matches |
| 🪄 **Self-healing** | Auto-starts at login, restarts if it dies, and re-discovers its Touch Bar widget by name |

---

## 🧩 How it works

```
        ┌─────────────┐   AppleScript    ┌──────────────────┐
        │ Apple Music │ ───position────▶ │  lyrics_daemon   │
        └─────────────┘    track/album   │   (Python)       │
                                         │                  │
   lrclib / Musixmatch ──word-level LRC─▶│  • monotonic     │
                                         │    extrapolation │
   album art ──colorthief──▶ ♪ color     │  • karaoke fill  │
                                         └────────┬─────────┘
                                                  │ writes /tmp + AppleScript push
                                                  ▼
                                         ┌──────────────────┐
                                         │ BetterTouchTool  │ ─▶ 💻 Touch Bar
                                         └──────────────────┘
```

The daemon reads the playback position only ~once a second, then **extrapolates with a
monotonic clock** between reads — so the lyrics glide smoothly instead of jumping every poll.
It talks to the display purely through `/tmp` files + an AppleScript push, so the rendering
layer is swappable.

---

## 📋 Requirements

| | |
|---|---|
| **macOS** | A MacBook Pro with a Touch Bar |
| **[BetterTouchTool](https://folivora.ai)** | Renders the Touch Bar widget *(paid, free trial available)* |
| **Apple Music** | The playback source |
| **Python 3** | Homebrew recommended (`brew install python`) |

---

## 🚀 Install

```bash
git clone https://github.com/edgehee/apple-music-touchbar-lyrics.git ~/lyrics_bar
bash ~/lyrics_bar/install.sh
```

`install.sh` installs the dependencies (`colorthief` · `pillow` · `syncedlyrics` · `certifi`)
and registers the LaunchAgent so it auto-starts at login.

### Final step — create the BTT widget (once)

1. Open **BetterTouchTool** → **Touch Bar** tab → **All Apps**
2. **`+`** → **`Shell Script / Task Widget`**
3. In **Script**, put:
   ```
   bash ~/lyrics_bar/lyric_widget.sh
   ```
   *(use the real path, e.g. `bash /Users/yourname/lyrics_bar/lyric_widget.sh`)*
4. Set the **Widget Name** to exactly **`Lyrics`** — the daemon auto-discovers the widget by this name.
5. **Update Interval** `0.5` s · transparent background · left-aligned text

> ▶️ Play a song in Apple Music and the lyrics appear on your Touch Bar.

---

## ⚙️ Customizing

Everything is a constant near the top of `lyrics_daemon.py` — flip a `True`/`False` or tweak a number:

| Constant | Default | What it does |
|---|:---:|---|
| `LEAD_SECONDS` | `0.3` | Show lyrics slightly early/late — raise if late, lower if early |
| `KARAOKE` | `True` | Word-by-word fill (auto-disabled for ballads) |
| `ALBUM_THUMB` | `True` | Use the real album cover as the icon (else a ♪) |
| `NEON_GLOW` | `True` | Album-colored neon glow on the icon |
| `PROGRESS_BAR` | `True` | Scrubber during long interludes |
| `COUNTDOWN` | `True` | Counting dots before the vocals start |
| `TAP_EFFECT` | `True` | Firework burst on tap |
| `GAP_TITLE_THRESHOLD` | `3.0` | Min interlude length (s) to show `Title – Artist` |

Apply changes:
```bash
launchctl kickstart -k gui/$(id -u)/com.lyricsbar.daemon
```

---

## 🛟 Troubleshooting

See **[RECOVERY.md](RECOVERY.md)** for symptom-by-symptom fixes.

The most common one — *lyrics stop showing on the Touch Bar* — is usually BTT pausing its Touch Bar.
Restarting BetterTouchTool brings it right back. If the widget itself vanished (e.g. after a BTT
update), just recreate it with the name **`Lyrics`** and the daemon reconnects automatically.

---

## 🛠️ Built with

`Python` · `AppleScript` · `BetterTouchTool` · `syncedlyrics` · `lrclib.net` · `colorthief` · `Pillow` · `certifi`

## 📝 Notes

- The Touch Bar display is handled by **BetterTouchTool**; if its trial expires you'll need a license (the lyrics stop showing until then).
- Songs with no lyric data just show `Title – Artist`.
- Custom fonts aren't possible — that's a BetterTouchTool limitation (system font only).

---

<div align="center">

**한국어 한 줄 요약** — 애플 뮤직에서 재생 중인 곡의 가사를 맥북 **터치바**에 실시간·단어별로 띄워주는 도구예요.
앨범 색 음표, 카라오케 차오름, 탭하면 불꽃 ✨

<sub>MIT Licensed · Built for 🌟 <a href="https://stardance.hackclub.com">Stardance</a></sub>

</div>
