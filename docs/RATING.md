# Aubade — where it stands

A scorecard kept honest against two reference points, re-scored as work lands.

- **Tauon** — the functional benchmark. A real library manager: gallery browsing,
  play counts, server streaming, themes.
- **Octave** — the visual benchmark. A translucent frameless panel floating over
  the wallpaper, album-card carousel, heavy frost. Thin on features, strong on
  identity.

They pull in different directions. Tauon is dense and information-rich; Octave
is sparse and atmospheric. "Better" has to mean something specific, so each row
below says what a 10 would look like.

## Scores

| Dimension | Aubade | Tauon | Octave | A 10 looks like |
|---|:--:|:--:|:--:|---|
| Import performance | 7 | 9 | ? | Library ready in seconds, incremental rescan |
| Library management | 1 | 9 | 3 | Albums, artists, persistent playlists as real entities |
| Browsing | 1 | 9 | 3 | Album grid, artist pages, search across the library |
| Lyrics | 9 | 5 | 1 | Synced, offset-correctable, online fallback, click-to-seek |
| Visual identity | 6 | 6 | 9 | Recognisable on sight, not a default toolkit window |
| Now playing | 8 | 6 | 7 | Full-screen, artwork-led, lyrics as the hero |
| Theming | 3 | 9 | 8 | User-controllable colour, background, density |
| Integrations | 2 | 9 | 1 | Scrobbling, presence, optional remote libraries |
| Code quality | 7 | ? | ? | Tested, bounded modules, honest error handling |

**Aubade overall: ~5.5/10.** Was 4/10 before the import work.

## What Aubade already wins

**Lyrics (9).** Sidecar plus LRCLIB with caching, negative caching, per-song
timing offset, click-to-seek, unsynced fallback. Validated against 2,000 real
files at a 99.3% parse rate. Neither reference player comes close.

**Now playing (8).** Full-screen view with a blurred backdrop and distance-faded
synced lyrics.

## What is actually missing

**Library management (1) is the gap that matters.** There is no library — only a
queue. No albums, no artists, no persistent playlists. Everything built so far
sits on top of a flat list of files, which is Amberol's deliberate design and
the thing Aubade has outgrown.

Browsing (1) cannot be fixed before this, because there is nothing to browse.

**Visual identity (6)** is competent but anonymous. It reads as a well-made GNOME
app rather than as Aubade. Octave scores 9 here on far less engineering, purely
through committing to a look.

## Ordering

1. **Library layer** — persistent database, incremental scan, albums and artists
   as entities, named playlists. Unblocks browsing, counts, and everything after.
2. **Browsing** — album grid, artist view, library-wide search.
3. **Visual identity** — commit to a look. Octave is the reference here, not Tauon.
4. **Integrations** — scrobbling, Discord presence (already built, parked on a
   branch).

Visual work comes third deliberately. A beautiful shell over a queue is still a
queue, and redesigning before the data model exists means redesigning twice.

## Measurements

Kept so results are comparable rather than remembered.

| Date | Change | Result |
|---|---|---|
| 2026-08-12 | Baseline import, 400 files | 18,229 ms |
| 2026-08-12 | O(1) duplicate detection | No measurable change — the scan was not the bottleneck |
| 2026-08-12 | Cover art loaded on first use | **1,931 ms**, 9.4x faster |

Profiling first would have found the artwork cost immediately. It was assumed to
be parsing or threading, and was neither.
