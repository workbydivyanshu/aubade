# Full-screen now-playing — design

Date: 2026-08-08
Status: approved, not yet implemented
Sub-project: 3 of 3

## Context

Aubade shows synced lyrics in a panel that replaces the album cover. This adds
a full-screen now-playing view where the lyrics are the main focus, in the style of
Apple Music: a blurred album-art backdrop, oversized typography, and minimal
transport controls.

Sub-projects 1 (rebrand) and 2 (online lyrics) are complete and merged to
`main`.

Two decisions were taken before this design:

- **The Apple Music look takes precedence over GNOME's HIG** where the two
  conflict. This is a personal application, and the distinctive look is the
  point.
- **Lyrics are the hero.** The full-screen view exists to show them well.

## Goal

A full-screen now-playing view that makes lyrics the centre of attention, looks
deliberate rather than default, and remains readable over any album art.

## Non-goals

- No library browsing, no queue management inside the full-screen view.
- No animation work beyond the existing crossfade and smooth scroll. Spring
  physics and bespoke transitions are how a polish project becomes a
  three-month project.
- No second lyrics implementation. The existing `LyricsView` is reused.
- No changes to lyrics resolution, caching, or sync. That is settled.

## Components

### `BlurredBackdrop` (`src/blurred_backdrop.rs`)

A custom widget that draws a `gdk::Texture` scaled to *cover* its allocation,
optionally blurred. Aspect ratio is preserved and overflow is centred; a
backdrop must never letterbox.

Already written during a spike and kept. It uses `Snapshot::push_blur(radius)`,
verified present in gtk4-rs 0.11.4.

Its only input is a texture. It performs no layout and knows nothing about
songs.

### `FullScreenView` (`src/fullscreen_view.rs` + `src/gtk/fullscreen-view.blp`)

A `Gtk.Overlay` stacking, back to front:

1. `BlurredBackdrop`
2. A fixed dark scrim
3. Content: small cover and track details top-left, `LyricsView` filling the
   middle, transport controls at the bottom

### `LyricsView`, reused

The same widget, with a `fullscreen` CSS class selecting a larger type scale.
One implementation means the sync behaviour cannot drift between the two views.

One behavioural addition: **distance-based fade**. Lines dim progressively with
distance from the active line, which is what makes the lyrics feel like they
move rather than merely highlight.

```rust
/// Opacity for a line `distance` rows from the active one.
pub fn opacity_for_distance(distance: usize) -> f64;
```

A pure function, so it is unit-tested rather than eyeballed.

## Readability over arbitrary artwork

White text over a bright album cover is unreadable. A **fixed dark scrim**
between backdrop and content is mandatory, not optional polish. This is the
same failure mode that caused the cover-overlay option to be rejected in
sub-project 1.

The scrim is a constant opacity rather than being derived from the artwork:
adaptive scrims are a tuning rabbit hole, and a fixed value that works for a
white cover works for every cover.

## Entry and exit

A new page in the existing `main_stack`, which already crossfades between
pages.

- Enter: a header bar button, or double-clicking the album cover
- Exit: `Esc`, or the same button
- Action: `win.fullscreen`, mirroring the existing `lyrics.toggle` pattern

## Ordering: blur is a separate, measured step

The backdrop ships **unblurred first**. Blur is enabled afterwards as a discrete
change, with frame timing measured in the real view.

This ordering exists because a spike attempting to measure blur in isolation
failed: the widget was bolted into a stack whose visible child is reassigned by
the lyrics logic, so it never mapped and never rendered. Every measurement taken
was of a widget that was not drawing.

What that spike did establish:

- GTK redraws strictly on demand. A static now-playing view rendered **once in
  18 seconds**, so steady-state blur cost is close to irrelevant.
- The real question is cost during crossfade and lyric scrolling, which can only
  be measured in the actual view.

If blur proves expensive, the mitigation is to blur a downscaled copy of the
cover — blurring a 200px texture and scaling up is visually near-identical and
costs a fraction. Failing that, the blurred result is cached to a texture per
song rather than recomputed per frame.

## Error handling

| Condition | Behaviour |
|---|---|
| Song has no cover art | Backdrop falls back to the cover-derived palette gradient already used by `update_style` |
| Song has no lyrics | Full-screen view still works: cover, details, and controls, with an empty lyrics area |
| No song playing | The full-screen action is insensitive |
| Texture fails to load | Backdrop draws nothing; the scrim and content remain readable |

The second row matters: the view must not look broken for the roughly one track
in three that has no lyrics.

## Testing

- `opacity_for_distance` is pure and gets unit tests: active line fully opaque,
  monotonic falloff, clamped at a floor rather than reaching zero.
- Everything else is visual and verified directly: build, launch on the user's
  Wayland session, capture with `grim`, inspect.
- Explicit visual checks: a **bright** cover and a **dark** cover, to prove the
  scrim works in both cases; and a song **without** lyrics.

## Build note

The blueprint target declares its output as a directory, so ninja cannot track
individual `.ui` files. After editing any `.blp`, run `touch src/gtk/*.blp`
before building or the compiled UI silently goes stale. This caused three
separate failures across sub-projects 1 and 3.

## Branching

Work happens on a `fullscreen` branch off `main`.
