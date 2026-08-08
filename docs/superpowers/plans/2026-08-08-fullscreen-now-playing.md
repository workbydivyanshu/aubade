# Full-screen Now-Playing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A full-screen now-playing view with lyrics as the focus, over a blurred album-art backdrop.

**Architecture:** A new page in the existing `main_stack` holding an overlay of backdrop, scrim, and content. `LyricsView` is reused with a larger type scale. Blur is enabled and measured as a separate step, after the view demonstrably works.

**Tech Stack:** Rust 2018, GTK4 (gtk4-rs 0.11), libadwaita 0.9, blueprint-compiler, meson + cargo.

## Global Constraints

- **The Apple Music look takes precedence over GNOME HIG** where they conflict.
- **A fixed dark scrim between backdrop and content is mandatory.** White text over a bright cover is unreadable without it.
- **One lyrics implementation.** Reuse `LyricsView`; do not fork it.
- **The view must look right for a song with no lyrics** — roughly one track in three.
- **After editing any `.blp`, run `touch src/gtk/*.blp` before building.** The blueprint target's output is a directory, so ninja cannot track individual `.ui` files and they silently go stale. This has caused three separate failures already.
- Run the app as: `cp builddir/src/aubade.gresource builddir/src/debug/` then `meson devenv -C builddir ./src/debug/aubade`. Kill it before rebuilding — `cp` to a running binary fails.
- Work on branch `fullscreen`, already created off `main`.
- Run all commands from `/home/divyu/GitHub/amberol`.

---

### Task 1: Distance-based lyric fade

**Files:**
- Modify: `src/lyrics_view.rs`

**Interfaces:**
- Produces: `lyrics_view::opacity_for_distance(distance: usize) -> f64`

Done first because it is the only pure logic in this sub-project, so it can be
test-driven before any visual work begins.

- [ ] **Step 1: Write the failing tests**

Append to `src/lyrics_view.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn active_line_is_fully_opaque() {
        assert_eq!(opacity_for_distance(0), 1.0);
    }

    #[test]
    fn opacity_falls_off_monotonically() {
        let mut previous = opacity_for_distance(0);
        for distance in 1..8 {
            let current = opacity_for_distance(distance);
            assert!(
                current < previous,
                "distance {} was not dimmer than {}",
                distance,
                distance - 1
            );
            previous = current;
        }
    }

    #[test]
    fn distant_lines_stay_visible() {
        // Lines must never vanish entirely, or the lyrics look truncated
        // rather than faded.
        for distance in 0..100 {
            assert!(opacity_for_distance(distance) >= 0.25);
        }
    }
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cargo test lyrics_view 2>&1 | tail -5`
Expected: FAIL — `cannot find function opacity_for_distance`.

- [ ] **Step 3: Implement**

Add near the top of `src/lyrics_view.rs`, outside `mod imp`:

```rust
/// Dimmest a line may become. Lines never vanish entirely, or the lyrics read
/// as truncated rather than faded.
const MIN_LYRIC_OPACITY: f64 = 0.25;

/// Opacity for a line `distance` rows away from the active one.
pub fn opacity_for_distance(distance: usize) -> f64 {
    if distance == 0 {
        return 1.0;
    }
    let faded = 1.0 - (distance as f64 * 0.18);
    faded.max(MIN_LYRIC_OPACITY)
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cargo test lyrics_view 2>&1 | tail -5`
Expected: PASS — 3 tests.

- [ ] **Step 5: Apply the fade when the active line changes**

In `LyricsView::set_position_ms`, replace the block that swaps the CSS classes
with one that also sets per-label opacity:

```rust
        {
            let labels = imp.labels.borrow();
            if let Some(previous) = imp.active.get() {
                if let Some(label) = labels.get(previous) {
                    label.remove_css_class("lyric-active");
                }
            }
            if let Some(current) = active {
                if let Some(label) = labels.get(current) {
                    label.add_css_class("lyric-active");
                }

                // Fade with distance from the active line.
                for (index, label) in labels.iter().enumerate() {
                    let distance = index.abs_diff(current);
                    label.set_opacity(opacity_for_distance(distance));
                }
            } else {
                for label in labels.iter() {
                    label.set_opacity(1.0);
                }
            }
        }
```

- [ ] **Step 6: Build, test, commit**

```bash
cargo fmt
cargo test 2>&1 | grep "test result"
touch src/gtk/*.blp && ninja -C builddir 2>&1 | grep -E "^error|Finished"
git add src/lyrics_view.rs
git commit -m "feat(lyrics): fade lyric lines by distance from the active line"
```
Expected: 48 tests pass; build finishes.

---

### Task 2: The full-screen view, unblurred

**Files:**
- Create: `src/gtk/fullscreen-view.blp`, `src/fullscreen_view.rs`
- Modify: `src/main.rs`, `src/gtk/meson.build`, `src/aubade.gresource.xml`

**Interfaces:**
- Consumes: `BlurredBackdrop` (already in `src/blurred_backdrop.rs`), `LyricsView`.
- Produces:
  - `FullScreenView::set_cover(Option<gdk::Texture>)`
  - `FullScreenView::lyrics_view() -> LyricsView`
  - `FullScreenView::set_details(title: &str, artist: &str)`

Blur stays **off** in this task. `BlurredBackdrop` draws the cover plainly so
the layout can be judged without confounding it with performance.

- [ ] **Step 1: Disable blur temporarily**

In `src/blurred_backdrop.rs`, change the snapshot body so the blur is skipped:

```rust
                // Blur is enabled in a later task, once the view is proven and
                // its cost can be measured in context.
                snapshot.append_texture(texture, &graphene::Rect::new(x, y, w, h));
```

Remove the `snapshot.push_blur(BLUR_RADIUS);` and matching `snapshot.pop();`
lines. Leave `BLUR_RADIUS` in place with `#[allow(dead_code)]`.

- [ ] **Step 2: Create the blueprint**

Create `src/gtk/fullscreen-view.blp`:

```blueprint
// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026

using Gtk 4.0;

template $AubadeFullScreenView: Widget {
  Overlay {
    $AubadeBlurredBackdrop backdrop {}

    [overlay]
    Box scrim {
      styles [
        "fullscreen-scrim",
      ]
    }

    [overlay]
    Box {
      orientation: vertical;

      Box {
        spacing: 12;
        margin-start: 28;
        margin-end: 28;
        margin-top: 22;

        Image cover_thumb {
          pixel-size: 56;

          styles [
            "card",
          ]
        }

        Box {
          orientation: vertical;
          valign: center;

          Label title_label {
            xalign: 0;
            ellipsize: end;

            styles [
              "fullscreen-title",
            ]
          }

          Label artist_label {
            xalign: 0;
            ellipsize: end;

            styles [
              "fullscreen-artist",
            ]
          }
        }
      }

      $AubadeLyricsView lyrics_view {
        vexpand: true;

        styles [
          "fullscreen",
        ]
      }
    }
  }
}
```

- [ ] **Step 3: Register the blueprint**

Add `'fullscreen-view.blp',` to the `input: files(...)` list in
`src/gtk/meson.build`, keeping alphabetical order (it goes first).

Add to `src/aubade.gresource.xml`, inside the `prefix="/io/github/workbydivyanshu/Aubade"` block:

```xml
    <file preprocess="xml-stripblanks">fullscreen-view.ui</file>
```

- [ ] **Step 4: Write the widget**

Create `src/fullscreen_view.rs`:

```rust
// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use adw::subclass::prelude::*;
use gtk::{gdk, glib, prelude::*, CompositeTemplate};

use crate::{blurred_backdrop::BlurredBackdrop, lyrics_view::LyricsView};

mod imp {
    use super::*;

    #[derive(Debug, Default, CompositeTemplate)]
    #[template(resource = "/io/github/workbydivyanshu/Aubade/fullscreen-view.ui")]
    pub struct FullScreenView {
        #[template_child]
        pub backdrop: TemplateChild<BlurredBackdrop>,
        #[template_child]
        pub lyrics_view: TemplateChild<LyricsView>,
        #[template_child]
        pub cover_thumb: TemplateChild<gtk::Image>,
        #[template_child]
        pub title_label: TemplateChild<gtk::Label>,
        #[template_child]
        pub artist_label: TemplateChild<gtk::Label>,
    }

    #[glib::object_subclass]
    impl ObjectSubclass for FullScreenView {
        const NAME: &'static str = "AubadeFullScreenView";
        type Type = super::FullScreenView;
        type ParentType = gtk::Widget;

        fn class_init(klass: &mut Self::Class) {
            Self::bind_template(klass);
            klass.set_layout_manager_type::<gtk::BinLayout>();
            klass.set_css_name("fullscreenview");
        }

        fn instance_init(obj: &glib::subclass::InitializingObject<Self>) {
            BlurredBackdrop::static_type();
            LyricsView::static_type();
            obj.init_template();
        }
    }

    impl ObjectImpl for FullScreenView {
        fn dispose(&self) {
            while let Some(child) = self.obj().first_child() {
                child.unparent();
            }
        }
    }

    impl WidgetImpl for FullScreenView {}
}

glib::wrapper! {
    pub struct FullScreenView(ObjectSubclass<imp::FullScreenView>)
        @extends gtk::Widget,
        @implements gtk::Accessible, gtk::Buildable, gtk::ConstraintTarget;
}

impl Default for FullScreenView {
    fn default() -> Self {
        glib::Object::new::<Self>()
    }
}

impl FullScreenView {
    pub fn lyrics_view(&self) -> LyricsView {
        self.imp().lyrics_view.get()
    }

    pub fn set_cover(&self, cover: Option<gdk::Texture>) {
        let imp = self.imp();
        imp.cover_thumb.set_paintable(cover.as_ref().map(|t| t.upcast_ref()));
        imp.backdrop.set_texture(cover);
    }

    pub fn set_details(&self, title: &str, artist: &str) {
        self.imp().title_label.set_label(title);
        self.imp().artist_label.set_label(artist);
    }
}
```

Add `mod fullscreen_view;` to `src/main.rs`, in alphabetical order (after
`mod drag_overlay;`).

- [ ] **Step 5: Build**

```bash
touch src/gtk/*.blp && ninja -C builddir 2>&1 | grep -E "^error|error\[|-->|Finished" | head -8
```
Expected: `Finished`. A warning that `FullScreenView` is never constructed is
expected — Task 3 wires it up.

- [ ] **Step 6: Commit**

```bash
cargo fmt
git add src/ 
git commit -m "feat(fullscreen): add the full-screen now-playing view"
```

---

### Task 3: Wire it into the window

**Files:**
- Modify: `src/gtk/window.blp`, `src/window.rs`

**Interfaces:**
- Consumes: `FullScreenView` from Task 2.
- Produces: a working `win.fullscreen` action.

- [ ] **Step 1: Add the stack page**

In `src/gtk/window.blp`, add a third `StackPage` to `main_stack`, after the
`main-view` page:

```blueprint
          StackPage {
            name: "fullscreen";

            child: $AubadeFullScreenView fullscreen_view {};
          }
```

- [ ] **Step 2: Add the header bar button**

In the `main-view` header bar, beside `lyrics_button`:

```blueprint
                  Button fullscreen_button {
                    icon-name: "fullscreen-symbolic";
                    tooltip-text: _("Full Screen");
                    action-name: "win.fullscreen";
                    valign: center;
                  }
```

**Do not use a system-theme icon here.** `view-fullscreen-symbolic` was checked
and exists only in the user's MacTahoe theme, not in Adwaita on disk. A header
bar button is flat and transparent, so an icon that fails to paint leaves an
invisible-but-clickable button — the exact bug that cost hours in sub-project 1.

Ship the icon instead, as was done for `lyrics-symbolic`. Create
`src/assets/icons/fullscreen-symbolic.svg`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg height="16px" viewBox="0 0 16 16" width="16px" xmlns="http://www.w3.org/2000/svg">
    <path d="m 1 1 h 5 v 2 h -3 v 3 h -2 z m 9 0 h 5 v 5 h -2 v -3 h -3 z m -9 9 h 2 v 3 h 3 v 2 h -5 z m 12 0 h 2 v 5 h -5 v -2 h 3 z m 0 0" fill="#222222"/>
</svg>
```

Register it in `src/aubade.gresource.xml`, in the icons block:

```xml
    <file alias="fullscreen-symbolic.svg">assets/icons/fullscreen-symbolic.svg</file>
```

and use `icon-name: "fullscreen-symbolic";` in the blueprint.

- [ ] **Step 3: Register the template children**

In `src/window.rs`, add to the `imp` struct:

```rust
        #[template_child]
        pub fullscreen_view: TemplateChild<FullScreenView>,
        #[template_child]
        pub fullscreen_button: TemplateChild<gtk::Button>,
```

Add matching `TemplateChild::default(),` initialisers in `fn new()`, add
`FullScreenView::static_type();` to `instance_init`, and add
`fullscreen_view::FullScreenView` to the `use crate::{...}` block.

- [ ] **Step 4: Add the actions**

In `class_init`, beside the other window actions:

```rust
            klass.install_action("win.fullscreen", None, move |win, _, _| {
                win.set_window_mode(WindowMode::FullScreen);
            });
            klass.install_action("win.leave-fullscreen", None, move |win, _, _| {
                win.set_window_mode(WindowMode::MainView);
            });
```

Add `FullScreen` to the `WindowMode` enum, and handle it in
`set_window_mode` by setting `main_stack`'s visible child to `"fullscreen"`.

Bind `Escape` to leaving, in `Application::setup_gactions` alongside the other
accelerators:

```rust
            obj.set_accels_for_action("win.leave-fullscreen", &["Escape"]);
```

- [ ] **Step 5: Feed the view**

In `update_cover`, after the existing cover handling:

```rust
                self.imp().fullscreen_view.set_cover(Some(cover.clone()));
```

In `update_song`, after the existing detail updates:

```rust
        if let Some(song) = song {
            self.imp()
                .fullscreen_view
                .set_details(&song.title(), &song.artist());
        }
```

In `apply_lyrics`, mirror the lyrics into the full-screen view so both stay in
sync:

```rust
        imp.fullscreen_view.lyrics_view().set_lyrics(lyrics.clone());
```

And in the `position-ms` handler, drive both:

```rust
                        win.imp()
                            .fullscreen_view
                            .lyrics_view()
                            .set_position_ms(state.position_ms());
```

`Lyrics` derives `Clone`, so mirroring costs one clone per song change.

- [ ] **Step 6: Build and verify it opens**

```bash
touch src/gtk/*.blp && ninja -C builddir 2>&1 | grep -E "^error|Finished" | head -5
cargo test 2>&1 | grep "test result"
```
Expected: build finishes, 48 tests pass.

Then launch and confirm no startup panic:
```bash
pkill -f "src/debug/aubade"
cp builddir/src/aubade.gresource builddir/src/debug/
XDG_RUNTIME_DIR=/run/user/1001 WAYLAND_DISPLAY=wayland-1 GDK_BACKEND=wayland \
  meson devenv -C builddir ./src/debug/aubade "<a track with lyrics>" &
```
A missing template child panics at runtime, not compile time, so this launch is
the real check.

- [ ] **Step 7: Commit**

```bash
cargo fmt
git add src/
git commit -m "feat(fullscreen): wire the full-screen view into the window"
```

---

### Task 4: Styling

**Files:**
- Modify: `src/gtk/style.css`

- [ ] **Step 1: Add the styles**

Append to `src/gtk/style.css`:

```css
.fullscreen-scrim {
  background: rgb(0 0 0 / 55%);
}

.fullscreen-title {
  font-size: 1.3rem;
  font-weight: bold;
}

.fullscreen-artist {
  font-size: 1rem;
  opacity: 0.75;
}

lyricsview.fullscreen .lyric-line {
  font-size: 1.9rem;
  font-weight: 500;
  margin: 6px 0;
}

lyricsview.fullscreen .lyric-active {
  font-weight: bold;
}
```

The scrim is a fixed 55% black. Deriving it from the artwork is a tuning rabbit
hole, and a value that works for a white cover works for every cover.

- [ ] **Step 2: Verify visually**

Rebuild, launch, enter full screen, and capture:

```bash
export XDG_RUNTIME_DIR=/run/user/1001
export HYPRLAND_INSTANCE_SIGNATURE=5c9377c15f85c50648f35ca5a213754f95b93ca0_1785760842_966495143
CLS=$(hyprctl clients -j | python3 -c "import json,sys; c=[x for x in json.load(sys.stdin) if 'Aubade' in x['class']]; print(c[0]['class'] if c else 'NONE')")
echo "$CLS"
```

**Confirm the class is Aubade before capturing.** A stale geometry lookup
captured an unrelated window earlier in this project; verify, then capture.

Required checks:
1. Lyrics are legible over the artwork
2. The active line is clearly distinguished
3. Distant lines fade without vanishing

- [ ] **Step 3: Commit**

```bash
git add src/gtk/style.css
git commit -m "feat(fullscreen): style the full-screen now-playing view"
```

---

### Task 5: Enable blur and measure it

**Files:**
- Modify: `src/blurred_backdrop.rs`

This is deliberately last. The view is proven first, so any performance problem
is unambiguously the blur.

- [ ] **Step 1: Re-enable blur**

Restore the push/pop around the texture draw in `snapshot`:

```rust
                snapshot.push_blur(BLUR_RADIUS);
                snapshot.append_texture(texture, &graphene::Rect::new(x, y, w, h));
                snapshot.pop();
```

Remove the `#[allow(dead_code)]` from `BLUR_RADIUS`.

- [ ] **Step 2: Measure**

The widget already logs frame timing every 10 frames. Launch, enter full
screen, let a song play for 30 seconds, then read:

```bash
grep "backdrop:" <log> | tail -6
```

Interpretation:
- `last snapshot` under ~4 ms — blur is affordable, keep it
- 4–8 ms — apply the downscale mitigation in Step 3
- over 8 ms — cache the blurred result per song instead

- [ ] **Step 3: Apply the downscale mitigation only if needed**

If the measurement calls for it, blur a downscaled copy: render the texture into
a 200px-wide intermediate, blur that, and scale it up. Visually near-identical
at this radius, and a fraction of the cost.

Do not apply this pre-emptively. An unnecessary optimisation is harder to read
and might not be needed at all.

- [ ] **Step 4: Verify legibility with two covers**

Capture the view with a **bright** cover and a **dark** cover. The fixed scrim
must keep the lyrics readable in both. If the bright cover fails, raise the
scrim opacity — do not make it adaptive.

- [ ] **Step 5: Verify a song with no lyrics**

Launch with a track that has no lyrics and no sidecar, enter full screen, and
confirm the view still looks deliberate: cover, title, artist, controls, and an
empty lyrics area rather than a broken layout.

- [ ] **Step 6: Remove the instrumentation and commit**

Once measured, delete the frame-counting fields and the `debug!` from
`snapshot`. Shipping a per-frame log in a release build is noise.

```bash
cargo fmt
cargo test 2>&1 | grep "test result"
git add src/
git commit -m "feat(fullscreen): enable the blurred backdrop"
```

- [ ] **Step 7: Update the changelog**

Add to `CHANGES.md` under `### Added`:

```markdown
- A full-screen now-playing view with a blurred album-art backdrop and
  large synced lyrics.
```

```bash
git add CHANGES.md
git commit -m "docs: note the full-screen view in the changelog"
```

---

## Notes for the implementer

- **`touch src/gtk/*.blp` before every build after editing a blueprint.** The
  target's output is a directory, so ninja cannot detect stale `.ui` files. This
  has cost time three times already.
- **Template child errors panic at runtime**, never at compile time. Launching
  is the only real check that the blueprint and the Rust struct agree.
- **Verify the window class immediately before `grim` captures.** A geometry
  lookup from moments earlier can point at a window that has since exited.
- **The lyrics view is shared, not duplicated.** Both the panel and the
  full-screen view are fed from the same `apply_lyrics` and `position-ms`
  handlers, so they cannot drift out of sync.
