# The Octave look, as measured

Values read off the running web app at `music.octavestreaming.com` via computed
style, not estimated from screenshots. The desktop player of the same name is
closed source — its repository carries only a licence and five images — so the
web app is the reference.

## Why this can be rebuilt in GTK4 at all

Octave's surfaces are CSS `backdrop-filter`: each panel blurs whatever the page
put behind it. GTK4 has no equivalent, and there is no way to blur arbitrary
content sitting underneath a widget.

It does not need one. Every glass surface in Octave sits over the same thing —
a dark page carrying a large, colourful, heavily blurred artwork glow. Aubade
already renders exactly that, in `src/blurred_backdrop.rs`, using
`snapshot.push_blur()`. So the look decomposes into two pieces GTK4 can do:

1. a blurred artwork backdrop filling the window, and
2. translucent panels with a lit bevel drawn on top of it.

The bevel is what sells it. Without blur, a flat translucent fill reads as a
grey box; with the two inset lines below it reads as glass.

## Colour

| Token | Value | Use |
|---|---|---|
| page background | `#000000` | behind the artwork glow |
| text primary | `#f5f5f7` | titles, headings |
| text muted | `#a3a3ad` | artist, secondary rows |
| text dim | `#6b6b76` | scroll affordances, disabled |
| accent | `#fb2c5a` | play, active state |
| accent soft | `#ff6f8b` | hover, gradient partner |
| glow warm | `#fb2c5a` at 22% | ambient page glow |
| glow cool | `#7850ff` at 18% | ambient page glow, second source |

Two ambient glows, warm and cool, are what keep a black page from reading as
flat. The now-playing view swaps them for colours sampled from the artwork —
Aubade already extracts a palette in `src/audio/cover_cache.rs`.

## Glass

Five tiers. Each is a fill plus a blur; the fill alone is the GTK4 fallback.

| Tier | Fill | Blur (web only) | Used for |
|---|---|---|---|
| subtle | `#ffffff` @ 6% | 24px, sat 180%, bright 104% | hover rows, inline chips |
| default | `#12141b` @ 42% | 38px, sat 210%, bright 108% | cards, sheets |
| bar | `#07080b` @ 52% | 36px, sat 200%, bright 110% | top bar, player bar |
| floating | `#12141c` @ 44% | 44px, sat 220%, bright 112% | circular overlay buttons |
| strong | `#101219` @ 48% | 46px, sat 220%, bright 110% | segmented controls, popovers |

Border: `rgba(255, 255, 255, 0.08)`, 1px.

The bevel, on every tier:

```
inset 0  1px 0 rgba(255, 255, 255, 0.18)
inset 0 -1px 0 rgba(0, 0, 0, 0.20)
```

The saturation boost is not decoration. Blurring desaturates; `saturate(210%)`
puts the colour back, which is why the panels pick up the artwork's hue instead
of going grey. Nothing in GTK4 reproduces it, so the fills above are already
chosen dark and low-alpha enough to let the backdrop's colour through.

## Geometry

- Corner radius: fully round (`9999px`) on every control — buttons, pills,
  segmented controls. Cards use a modest radius; artwork is square.
- Top bar height: `56px`.
- Shelf: horizontal scroll, `16px` gap, `234px` tall, `8px` bottom padding.
- Artwork sizes in use: `28px` inline, `40px` list row, `60px` player bar.
- Circular controls: `30px` small, `36px` standard, `44px` prominent.

## Type

Stack is SF Pro, falling back to Inter — which is the one to target on Fedora.

| Role | Size | Weight | Tracking |
|---|---|---|---|
| Page heading | 36px | 700 | `-0.9px` |
| Body | 16px | 400 | `-0.011em` |
| Pill label | 12px | 600 | `-0.011em` |

Negative tracking at every size is a large part of why it reads as Apple's
type rather than a default toolkit's.

## Pages

Routes are `/`, `/search`, `/browse`, `/radio`, `/podcasts`, `/library`,
`/album/:id`, `/artist/:id`, `/playlist/:id`. Radio and podcasts are streaming
only and have no offline meaning; the rest do.

Measured at a 1440x900 viewport.

### Sidebar, on every page

- Width `256px`, fill `#252526` at 40%, item gap `4px`.
- Nav row: `231x43`, radius `28px` (a pill, not a rectangle), label `15px/500`,
  icon-to-label gap `14px`. The selected row is a `#1c1c20` fill behind it.
- Playlist row below the nav: `56px` tall, radius `20px`, gap `12px`.
- The playlist list scrolls on its own, the nav above it does not.

### Library

- Grid gap: `24px` between rows, `16px` between columns.
- Filter control: `176x36`, radius `20px`, fill `#141417`.
- List rows: `52px` tall, radius `28px`.

### Album

- Cover: `304x304`, radius `24px`, with a drop shadow. Some carry a `<video>`
  of the same size, which is the animated artwork Apple ships; there is no
  offline equivalent and it can be ignored.
- Title `48px/700`, tracking `-1.2px` — larger than the `36px` used for page
  headings elsewhere, so the album title is the biggest type in the app.
- Behind it, an artwork image drawn far larger than its container
  (`1585x616` inside `1174`), cropped and blurred. This is the same effect as
  `blurred_backdrop.rs`.
- Play button: a `118x48` pill, label `14px/600`.
- Track rows: `52px` tall, radius `28px`, title `14px/500`, meta `12px/400`.
- Circular secondary buttons: `48x48`, white at 10%.

**The accent is per-album, not global.** This album's play button is `#d51815`,
against the site-wide `#fb2c5a`. The colour is sampled from the artwork, which
is why every album page feels like its own record. Aubade already extracts a
palette from cover art in `src/audio/cover_cache.rs`, so this is reproducible
rather than aspirational — and it matters more than any single measurement
here, because it is what stops the app looking the same for every album.

## Structure of the home view

A greeting that changes with the hour, a scope switch (Global/Local) and region
chip, then quick links, then a shelf of recent items, then a full-bleed hero
card ranked `#1 TODAY`, then genre browsing.

For an offline library the online-only parts have local equivalents: the hero
becomes the most played record, the recent shelf becomes recently added, and
the scope switch has no meaning and should go.
