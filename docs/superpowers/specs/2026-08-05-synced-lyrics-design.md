# Synced lyrics for Amberol — design

Date: 2026-08-05
Status: approved, not yet implemented

## Context

Amberol deliberately has no lyrics support. From its README:

> it does not show you lyrics for your songs, or the Wikipedia page for your bands.

This is the maintainer's stated design philosophy, not a gap. Adding lyrics is
therefore a **personal fork**, not an upstream contribution. No merge request
will be filed.

Work happens on a `lyrics` branch off `main`. Commits stay atomic and disjoint
from upstream files where possible, so rebasing onto future Amberol releases
stays clean.

## Goal

Display time-synced lyrics from sidecar `.lrc` files, highlighting and
auto-scrolling to the line matching the current playback position.

## Non-goals

Deliberately excluded from v1:

- Network fetch of any kind (LRCLIB, Apple Music, or otherwise). No HTTP client
  dependency is added.
- Lyrics embedded in audio file tags (SYLT frames, `LYRICS`/`USLT` tag values).
- Word-level karaoke highlighting. Enhanced-LRC inline `<mm:ss.xx>` tags are
  stripped; sync stays line-level.
- Editing, saving, or fetching lyrics.
- Translation or romanisation lines.

## Constraints discovered in the codebase

Three findings shape the design. Each was verified against the source at commit
`c7f7a2b`.

1. **Position is truncated to whole seconds.** `src/audio/gst_backend.rs:79`
   already configures `set_position_update_interval(250)`, so GStreamer emits
   position updates at 4 Hz. But `send_update_position` at
   `src/audio/gst_backend.rs:26` calls `clock.seconds()`, discarding sub-second
   precision before anything else observes it. LRC timestamps are
   centisecond-precision, so a 1 Hz truncated tick would drift up to a second
   late.

2. **`position` has three consumers.** The `position` property on `AudioState`
   is read by the MPRIS controller, the elapsed/remaining labels
   (`src/window.rs:1278`), and the waveform view. Changing its unit would ripple
   through all three.

3. **The window layout is a split view.** `Adw.OverlaySplitView` with the
   playback column as `content` and the queue as `sidebar`
   (`src/gtk/window.blp:83`). The sidebar is capped at 330px, and an
   `Adw.Breakpoint` at `max-width: 560sp` collapses the split view.

## Architecture

### New: `src/lyrics/`

Pure logic. No GTK imports, so it runs under plain `cargo test`.

- **`lrc.rs`** — the parser and lookup.
  - `parse(&str) -> Lyrics`
  - `Lyrics { lines: Vec<LyricLine>, offset_ms: i64 }`
  - `LyricLine { time_ms: u64, text: String }`
  - `Lyrics::active_line_at(position_ms) -> Option<usize>` — `partition_point`
    binary search for the last line whose `time_ms + offset_ms <= position_ms`.

- **`loader.rs`** — sidecar discovery only.
  - For `/music/song.mp3`, try `/music/song.lrc`, then `/music/song.mp3.lrc`.
  - Extension matching is case-insensitive.
  - No directory scanning, no fuzzy matching, no network.

### New: `src/lyrics_view.rs` + `src/gtk/lyrics-view.blp`

A `Gtk.ScrolledWindow` containing a plain vertical `Gtk.Box` of `Gtk.Label`s.

A `Box` of labels rather than a `ListView` with a factory: lyric files run under
~100 lines, so virtualisation buys nothing, and direct label ownership makes the
scroll-to-center maths and per-line style classes straightforward.

The active label carries the CSS class `lyric-active`; all others carry
`lyric-inactive`. Both are defined in the existing `src/gtk/style.css`.

### Modified files

| File | Change |
|---|---|
| `src/audio/gst_backend.rs` | Keep milliseconds instead of truncating to seconds |
| `src/audio/state.rs` | Add a `position-ms` property beside the existing `position` |
| `src/audio/player.rs` | Set both properties in `update_position` |
| `src/audio/song.rs` | Add a `has-lyrics` property and the resolved `.lrc` path |
| `src/window.rs` | `lyrics-visible` property, toggle action, stack wiring |
| `src/gtk/window.blp` | Wrap `song_cover` and `lyrics_view` in a `Gtk.Stack` |
| `src/amberol.gresource.xml` | Register `lyrics-view.ui` |
| `src/meson.build`, `src/gtk/meson.build` | Register the new sources |

## Data flow

1. On song load, `loader.rs` resolves a sidecar path. Present and parseable to
   at least one line sets `has-lyrics = true`.
2. `gst_backend` emits millisecond positions at 4 Hz.
3. `player.rs` sets both `position` (seconds, unchanged semantics) and
   `position-ms`.
4. `lyrics_view` listens on `notify::position-ms`, resolves the active line,
   swaps the style classes, and scrolls that label to the vertical center.

**No new timers are introduced.** 250 ms granularity sits well below the
perceptual threshold for line-level lyrics, which turn over every few seconds.

Keeping `position` untouched means MPRIS, the time labels, and the waveform
carry zero risk from this change.

## UI

A `Gtk.Stack` named `cover_stack` inside `main_box` (`src/gtk/window.blp:103`)
holds `song_cover` and the new `lyrics_view`. The waveform, song details, and
playback controls below it are untouched, so the window never reflows and the
560sp breakpoint keeps working unchanged.

A toggle button in the `Adw.HeaderBar` is bound to a `lyrics-visible` property
through `install_property_action`, mirroring the existing `queue.toggle` pattern
at `src/window.rs:212`.

The button's `visible` binds to the current song's `has-lyrics`. **A song with
no `.lrc` file shows no toggle at all** — the button's presence is itself the
"this song has lyrics" indicator, and the UI never offers something absent.

## Error handling

Every failure degrades to "no lyrics". None produces a dialog, and none panics.

- No sidecar file — `has-lyrics = false`, toggle hidden. Not an error; not logged
  above `debug`.
- Malformed timestamp on a line — skip that line, keep the rest. `parse` returns
  a `Lyrics` for any input whatsoever and has no error variant.
- Unreadable file (permissions, IO error) — log at `warn`, treat as no lyrics.
- Parses to zero usable lines — treat as no lyrics.
- Encoding — read as UTF-8, fall back to lossy conversion. Strip a leading BOM,
  tolerate CRLF line endings.

## LRC format handling

- Timestamps: `[mm:ss.xx]` and `[mm:ss.xxx]`. Both accepted.
- Multiple timestamps on one line (a repeated chorus) expand into multiple
  entries sharing the same text.
- Metadata tags `[ar:]`, `[ti:]`, `[al:]`, `[by:]` are recognised and skipped.
- `[offset:±ms]` is applied as a global shift during lookup.
- A timestamped line with empty text is an instrumental gap. It is kept as an
  entry so the highlight correctly clears.
- Entries are sorted by time after parsing; input order is not trusted.
- Enhanced-LRC inline `<mm:ss.xx>` word tags are stripped from the line text.

## Testing

`src/lyrics/lrc.rs` is pure, so it gets real unit tests under `cargo test` with
no display server or GTK initialisation:

- Both timestamp precisions (`.xx`, `.xxx`)
- A line carrying multiple timestamps
- `[offset:]` applied, both positive and negative
- Metadata tags skipped, not rendered as lyrics
- Out-of-order timestamps sorted correctly
- Blank instrumental entries preserved
- Malformed junk lines skipped without losing valid neighbours
- Empty file, whitespace-only file
- BOM stripped, CRLF tolerated
- `active_line_at` before the first timestamp (returns `None`), exactly on a
  timestamp, between two, and after the last

Sidecar resolution in `loader.rs` is tested against a temp directory for each
naming variant and the absent case.

**Test fixtures use invented placeholder text, never real song lyrics.**

### Verification boundary

The build is verified natively: configure, compile, and `cargo test` all pass.

**The GUI is not launched by me.** Per standing instruction, no GUI application
is started on the live Hyprland session. Visual confirmation is done by the user,
against a command handed over at the end.

## Build prerequisite

The native build requires `gstreamer-play-1.0`, which is not installed on this
system. `meson setup` fails at `meson.build:15` without it. Two host packages
are needed before implementation can be verified:

- `gstreamer1-plugins-bad-free-devel` — provides `gstreamer-play-1.0.pc`.
  Available at 1.28.5-1.fc44, matching the installed GStreamer runtime.
- `blueprint-compiler` — compiles the `.blp` UI files. Available at 0.20.4-1.fc44.
  Optional: `subprojects/blueprint-compiler.wrap` lets meson fetch and build it
  instead, but the distro package is fewer moving parts.

The Flathub build is unaffected; both are purely host-build dependencies.

### Running the development build

The binary cannot be run directly out of `builddir`. `src/main.rs:57` selects the
gresource path from the `MESON_DEVENV` environment variable: unset, it loads from
the install prefix; set, it loads from beside the executable. The app also needs
`GSETTINGS_SCHEMA_DIR` pointed at the build tree, or it aborts on a missing
schema.

`meson devenv` supplies both, and cds into the build directory:

    meson devenv -C ~/GitHub/amberol/builddir ./src/amberol

The path is `./src/amberol` because devenv does not add `src/` to `PATH`.

The development profile builds application id `io.bassi.Amberol.Devel`, distinct
from the Flathub `io.bassi.Amberol`, so the two never collide.

The installed Flathub `io.bassi.Amberol` 2026.1 remains untouched; the native
build uses its own prefix, so it is always available as a fallback.
