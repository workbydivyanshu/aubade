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

## Structure of the home view

A greeting that changes with the hour, a scope switch (Global/Local) and region
chip, then quick links, then a shelf of recent items, then a full-bleed hero
card ranked `#1 TODAY`, then genre browsing.

For an offline library the online-only parts have local equivalents: the hero
becomes the most played record, the recent shelf becomes recently added, and
the scope switch has no meaning and should go.
