# Aubade Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the project from Amberol to Aubade completely, so no functional reference to the old identity remains and the app runs under its own identity with the user's data intact.

**Architecture:** Four ordered passes, each its own commit — file renames, identity strings, code identifiers, translations — followed by new icon artwork and a data migration. Ordering matters: GResource paths must be rewritten before the bare `Amberol` type prefix, or the path replacement will corrupt already-renamed identifiers.

**Tech Stack:** Rust 2018, GTK4 (gtk4-rs 0.11), libadwaita 0.9, GStreamer, blueprint-compiler, meson + cargo.

## Global Constraints

- **Application id:** `io.github.workbydivyanshu.Aubade` (development: `io.github.workbydivyanshu.Aubade.Devel`)
- **GResource base path:** `/io/github/workbydivyanshu/Aubade`
- **GSettings schema id:** `io.github.workbydivyanshu.Aubade`, path `/io/github/workbydivyanshu/Aubade/`
- **Binary and crate name:** `aubade`
- **GObject type prefix:** `Aubade` (e.g. `AubadeWindow`)
- **Never remove or alter `SPDX-FileCopyrightText` headers.** GPL-3.0 requires them. `LICENSES/` is untouched.
- **No feature or UI changes.** Behaviour after the rebrand is identical to before.
- **No new dependencies.**
- Work on branch `rebrand`, cut from `lyrics`. One commit per pass.
- Run all commands from `/home/divyu/GitHub/amberol`.
- **Do not run `sed` across the whole tree in one shot.** Each pass targets specific files in a specific order.

---

### Task 1: Branch and file renames (Pass 1)

**Files:**
- Rename: `data/io.bassi.Amberol.desktop.in.in`, `.gschema.xml`, `.metainfo.xml.in.in`, `.service.in`
- Rename: `io.bassi.Amberol.json`
- Rename: 4 SVGs under `data/icons/hicolor/`

**Interfaces:**
- Consumes: nothing.
- Produces: the renamed paths that Task 2 edits the contents of.

- [ ] **Step 1: Create the branch**

```bash
git checkout lyrics && git checkout -b rebrand
git status --porcelain
```
Expected: on branch `rebrand`, clean tree.

- [ ] **Step 2: Rename the data files**

```bash
git mv data/io.bassi.Amberol.desktop.in.in      data/io.github.workbydivyanshu.Aubade.desktop.in.in
git mv data/io.bassi.Amberol.gschema.xml        data/io.github.workbydivyanshu.Aubade.gschema.xml
git mv data/io.bassi.Amberol.metainfo.xml.in.in data/io.github.workbydivyanshu.Aubade.metainfo.xml.in.in
git mv data/io.bassi.Amberol.service.in         data/io.github.workbydivyanshu.Aubade.service.in
git mv io.bassi.Amberol.json                    io.github.workbydivyanshu.Aubade.json
```

- [ ] **Step 3: Rename the icon files**

```bash
cd data/icons/hicolor
git mv scalable/apps/io.bassi.Amberol.svg              scalable/apps/io.github.workbydivyanshu.Aubade.svg
git mv scalable/apps/io.bassi.Amberol.Devel.svg        scalable/apps/io.github.workbydivyanshu.Aubade.Devel.svg
git mv symbolic/apps/io.bassi.Amberol-symbolic.svg     symbolic/apps/io.github.workbydivyanshu.Aubade-symbolic.svg
git mv symbolic/apps/io.bassi.Amberol.Devel-symbolic.svg symbolic/apps/io.github.workbydivyanshu.Aubade.Devel-symbolic.svg
cd /home/divyu/GitHub/amberol
```

- [ ] **Step 4: Update the build files that reference those filenames**

`data/meson.build` and `data/icons/meson.build` refer to the old filenames. Replace `io.bassi.Amberol` with `io.github.workbydivyanshu.Aubade` in both:

```bash
sed -i 's/io\.bassi\.Amberol/io.github.workbydivyanshu.Aubade/g' data/meson.build data/icons/meson.build
grep -rn "io.bassi" data/ || echo "clean"
```
Expected: `clean`.

- [ ] **Step 5: Update `application_id`**

`data/icons/meson.build` does not hardcode the icon filenames — it derives them
from `application_id` in the top-level `meson.build:48`. The renames in Steps 2
and 3 therefore break configuration until this moves with them:

```bash
sed -i "s/application_id = 'io\.bassi\.Amberol@0@'/application_id = 'io.github.workbydivyanshu.Aubade@0@'/" meson.build
grep -n "^application_id" meson.build
```
Expected: `application_id = 'io.github.workbydivyanshu.Aubade@0@'.format(profile)`.

The `project()` name stays `amberol` for now; that belongs to Task 2.

- [ ] **Step 6: Verify meson configures**

```bash
rm -rf builddir && meson setup builddir -Dprofile=development 2>&1 | tail -5
```
Expected: configuration succeeds with no "File ... does not exist" error.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(rebrand): rename data and icon files to Aubade"
```

---

### Task 2: Identity strings (Pass 2)

**Files:**
- Modify: `meson.build`, `Cargo.toml`
- Modify: `data/io.github.workbydivyanshu.Aubade.desktop.in.in`
- Modify: `data/io.github.workbydivyanshu.Aubade.metainfo.xml.in.in`
- Modify: `data/io.github.workbydivyanshu.Aubade.gschema.xml`
- Modify: `data/io.github.workbydivyanshu.Aubade.service.in`
- Modify: `io.github.workbydivyanshu.Aubade.json`

**Interfaces:**
- Consumes: renamed paths from Task 1.
- Produces: the gschema id `io.github.workbydivyanshu.Aubade` that the running app looks up at startup.

- [ ] **Step 1: Rewrite the identity in the data files**

```bash
sed -i 's/io\.bassi\.Amberol/io.github.workbydivyanshu.Aubade/g; s/Amberol/Aubade/g' \
  data/io.github.workbydivyanshu.Aubade.desktop.in.in \
  data/io.github.workbydivyanshu.Aubade.metainfo.xml.in.in \
  data/io.github.workbydivyanshu.Aubade.gschema.xml \
  data/io.github.workbydivyanshu.Aubade.service.in \
  io.github.workbydivyanshu.Aubade.json
```

- [ ] **Step 2: Confirm the gschema id and path**

```bash
grep -n "schema id=\|path=" data/io.github.workbydivyanshu.Aubade.gschema.xml
```
Expected exactly:
```
<schema id="io.github.workbydivyanshu.Aubade" path="/io/github/workbydivyanshu/Aubade/">
```
If the path lost its trailing slash or kept the old segments, fix it by hand. A
wrong path makes the app abort at startup with "Settings schema not installed".

- [ ] **Step 3: Update meson project name and Cargo package name**

In `meson.build`, change the `project(` name argument from `'amberol'` to `'aubade'`.
In `Cargo.toml`, change `name = "amberol"` to `name = "aubade"`.

Also update the binary name reference in `src/meson.build`: it uses
`meson.project_name()`, so it follows automatically — verify with:

```bash
grep -n "project(" meson.build | head -2
grep -n '^name' Cargo.toml
```
Expected: `project('aubade',` and `name = "aubade"`.

- [ ] **Step 4: Validate the desktop and metainfo files**

```bash
rm -rf builddir && meson setup builddir -Dprofile=development >/dev/null 2>&1
ninja -C builddir 2>&1 | tail -3
desktop-file-validate builddir/data/io.github.workbydivyanshu.Aubade.Devel.desktop && echo "desktop OK"
appstreamcli validate builddir/data/io.github.workbydivyanshu.Aubade.Devel.metainfo.xml 2>&1 | tail -3
```
Expected: build succeeds, `desktop OK`. `appstreamcli` may emit style warnings;
errors are failures, warnings are acceptable.

If the generated filenames differ, list `builddir/data/` and use the actual names.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(rebrand): rename application identity to Aubade"
```

---

### Task 3: Code identifiers (Pass 3)

**Files:**
- Modify: `src/amberol.gresource.xml` (renamed to `src/aubade.gresource.xml`)
- Modify: all `src/**/*.rs` and `src/gtk/*.blp`
- Modify: `src/meson.build`, `src/application.rs`, `src/utils.rs`

**Interfaces:**
- Consumes: the app id from Task 2.
- Produces: a fully renamed codebase. Nothing later depends on internals.

**This is the highest-risk task.** GResource paths and GObject type names are
resolved at runtime. A mismatch compiles cleanly and panics on launch.
**Order is mandatory:** replace the resource *path* before the bare `Amberol`
prefix, otherwise the path replacement corrupts already-renamed identifiers.

- [ ] **Step 1: Rename the gresource file and update its reference**

```bash
git mv src/amberol.gresource.xml src/aubade.gresource.xml
sed -i "s/'amberol'/'aubade'/; s/amberol\.gresource/aubade.gresource/g" src/meson.build
grep -n "gresource" src/meson.build | head -4
```
Expected: `gnome.compile_resources('aubade', 'aubade.gresource.xml', ...)`.

- [ ] **Step 2: Replace the resource path FIRST, everywhere**

```bash
grep -rl "/io/bassi/Amberol" src/ | xargs sed -i 's#/io/bassi/Amberol#/io/github/workbydivyanshu/Aubade#g'
grep -rn "io/bassi" src/ || echo "no resource paths remain"
```
Expected: `no resource paths remain`.

- [ ] **Step 3: Replace the GObject type prefix**

```bash
grep -rl "Amberol" src/ | xargs sed -i 's/Amberol/Aubade/g'
grep -rn "Amberol" src/ | grep -v SPDX || echo "no type names remain"
```
Expected: `no type names remain`.

- [ ] **Step 4: Replace the cache directory name**

There are four occurrences in `src/utils.rs`, at lines 69, 262, 275 and 304.
Missing one silently splits the cache across two directories.

```bash
sed -i 's/push("amberol")/push("aubade")/g' src/utils.rs
grep -c 'push("aubade")' src/utils.rs
```
Expected: `4`.

- [ ] **Step 5: Confirm resource-base-path matches the gresource prefix**

```bash
grep -n "resource-base-path" src/application.rs
```
Expected: `"/io/github/workbydivyanshu/Aubade"`. This string must equal the
`prefix` in `src/aubade.gresource.xml`. If they differ the app panics at startup
with "Unable to find aubade.gresource" or fails template init.

```bash
grep -n "prefix=" src/aubade.gresource.xml
```
Both must read `/io/github/workbydivyanshu/Aubade`.

- [ ] **Step 6: Build and run the unit tests**

```bash
rm -rf builddir && meson setup builddir -Dprofile=development >/dev/null 2>&1
ninja -C builddir 2>&1 | grep -E "^error|error\[|warning|Finished" | head -10
cargo test 2>&1 | grep -E "test result|^error"
```
Expected: build finishes with no errors or warnings; `29 passed`.

- [ ] **Step 7: Launch the app and screenshot it**

A clean build proves nothing here — template bindings fail only at runtime.

```bash
cp builddir/src/aubade.gresource builddir/src/debug/ 2>/dev/null
XDG_RUNTIME_DIR=/run/user/1001 WAYLAND_DISPLAY=wayland-1 GDK_BACKEND=wayland \
  meson devenv -C builddir ./src/debug/aubade \
  "/home/divyu/Music/a literal rollercoaster!!!/a little more time - ROLE MODEL.opus" &
```

Wait for the window, then capture it:

```bash
export XDG_RUNTIME_DIR=/run/user/1001
export HYPRLAND_INSTANCE_SIGNATURE=5c9377c15f85c50648f35ca5a213754f95b93ca0_1785760842_966495143
G=$(hyprctl clients -j | python3 -c "import json,sys; c=[x for x in json.load(sys.stdin) if 'Aubade' in x['class']][0]; print(f\"{c['at'][0]},{c['at'][1]} {c['size'][0]}x{c['size'][1]}\")")
WAYLAND_DISPLAY=wayland-1 grim -g "$G" /tmp/aubade-verify.png
```

Read the screenshot. Required: the window renders, and the lyrics button is
present in the header bar (this song has a sidecar `.lrc`). Any startup panic
means the resource path or a template binding is wrong — re-check Step 5.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(rebrand): rename code identifiers and resource paths to Aubade"
```

---

### Task 4: Translations (Pass 4)

**Files:**
- Modify: `po/*.po` (54 files), `po/POTFILES.in`, `po/LINGUAS` if it names the domain

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing later depends on this.

- [ ] **Step 1: Update POTFILES for the renamed source paths**

`po/POTFILES.in` lists source files by path. The `.blp` and `.rs` names did not
change, but the gresource filename did.

```bash
grep -n "amberol" po/POTFILES.in || echo "no path changes needed"
```
If it lists `src/amberol.gresource.xml`, update it to `src/aubade.gresource.xml`.

- [ ] **Step 2: Replace the app name across the catalogues**

```bash
sed -i 's/io\.bassi\.Amberol/io.github.workbydivyanshu.Aubade/g; s/Amberol/Aubade/g' po/*.po po/*.pot 2>/dev/null
grep -rl "Amberol" po/ | head -5 || echo "translations clean"
```
Expected: `translations clean`.

Accepted loss: where the app name appeared inside a translatable string, the
msgid has changed and that string's existing translations are now orphaned.
This affects proper-noun occurrences only.

- [ ] **Step 3: Verify the build still succeeds with translations**

```bash
ninja -C builddir 2>&1 | grep -E "^error|Finished" | head -5
```
Expected: build finishes.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(rebrand): update translation catalogues to Aubade"
```

---

### Task 5: Icon artwork

**Files:**
- Replace contents: `data/icons/hicolor/scalable/apps/io.github.workbydivyanshu.Aubade.svg`
- Replace contents: `data/icons/hicolor/scalable/apps/io.github.workbydivyanshu.Aubade.Devel.svg`
- Replace contents: `data/icons/hicolor/symbolic/apps/io.github.workbydivyanshu.Aubade-symbolic.svg`
- Replace contents: `data/icons/hicolor/symbolic/apps/io.github.workbydivyanshu.Aubade.Devel-symbolic.svg`

**Interfaces:**
- Consumes: the filenames established in Task 1.
- Produces: nothing.

- [ ] **Step 1: Inspect the existing icon for style reference**

```bash
head -30 data/icons/hicolor/scalable/apps/io.github.workbydivyanshu.Aubade.svg
```
Note the canvas size and structure. GNOME app icons are 128×128 with a rounded
base shape; symbolic icons are 16×16 monochrome.

- [ ] **Step 2: Draw the app icon**

Write a 128×128 SVG on a dawn motif: a sun cresting a horizon line over a
rounded base, in warm GNOME palette tones (`#ffbe6f`, `#ff7800`, `#e66100` for
the sun; `#241f31` for the horizon). Keep it flat — no gradients meshes, no
filters — so it renders correctly at small sizes.

- [ ] **Step 3: Draw the symbolic variant**

A 16×16 monochrome SVG, single `fill="#222222"` path, same motif reduced to its
silhouette. Symbolic icons are recoloured by GTK, so the fill colour is a
placeholder and must be a solid colour, not `currentColor`.

- [ ] **Step 4: Draw the devel variants**

Copy both, and desaturate the app-icon variant to blue-grey tones
(`#99c1f1`, `#3584e4`, `#1a5fb4`) so development builds are visually distinct
from release builds, per GNOME convention.

- [ ] **Step 5: Verify the icons render**

```bash
rsvg-convert -w 128 -h 128 data/icons/hicolor/scalable/apps/io.github.workbydivyanshu.Aubade.svg -o /tmp/icon-check.png && echo "renders"
```
Expected: `renders`. If `rsvg-convert` is unavailable, use
`magick convert` instead. Read `/tmp/icon-check.png` and confirm it looks
correct — an SVG that parses is not necessarily an SVG that looks right.

- [ ] **Step 7: Commit**

```bash
git add data/icons/
git commit -m "feat(rebrand): add Aubade icon artwork"
```

---

### Task 6: User data migration and final verification

**Files:**
- No source changes. This is a one-off operation on the user's machine.

**Interfaces:**
- Consumes: the new app id and cache directory name.
- Produces: the completion gate for the whole rebrand.

- [ ] **Step 1: Migrate the cache directory**

```bash
cp -rn ~/.cache/amberol/. ~/.cache/aubade/ 2>/dev/null || cp -r ~/.cache/amberol ~/.cache/aubade
ls ~/.cache/aubade/playlists/current.pls && echo "queue migrated"
```
Expected: `queue migrated`. `~/.cache/amberol` is left in place as a fallback;
do not delete it.

- [ ] **Step 2: Migrate GSettings values**

```bash
gsettings list-recursively io.bassi.Amberol 2>/dev/null | while read -r _schema key value; do
  gsettings set io.github.workbydivyanshu.Aubade "$key" "$value" 2>/dev/null \
    && echo "migrated $key"
done
```
If the old schema is not installed on the host this produces no output, which is
fine — the app falls back to defaults.

- [ ] **Step 3: Run the completion grep**

```bash
grep -rI "io\.bassi\|Amberol" . --exclude-dir=builddir --exclude-dir=.git --exclude-dir=target \
  | grep -v "SPDX-FileCopyrightText" | grep -v "^\./po/.*#" | head -20
```
Expected: no output, or matches only inside GPL copyright headers and `.po`
translator comments. Any other match is an incomplete rename — fix it.

- [ ] **Step 4: Full build and test**

```bash
rm -rf builddir && meson setup builddir -Dprofile=development >/dev/null 2>&1
ninja -C builddir 2>&1 | grep -E "^error|warning|Finished"
cargo test 2>&1 | grep "test result"
```
Expected: build finishes with no errors or warnings; `29 passed`.

- [ ] **Step 5: Launch and verify end to end**

```bash
cp builddir/src/aubade.gresource builddir/src/debug/ 2>/dev/null
XDG_RUNTIME_DIR=/run/user/1001 WAYLAND_DISPLAY=wayland-1 GDK_BACKEND=wayland \
  meson devenv -C builddir ./src/debug/aubade \
  "/home/divyu/Music/a literal rollercoaster!!!/a little more time - ROLE MODEL.opus" &
```

Capture and read the screenshot as in Task 3 Step 7. Required:

1. The window opens with no startup panic
2. The lyrics button is present in the header bar
3. The saved queue from the migrated cache is present in the playlist sidebar

- [ ] **Step 6: Commit any fixes**

```bash
git status --porcelain
```
If Step 3 required fixes, commit them:
```bash
git add -A && git commit -m "refactor(rebrand): fix remaining Amberol references"
```
If the tree is clean, nothing to commit — the rebrand is complete.

---

## Notes for the implementer

- **Order within Task 3 is not optional.** Resource path first, then type prefix.
  Reversing it produces `/io/bassi/Aubade`, which fails at runtime only.
- **`sed 's/Amberol/Aubade/g'` would also rewrite SPDX headers if they contained
  the word.** They do not — they carry the author's name, not the app name — but
  verify with `git diff` before committing Task 3.
- **The app cannot be rebuilt while it is running.** `cp` to a running binary
  fails with "Text file busy". Kill the process before rebuilding.
- **Run the built binary as `./src/debug/aubade` under `meson devenv`,** which
  sets `MESON_DEVENV` and `GSETTINGS_SCHEMA_DIR`. Running the binary directly
  fails to find its gresource and its schema.
