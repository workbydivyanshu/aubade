# Rebrand to Aubade — design

Date: 2026-08-07
Status: approved, not yet implemented
Sub-project: 1 of 3

## Context

This fork of Amberol is becoming a personal, portfolio-grade local music
player. The work splits into three independent sub-projects, each with its own
spec, plan, and build cycle:

1. **Rebrand to Aubade** (this document)
2. **Network lyrics fetching** — LRCLIB provider, cache, sidecar fallback
3. **Apple Music-grade UI** — visual overhaul

Rebranding goes first because it touches nearly every file. Doing it after the
UI work would mean redoing every string, screenshot, and asset.

The name was checked against crates.io (0 results), Flathub (no such app), and
GitHub (several unrelated repos — an Obsidian theme, a markdown tool — but no
music player).

## Goal

Rename the project from Amberol to Aubade completely and correctly, so that no
functional reference to the old identity remains, the app installs and runs
under its own identity, and the user's existing queue and settings survive.

## Non-goals

- No feature work. Behaviour after the rebrand is identical to behaviour before.
- No UI or theme changes. Those belong to sub-project 3.
- No new dependencies.
- No removal of GPL copyright headers. The licence requires them and they stay.

## Identity

| Field | Value |
|---|---|
| Display name | Aubade |
| Application id | `io.github.workbydivyanshu.Aubade` |
| Development id | `io.github.workbydivyanshu.Aubade.Devel` |
| Binary and crate | `aubade` |
| GResource base path | `/io/github/workbydivyanshu/Aubade` |
| GSettings schema id | `io.github.workbydivyanshu.Aubade` |
| GSettings path | `/io/github/workbydivyanshu/Aubade/` |
| GObject type prefix | `Aubade` (e.g. `AubadeWindow`, `AubadeLyricsView`) |
| CSS names | unchanged where generic; `songcover`, `lyricsview` etc. stay |
| User cache directory | `~/.cache/aubade` |

## Surface area (measured, not estimated)

- 53 files containing `Amberol` / `amberol` / `io.bassi`, 271 occurrences,
  excluding `po/` and `builddir/`
- 54 `.po` translation files
- 4 files named `data/io.bassi.Amberol.*`
- 4 icon SVGs under `data/icons/`
- 1 Flatpak manifest, `io.bassi.Amberol.json`

## Approach: four passes, four commits

A single find-and-replace across 271 occurrences would compile cleanly and then
fail at runtime. GResource paths and template bindings are resolved at runtime,
so a mismatch surfaces as a panic during template initialisation, not as a
compile error. The rename is therefore split into four passes, each committed
and verified separately so a failure is isolated to one pass and revertable with
`git reset`.

### Pass 1 — file renames

`git mv` for:

- `data/io.bassi.Amberol.desktop.in.in` → `data/io.github.workbydivyanshu.Aubade.desktop.in.in`
- `data/io.bassi.Amberol.gschema.xml` → `data/io.github.workbydivyanshu.Aubade.gschema.xml`
- `data/io.bassi.Amberol.metainfo.xml.in.in` → `data/io.github.workbydivyanshu.Aubade.metainfo.xml.in.in`
- `data/io.bassi.Amberol.service.in` → `data/io.github.workbydivyanshu.Aubade.service.in`
- `io.bassi.Amberol.json` → `io.github.workbydivyanshu.Aubade.json`
- the four icon SVGs under `data/icons/hicolor/`

`git mv` preserves history across the rename.

Verification: `meson setup` reconfigures without error.

### Pass 2 — identity strings

`meson.build` project name, `Cargo.toml` package name, and the contents of the
renamed data files: desktop entry, metainfo, gschema id and path, DBus service
name, Flatpak manifest.

Verification: build succeeds; `desktop-file-validate` and `appstreamcli
validate` both pass.

### Pass 3 — code identifiers

This is the highest-risk pass, and all of it must change together:

- GObject type names (`AmberolWindow` → `AubadeWindow`, and every sibling)
- `#[template(resource = "/io/bassi/Amberol/...")]` attributes
- `src/amberol.gresource.xml` prefixes and the file's own name
- `resource-base-path` property in `application.rs`
- `src/config.rs.in` consumers
- The cache directory name in `utils.rs` — four occurrences, at lines 69, 262,
  275 and 304. Missing one silently splits the cache between two directories.

Verification: build succeeds, `cargo test` passes, **and the app launches and is
screenshotted**. A template-binding mismatch cannot be caught any other way.

### Pass 4 — translations

Update app-name references across the 54 `.po` files. Translated UI strings are
left intact.

Known and accepted loss: where the app name appears inside a translatable
string, changing it changes the msgid and orphans that string's existing
translations. This affects proper-noun occurrences only, which are largely
untranslated in practice.

Verification: build succeeds; no `io.bassi` or `Amberol` remains outside GPL
headers and translator comments.

## Icon

A new scalable SVG in the GNOME app-icon idiom, on a dawn motif fitting the
name, drawn to sit naturally alongside other GNOME applications. Three assets:

- `io.github.workbydivyanshu.Aubade.svg` — the app icon
- `io.github.workbydivyanshu.Aubade-symbolic.svg` — monochrome symbolic variant
- `io.github.workbydivyanshu.Aubade.Devel.svg` — visually distinct development
  variant, per GNOME convention, so development builds are identifiable

Filenames must match the application id exactly or the icon silently fails to
resolve.

## User data migration

Changing the application id orphans existing settings and cache. The rebrand
includes a one-time migration:

- Copy `~/.cache/amberol` to `~/.cache/aubade`, preserving the saved queue at
  `playlists/current.pls`, cached cover art, and generated waveforms
- Read the old GSettings values and write them into the new schema

This is a one-off operation performed during the rebrand, not code shipped in
the application.

The Flathub installation of `io.bassi.Amberol` is untouched: different id,
different data directories, different binary.

## Attribution

GPL-3.0 requires preserving copyright notices, and they are preserved. Every
existing `SPDX-FileCopyrightText` header stays exactly as it is, `LICENSES/`
is untouched, and the full git history is retained.

## Risk register

| Risk | Consequence | Mitigation |
|---|---|---|
| GSettings schema id/path mismatch | App aborts at startup with "Settings schema not installed" | Pass 2 verified by launching the app, not just building |
| GResource path mismatch | Panic during template init, at runtime only | Pass 3 changes all paths atomically; verified by launch + screenshot |
| Icon filename ≠ app id | Icon silently absent | Filenames derived directly from the app id; verified visually |
| Missed occurrence | Stale branding, or a broken reference | Completion gate is a grep returning zero non-header matches |
| Bad pass | Broken build | Each pass is its own commit; `git reset` reverts one pass |

## Verification

The rebrand is complete when all of the following hold:

1. `cargo test` — 29 tests pass
2. Full meson build with zero warnings
3. `grep -rI "io\.bassi\|Amberol" .` returns matches only in GPL copyright
   headers and `.po` translator comments
4. `desktop-file-validate` passes on the new desktop file
5. `appstreamcli validate` passes on the new metainfo
6. The application launches on the user's Wayland session and is screenshotted:
   window renders, the lyrics button appears for a song with a sidecar `.lrc`,
   the toggle swaps to the lyrics view, and lyrics scroll in sync
7. The migrated queue loads — the previously saved playlist is present

Verification is performed directly, using `grim` against the user's Wayland
socket, rather than delegated.

## Branching

Work happens on a `rebrand` branch off `lyrics`, four commits, one per pass.
