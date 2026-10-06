# Aubade

A local-first music player for GNOME — GTK4 + libadwaita UI in the spirit of
the Apple Music concept, GStreamer engine, zero network dependency for
playback. Scans your own files, keeps a cached library with play stats, and
fetches synced lyrics on demand.

![Player](aubade-ui/) · 17 screens · 92 tests · Flatpak-ready

## Run

```sh
./run.sh
# or: /usr/bin/python3 -m aubade   (run from this dir)
```

Must use `/usr/bin/python3` (system gi/Gst bindings live there).
On first launch it scans `~/Music`; use **+ Load Music folder** to pick another.

## Install

```sh
./install.sh              # user install: desktop entry, icons, AppStream metadata
./install.sh --dry-run    # print what it would write, change nothing
./install.sh --uninstall  # remove exactly what it installed
```

Needs no flatpak and no root. Or the Flatpak route (see `flatpak/README.md`):
`flatpak-builder --user --install flatpak/dev.aubade.Aubade.yml` —
MPRIS, artwork, and audio all verified working inside the sandbox.

## Features

- **17 screens** — Home, Discover, Browse, Radio, Podcasts, Albums (+detail),
  Songs (sortable, filterable), Artists (+detail), Search, Queue, Now Playing
  (karaoke lyrics), Playlists (auto: Liked / Recent / Most played / New),
  Profile, Settings
- **Queue done right** — drag-drop reorder, Play Next / Add to Queue /
  per-row menus, persisted across restarts
- **Synced lyrics** — embedded tags → `.lrc` sidecar → SQLite cache →
  LRCLIB/ovh fallback, karaoke highlight with adjustable sync offset
- **Real stats** — plays, skips, likes drive Discover mixes, genre radio,
  top-artist hero, and history
- **Keyboard** — Space, arrows (±10s / volume), n/p, `/` search, Esc
- **Desktop-native** — MPRIS2 (media keys), Flatpak, dark-first purple glass theme

## Layout

- `aubade/ui.py` — window, view stack, Home/Search/Settings/Profile/playlist views
- `aubade/shell/` — `sidebar.py`, `playerbar.py`, `rail.py`, `nowplaying.py`
- `aubade/player.py` — GStreamer queue engine (gapless `about-to-finish`, shuffle/repeat, seek/volume)
- `aubade/store.py` — SQLite cache + stats (tracks, plays, skips, likes, queue)
- `aubade/library.py` — recursive scan + incremental `sync_library`
- `aubade/lyrics.py` — LRC parser + provider chain + karaoke index
- `aubade/art.py` — embedded/folder cover-art pipeline with disk thumb cache
- `aubade/mpris.py` — MPRIS2 on the session bus
- `aubade/theme.css` — design tokens inlined (GTK has no `var()`; glass is tint+rim, no real blur)
- `tests/` — 92 hermetic unit tests (`python3 -m unittest discover -s tests`)

## Design reference

The UI was cloned screen-by-screen from a React reference implementation
(17 screens, token-driven design system) kept alongside the project during
development.
