# Cloning Octave for an offline library

Written against 124 clean captures in `~/octave-shots2` and the measurements in
[OCTAVE.md](OCTAVE.md). Read that first for the palette, the glass tiers and
the type scale; this file is about structure and order of work.

## The gap, stated plainly

Octave is a **navigable application**: a permanent sidebar, a routed content
area, and a player docked across the bottom that never goes away.

Aubade is **one screen**. A header bar, a centred cover, controls beneath it,
and a queue in a slide-out sidebar. There are no pages, so there is nothing to
navigate between and nowhere for a sidebar to lead.

That is the whole difference. Every remaining item is decoration on top of it,
which is why the shell has to come first and cannot be skipped.

## What the captures show

### Shell, identical on every page

- Sidebar, `256px`, permanent, never collapses on desktop. Top to bottom: the
  wordmark with a collapse button, six nav rows, a rule, a `PINNED` section
  with an add button, pinned playlists, and a credit line pinned to the bottom.
- Nav row: `43px` tall, radius `28px`, icon then label at `15px/500`. The
  selected row is a filled pill and its icon takes the accent colour; the label
  does not.
- Top bar, `56px`: back and forward chevrons at the left, notifications and
  avatar at the right. Nothing else — no title.
- Content area is pure black and scrolls **inside itself**, not with the window.

### Home

- `Good evening`, `36px/700`, greeting varies with the hour.
- Right of it, a `Global`/`Local` segmented pill and a region chip.
- **Quick links**: a 4x2 grid of wide cards, each a `56px` square of artwork
  flush against the left edge with a label beside it. Dark fill, small radius.
- **Hero**: one full-width card, radius `~16px`, its background an ambient
  wash taken from the artwork. Inside: `172px` cover, a `#1 TODAY` eyebrow in
  caps, the title at `48px/700`, the artist, an accent `Play` pill and a
  circular share button.
- **Shelves**: heading at `24px/700` with a leading icon and a chevron, a grey
  one-line subtitle, `See all` to the right, then a horizontal row of square
  cards with the title and artist stacked beneath.

### Album

The strongest page, and the one worth getting right.

- The artwork, enormously enlarged and blurred, fills the entire header area
  edge to edge.
- The cover sits centred over it at `304px`, radius `24px`, with a drop shadow.
- Everything below is **centred**: an `ALBUM` eyebrow in spaced caps, the title
  at `48px/700`, the artist, then a meta line reading `2025 · 1 song · 715 fans`.
- A row of circular glass buttons at `48px` — shuffle, download, like, add,
  share, more — with the accent `Play` pill sitting among them.
- The track list follows: index, title over artist, duration right-aligned.
- **The accent is sampled from the artwork.** This record's Play button is
  `#d51815` because the car on its cover is red. The site-wide `#fb2c5a` is
  only the default.

## Order of work

### 1. The shell

Replace the single-window layout with sidebar, top bar, content stack and a
docked player bar. Nothing else on this list can be built until pages exist to
put things on.

The player moves out of the centre of the window and into a permanent bar, which
is a real loss — the current centred now-playing view is one of the better parts
of the app. It should become a page you can navigate *to*, not something that
disappears.

### 2. Home

The widget already exists and is reachable. It needs the quick-links grid and
the hero card, and its shelves need the heading treatment above.

### 3. Album page

Blurred artwork header, centred cover, artwork-derived accent, track list.
`blurred_backdrop.rs` and the palette extraction in `cover_cache.rs` already do
the two hard parts; this is mostly assembly.

### 4. Artist page, then search

Artist is shelves of albums plus a header. Search is a filter over
`Library::search`, which exists.

### 5. Type

Ship Inter and set negative tracking throughout. A large part of why Octave
does not look like a toolkit demo is that its type is tight and its own; the
default GNOME font will undo much of the rest of this work.

## What does not carry over

Radio, podcasts, `Global`/`Local`, region, `See all`, fan counts, `LOSSLESS`
badges and animated covers are all properties of a streaming catalogue. Building
shelves that need a server would leave the app looking like a client for
something that does not exist.

The offline equivalents already have data behind them: the hero becomes the most
played record, the recent shelf becomes recently added, and quick links become
pinned albums.
