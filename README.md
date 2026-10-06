# Aubade (native)

GTK4 + libadwaita music player, Apple-Music-concept UI, local files only.
Engine: GStreamer `playbin` (gapless via `about-to-finish`). Tags: mutagen.
Reference engine this UI will eventually absorb: Tauon fork in `../src/`.

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

Needs no flatpak and no root: it reuses `flatpak/dev.aubade.Aubade.desktop` and
`flatpak/icons/` into `~/.local/share`, adds an `aubade` launcher in
`~/.local/bin` for the desktop `Exec=`, and refreshes the icon/desktop caches.
The app keeps running from this tree, so move the directory and re-run the
script. See `flatpak/README.md` for the flatpak route.

## Layout

- `aubade/__main__.py` — entry, `Gst.init`
- `aubade/ui.py` — 3-pane window; center is a view stack (Home / Albums / Songs / Artists), full-width floating glass player bar below
- `aubade/theme.css` — ported from the web reference tokens (`~/GitHub/aubade-reference/src/styles/tokens.css`); GTK has no var()/backdrop-filter so values are inlined, glass is tint+rim approximation
- `aubade/assets/backdrop.jpg` — static aurora-canyon night backdrop (reference ambience lane, frozen single frame)
- `aubade/player.py` — queue, shuffle, repeat off→all→one, seek/volume; GStreamer callbacks marshaled to main thread, clean `shutdown()`
- `aubade/lyrics.py` — Tauon-mirror lyrics: embedded tags → `.lrc` sidecar → SQLite cache → LRCLIB/ovh fallback; LRC parser + karaoke index
- `aubade/mpris.py` — MPRIS2 on the session bus (`org.mpris.MediaPlayer2.aubade`): transport, metadata + art, volume/shuffle/repeat; GNOME + media keys work
- `aubade/library.py` — recursive scan + `sync_library` (incremental, mtime-based)
- `aubade/store.py` — SQLite cache (`~/.local/share/aubade/library.db`): tracks, plays, skips, likes + stats (top artist/album/genres, recent plays)
- `aubade/art.py` — Tauon-style art: embedded tags → folder.jpg → subdirs; Pillow LANCZOS thumbs cached in `~/.cache/aubade/thumbs/`
- `aubade/theme.css` — Aubade purples

No mock data anywhere: empty states render until real plays/genres/art exist.
