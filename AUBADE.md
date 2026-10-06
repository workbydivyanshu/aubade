# Aubade — Apple-Music-concept music player (Tauon-powered)

Target UI: Dribbble 16889199 + `~/Downloads/original-*.png` (purple glass,
3-column: sidebar / Trending+Playlist+player / Tags+Played+featured).

## What lives where

| Path | Role |
|------|------|
| `src/` (this fork root) | Pristine Tauon `master` (`d05e5a3`) = playback engine. Do not redesign here. |
| `src/tauon/theme/Aubade.ttheme` | Native Tauon theme approximating the concept (deep purple, pink `#FF4D6D` accents, green `#3DFF88` active). Load in Tauon: Settings → Theme → Aubade. SDL can't do blur, so this is tone-only. |
| `aubade/` (**native app**, GTK4 + libadwaita) | Real desktop app, local files only. `./aubade/run.sh`. Verified: 5760-track scan, GStreamer gapless playback, 25 s error-free run. |
| `aubade-ui/` | Aubade UI shell v1 — pixel-faithful, **working** web prototype. Real playback via `<audio>` + your local files. No build step. |

## Run the UI now

```bash
cd ~/aubade/aubade-ui
python3 -m http.server 8811
# open http://localhost:8811
# → "Load Music folder" (pick ~/Music), or drag-drop audio files. Then press Play.
```

## Run the engine (Tauon backend)

```bash
cd ~/aubade
pip install -e .          # builds phazor C ext (needs FLAC/mp3/opus/vorbis dev libs)
python -m tauon
```

## Engine bridge (how UI v2 talks to Tauon)

Tauon already exposes a headless-ready API — no engine work needed:

- `src/tauon/t_modules/t_webserve.py:489 webserve2` → `http://0.0.0.0:7814/api1/*`
  (`/status`, `/play`, `/pause`, `/next`, `/back`, `/seek/<ms>`,
  `/setvolume/<0-100>`, `/tracklist/<plUUID>`, `/file/<trackId>`, …)
- Playback state machine: `src/tauon/t_modules/t_phazor.py:969 player4`
  over `src/phazor/phazor.c` EXPORTs via ctypes.
- Scanner to reuse: `t_main.py:53141 worker1.gets` + `52885 add_file`
  gated by `54175 Formats.DA`, metadata via `19226 Tauon.tag_scan` + `t_tagscan.py`.
- UI-only SDL layer that stays behind: `t_draw.py`, `t_custom.py`,
  `BottomBarType1` (`t_main.py:34681`), layout (`t_main.py:15534`).

So v2 = Aubade shell speaks `/api1/*` (or imports `player4`+scanner directly),
Tauon keeps doing gapless/CUE/archive/Plex/Jellyfin.

## Toughness: 84/100

Engine free (clone), UI expensive: 63.5k-line SDL immediate-mode monolith
(`t_main.py`) has no CSS blur/flexbox, and the concept only specs 2 screens —
7+ views must be invented. Hence shell-first, native-reskin-second.
