# Synced Lyrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display time-synced lyrics from sidecar `.lrc` files in Amberol, highlighting and auto-scrolling to the line matching playback position.

**Architecture:** A pure, GTK-free `src/lyrics/` module parses LRC text and resolves sidecar paths, fully unit-tested. GStreamer's existing 4 Hz position signal stops being truncated to whole seconds, feeding a new `position-ms` property that sits beside the untouched `position` property. A `LyricsView` widget swaps with the album cover inside a `Gtk.Stack`.

**Tech Stack:** Rust 2018, GTK4 (gtk4-rs 0.11), libadwaita 0.9, GStreamer 0.25, blueprint-compiler, meson + cargo.

## Global Constraints

- **No new runtime dependencies.** `regex` and `once_cell` are already in `Cargo.toml` and are the only crates the parser needs. No HTTP client, no `tempfile`.
- **Never change the unit or semantics of the existing `position` property.** It is consumed by the MPRIS controller, the elapsed/remaining labels, and the waveform view.
- **All new files carry the SPDX header** used throughout the repo:
  `// SPDX-FileCopyrightText: 2026` and `// SPDX-License-Identifier: GPL-3.0-or-later`
- **Test fixtures use invented placeholder text**, never real song lyrics.
- **Do not launch the GUI.** Verification is `cargo test` plus `ninja -C builddir`. The user performs all visual testing.
- Run all commands from `/home/divyu/GitHub/amberol` on branch `lyrics`.
- New `.rs` files need only a `mod` declaration in `src/main.rs`; `src/meson.build` drives cargo and never lists individual Rust files. New `.blp` files must be registered in **both** `src/gtk/meson.build` and `src/amberol.gresource.xml`.

---

### Task 1: LRC parser

**Files:**
- Create: `src/lyrics/mod.rs`
- Create: `src/lyrics/lrc.rs`
- Modify: `src/main.rs:4-22` (add `mod lyrics;`)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `struct LyricLine { pub time_ms: u64, pub text: String }`
  - `struct Lyrics { pub lines: Vec<LyricLine>, pub offset_ms: i64 }`
  - `Lyrics::parse(input: &str) -> Lyrics`
  - `Lyrics::is_empty(&self) -> bool`
  - `Lyrics::active_line_at(&self, position_ms: u64) -> Option<usize>`

**Offset semantics (decided, do not re-litigate):** effective time is
`time_ms - offset_ms`. A positive `[offset:]` makes lyrics appear *earlier*.

- [ ] **Step 1: Create the module declaration**

Create `src/lyrics/mod.rs`:

```rust
// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

pub mod lrc;

pub use lrc::{LyricLine, Lyrics};
```

Add `mod lyrics;` to `src/main.rs`, keeping the existing alphabetical order —
it goes between `mod i18n;` and `mod marquee;`.

- [ ] **Step 2: Write the failing tests**

Create `src/lyrics/lrc.rs` containing ONLY the test module for now:

```rust
// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_centisecond_timestamps() {
        let l = Lyrics::parse("[00:12.34]first placeholder line");
        assert_eq!(l.lines.len(), 1);
        assert_eq!(l.lines[0].time_ms, 12_340);
        assert_eq!(l.lines[0].text, "first placeholder line");
    }

    #[test]
    fn parses_millisecond_timestamps() {
        let l = Lyrics::parse("[01:02.345]second placeholder line");
        assert_eq!(l.lines[0].time_ms, 62_345);
    }

    #[test]
    fn expands_multiple_timestamps_on_one_line() {
        let l = Lyrics::parse("[00:10.00][00:50.00]repeated placeholder");
        assert_eq!(l.lines.len(), 2);
        assert_eq!(l.lines[0].time_ms, 10_000);
        assert_eq!(l.lines[1].time_ms, 50_000);
        assert_eq!(l.lines[1].text, "repeated placeholder");
    }

    #[test]
    fn skips_metadata_tags() {
        let l = Lyrics::parse("[ar:Placeholder Artist]\n[ti:Placeholder Title]\n[00:01.00]only line");
        assert_eq!(l.lines.len(), 1);
        assert_eq!(l.lines[0].text, "only line");
    }

    #[test]
    fn reads_offset_tag() {
        let l = Lyrics::parse("[offset:-500]\n[00:10.00]placeholder");
        assert_eq!(l.offset_ms, -500);
        let p = Lyrics::parse("[offset:+250]\n[00:10.00]placeholder");
        assert_eq!(p.offset_ms, 250);
    }

    #[test]
    fn sorts_out_of_order_timestamps() {
        let l = Lyrics::parse("[00:30.00]later\n[00:05.00]earlier");
        assert_eq!(l.lines[0].text, "earlier");
        assert_eq!(l.lines[1].text, "later");
    }

    #[test]
    fn keeps_blank_instrumental_entries() {
        let l = Lyrics::parse("[00:01.00]placeholder\n[00:20.00]");
        assert_eq!(l.lines.len(), 2);
        assert_eq!(l.lines[1].text, "");
    }

    #[test]
    fn skips_malformed_lines_but_keeps_valid_neighbours() {
        let l = Lyrics::parse("[00:01.00]good one\nnot a lyric line\n[garbage]\n[00:02.00]good two");
        assert_eq!(l.lines.len(), 2);
        assert_eq!(l.lines[0].text, "good one");
        assert_eq!(l.lines[1].text, "good two");
    }

    #[test]
    fn strips_enhanced_word_tags() {
        let l = Lyrics::parse("[00:01.00]<00:01.00>alpha <00:01.50>beta");
        assert_eq!(l.lines[0].text, "alpha beta");
    }

    #[test]
    fn handles_bom_and_crlf() {
        let l = Lyrics::parse("\u{feff}[00:01.00]placeholder one\r\n[00:02.00]placeholder two\r\n");
        assert_eq!(l.lines.len(), 2);
        assert_eq!(l.lines[0].text, "placeholder one");
        assert_eq!(l.lines[1].text, "placeholder two");
    }

    #[test]
    fn empty_and_whitespace_inputs_produce_no_lines() {
        assert!(Lyrics::parse("").lines.is_empty());
        assert!(Lyrics::parse("   \n\n  ").lines.is_empty());
        assert!(Lyrics::parse("").is_empty());
    }

    #[test]
    fn is_empty_when_every_line_is_blank() {
        assert!(Lyrics::parse("[00:01.00]\n[00:02.00]").is_empty());
        assert!(!Lyrics::parse("[00:01.00]placeholder").is_empty());
    }

    #[test]
    fn active_line_before_first_timestamp_is_none() {
        let l = Lyrics::parse("[00:10.00]placeholder");
        assert_eq!(l.active_line_at(0), None);
        assert_eq!(l.active_line_at(9_999), None);
    }

    #[test]
    fn active_line_at_boundaries() {
        let l = Lyrics::parse("[00:10.00]a\n[00:20.00]b\n[00:30.00]c");
        assert_eq!(l.active_line_at(10_000), Some(0));
        assert_eq!(l.active_line_at(15_000), Some(0));
        assert_eq!(l.active_line_at(20_000), Some(1));
        assert_eq!(l.active_line_at(999_000), Some(2));
    }

    #[test]
    fn active_line_applies_offset() {
        let l = Lyrics::parse("[offset:1000]\n[00:10.00]placeholder");
        assert_eq!(l.active_line_at(9_000), Some(0));
        assert_eq!(l.active_line_at(8_999), None);
    }

    #[test]
    fn active_line_on_empty_lyrics_is_none() {
        assert_eq!(Lyrics::parse("").active_line_at(1_000), None);
    }
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cargo test lyrics::lrc 2>&1 | tail -20`
Expected: FAIL — compile errors, `cannot find type Lyrics in this scope`.

- [ ] **Step 4: Write the implementation**

Insert above the `#[cfg(test)]` module in `src/lyrics/lrc.rs`:

```rust
use once_cell::sync::Lazy;
use regex::Regex;

static TIMESTAMP_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]").unwrap());
static METADATA_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\[([a-zA-Z_]+):([^\]]*)\]").unwrap());
static WORD_TAG_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>").unwrap());

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LyricLine {
    pub time_ms: u64,
    pub text: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Lyrics {
    pub lines: Vec<LyricLine>,
    pub offset_ms: i64,
}

impl Lyrics {
    /// Parses LRC text. Never fails: unrecognised lines are skipped, so any
    /// input yields a `Lyrics` (possibly with no lines).
    pub fn parse(input: &str) -> Self {
        let input = input.strip_prefix('\u{feff}').unwrap_or(input);
        let mut lines: Vec<LyricLine> = Vec::new();
        let mut offset_ms: i64 = 0;

        for raw in input.lines() {
            let mut rest = raw.trim_end_matches('\r').trim_start();
            let mut stamps: Vec<u64> = Vec::new();

            loop {
                if let Some(caps) = TIMESTAMP_RE.captures(rest) {
                    let minutes: u64 = caps[1].parse().unwrap_or(0);
                    let seconds: u64 = caps[2].parse().unwrap_or(0);
                    let fraction = caps
                        .get(3)
                        .map(|m| {
                            let digits = m.as_str();
                            let value: u64 = digits.parse().unwrap_or(0);
                            match digits.len() {
                                1 => value * 100,
                                2 => value * 10,
                                _ => value,
                            }
                        })
                        .unwrap_or(0);
                    stamps.push(minutes * 60_000 + seconds * 1_000 + fraction);
                    let end = caps.get(0).unwrap().end();
                    rest = &rest[end..];
                    continue;
                }

                // Metadata may only precede the first timestamp on a line.
                if stamps.is_empty() {
                    if let Some(caps) = METADATA_RE.captures(rest) {
                        if caps[1].eq_ignore_ascii_case("offset") {
                            if let Ok(value) = caps[2].trim().parse::<i64>() {
                                offset_ms = value;
                            }
                        }
                        let end = caps.get(0).unwrap().end();
                        rest = &rest[end..];
                        continue;
                    }
                }

                break;
            }

            if stamps.is_empty() {
                continue;
            }

            let text = WORD_TAG_RE.replace_all(rest, "").trim().to_string();
            for time_ms in stamps {
                lines.push(LyricLine {
                    time_ms,
                    text: text.clone(),
                });
            }
        }

        lines.sort_by_key(|line| line.time_ms);

        Lyrics { lines, offset_ms }
    }

    /// True when there is nothing worth showing: no lines at all, or every
    /// line is an instrumental gap.
    pub fn is_empty(&self) -> bool {
        self.lines.iter().all(|line| line.text.is_empty())
    }

    /// Index of the last line whose adjusted timestamp has been reached.
    /// `None` before the first line.
    pub fn active_line_at(&self, position_ms: u64) -> Option<usize> {
        if self.lines.is_empty() {
            return None;
        }

        let position = position_ms as i64;
        let index = self
            .lines
            .partition_point(|line| line.time_ms as i64 - self.offset_ms <= position);

        if index == 0 {
            None
        } else {
            Some(index - 1)
        }
    }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cargo test lyrics::lrc 2>&1 | tail -20`
Expected: PASS — `test result: ok. 16 passed; 0 failed`.

- [ ] **Step 6: Commit**

```bash
git add src/lyrics/mod.rs src/lyrics/lrc.rs src/main.rs
git commit -m "feat(lyrics): add LRC parser with timestamp lookup"
```

---

### Task 2: Sidecar file discovery and loading

**Files:**
- Create: `src/lyrics/loader.rs`
- Modify: `src/lyrics/mod.rs` (add `pub mod loader;`)

**Interfaces:**
- Consumes: `Lyrics::parse`, `Lyrics::is_empty` from Task 1.
- Produces:
  - `loader::sidecar_path(song_path: &Path) -> Option<PathBuf>`
  - `loader::load_from_sidecar(sidecar_path: &Path) -> Option<Lyrics>`
  - `loader::load_lyrics(song_path: &Path) -> Option<Lyrics>`

`load_from_sidecar` takes an already-resolved `.lrc` path; `load_lyrics` is the
convenience wrapper that resolves first. Task 6 uses `load_from_sidecar`,
because `Song` already caches the resolved path and re-resolving would be waste.

- [ ] **Step 1: Write the failing tests**

Create `src/lyrics/loader.rs` containing ONLY the test module for now:

```rust
// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn scratch(tag: &str) -> PathBuf {
        let mut dir = std::env::temp_dir();
        dir.push(format!("amberol-lyrics-{}-{}", std::process::id(), tag));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn finds_sidecar_with_replaced_extension() {
        let dir = scratch("replaced");
        let song = dir.join("track.mp3");
        fs::write(&song, b"").unwrap();
        fs::write(dir.join("track.lrc"), b"").unwrap();
        assert_eq!(sidecar_path(&song), Some(dir.join("track.lrc")));
    }

    #[test]
    fn finds_sidecar_with_appended_extension() {
        let dir = scratch("appended");
        let song = dir.join("track.mp3");
        fs::write(&song, b"").unwrap();
        fs::write(dir.join("track.mp3.lrc"), b"").unwrap();
        assert_eq!(sidecar_path(&song), Some(dir.join("track.mp3.lrc")));
    }

    #[test]
    fn finds_sidecar_with_uppercase_extension() {
        let dir = scratch("uppercase");
        let song = dir.join("track.mp3");
        fs::write(&song, b"").unwrap();
        fs::write(dir.join("track.LRC"), b"").unwrap();
        assert_eq!(sidecar_path(&song), Some(dir.join("track.LRC")));
    }

    #[test]
    fn returns_none_when_absent() {
        let dir = scratch("absent");
        let song = dir.join("track.mp3");
        fs::write(&song, b"").unwrap();
        assert_eq!(sidecar_path(&song), None);
    }

    #[test]
    fn loads_and_parses_lyrics() {
        let dir = scratch("load");
        let song = dir.join("track.mp3");
        fs::write(&song, b"").unwrap();
        fs::write(dir.join("track.lrc"), b"[00:05.00]placeholder line").unwrap();
        let lyrics = load_lyrics(&song).unwrap();
        assert_eq!(lyrics.lines.len(), 1);
        assert_eq!(lyrics.lines[0].time_ms, 5_000);
    }

    #[test]
    fn load_returns_none_for_blank_lyrics() {
        let dir = scratch("blank");
        let song = dir.join("track.mp3");
        fs::write(&song, b"").unwrap();
        fs::write(dir.join("track.lrc"), b"no timestamps here").unwrap();
        assert!(load_lyrics(&song).is_none());
    }

    #[test]
    fn load_returns_none_when_no_sidecar() {
        let dir = scratch("nosidecar");
        let song = dir.join("track.mp3");
        fs::write(&song, b"").unwrap();
        assert!(load_lyrics(&song).is_none());
    }

    #[test]
    fn load_from_sidecar_reads_a_resolved_path() {
        let dir = scratch("resolved");
        let sidecar = dir.join("track.lrc");
        fs::write(&sidecar, b"[00:07.00]placeholder line").unwrap();
        let lyrics = load_from_sidecar(&sidecar).unwrap();
        assert_eq!(lyrics.lines[0].time_ms, 7_000);
        assert!(load_from_sidecar(&dir.join("missing.lrc")).is_none());
    }

    #[test]
    fn tolerates_invalid_utf8() {
        let dir = scratch("badutf8");
        let song = dir.join("track.mp3");
        fs::write(&song, b"").unwrap();
        let mut bytes = b"[00:01.00]caf".to_vec();
        bytes.push(0xff);
        fs::write(dir.join("track.lrc"), bytes).unwrap();
        assert!(load_lyrics(&song).is_some());
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test lyrics::loader 2>&1 | tail -20`
Expected: FAIL — `cannot find function sidecar_path in this scope`.

- [ ] **Step 3: Write the implementation**

Insert above the `#[cfg(test)]` module in `src/lyrics/loader.rs`:

```rust
use std::{
    ffi::OsString,
    path::{Path, PathBuf},
};

use log::warn;

use super::Lyrics;

/// Resolves the sidecar `.lrc` path for a song, if one exists.
///
/// Tries `track.lrc`, then `track.mp3.lrc`, then falls back to a
/// case-insensitive scan of the containing directory.
pub fn sidecar_path(song_path: &Path) -> Option<PathBuf> {
    let replaced = song_path.with_extension("lrc");
    if replaced.is_file() {
        return Some(replaced);
    }

    let mut appended = OsString::from(song_path.as_os_str());
    appended.push(".lrc");
    let appended = PathBuf::from(appended);
    if appended.is_file() {
        return Some(appended);
    }

    let parent = song_path.parent()?;
    let stem = song_path.file_stem()?.to_str()?;
    let file_name = song_path.file_name()?.to_str()?;

    let entries = std::fs::read_dir(parent).ok()?;
    for entry in entries.flatten() {
        let candidate = entry.path();
        if !candidate.is_file() {
            continue;
        }

        let ext_is_lrc = candidate
            .extension()
            .and_then(|e| e.to_str())
            .is_some_and(|e| e.eq_ignore_ascii_case("lrc"));
        if !ext_is_lrc {
            continue;
        }

        let candidate_stem = match candidate.file_stem().and_then(|s| s.to_str()) {
            Some(s) => s,
            None => continue,
        };

        if candidate_stem.eq_ignore_ascii_case(stem)
            || candidate_stem.eq_ignore_ascii_case(file_name)
        {
            return Some(candidate);
        }
    }

    None
}

/// Reads and parses an already-resolved `.lrc` path.
///
/// Returns `None` when the file cannot be read or holds nothing worth
/// displaying. Never returns an error: absent lyrics are the normal case,
/// not a failure.
pub fn load_from_sidecar(sidecar_path: &Path) -> Option<Lyrics> {
    let bytes = match std::fs::read(sidecar_path) {
        Ok(b) => b,
        Err(e) => {
            warn!("Unable to read lyrics file {:?}: {}", sidecar_path, e);
            return None;
        }
    };

    let text = String::from_utf8_lossy(&bytes);
    let lyrics = Lyrics::parse(&text);

    if lyrics.is_empty() {
        None
    } else {
        Some(lyrics)
    }
}

/// Resolves and loads the sidecar lyrics for a song path.
pub fn load_lyrics(song_path: &Path) -> Option<Lyrics> {
    load_from_sidecar(&sidecar_path(song_path)?)
}
```

Add to `src/lyrics/mod.rs`, after the existing `pub mod lrc;`:

```rust
pub mod loader;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cargo test lyrics:: 2>&1 | tail -20`
Expected: PASS — 25 tests passed across `lrc` (16) and `loader` (9).

- [ ] **Step 5: Commit**

```bash
git add src/lyrics/loader.rs src/lyrics/mod.rs
git commit -m "feat(lyrics): add sidecar .lrc discovery and loading"
```

---

### Task 3: Millisecond-precision playback position

**Files:**
- Modify: `src/audio/gst_backend.rs:25-30`
- Modify: `src/audio/state.rs:22`, `:35`, `:45-62`, `:69-82`, `:155-174`
- Modify: `src/audio/player.rs:472-478`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `PlayerState::position_ms(&self) -> u64`
  - `PlayerState::set_position_ms(&self, position_ms: u64)`
  - A `position-ms` GObject property (`u64`, read-only) that notifies at 4 Hz.

**Critical:** `PlaybackAction::UpdatePosition` changes unit from seconds to
milliseconds. It has exactly one sender (`gst_backend.rs:27`) and one handler
(`player.rs:187`), both changed here. The public `position` property keeps its
seconds unit and gains change-detection so it does not notify four times a
second with an unchanged value.

- [ ] **Step 1: Stop truncating the GStreamer position**

In `src/audio/gst_backend.rs`, change `send_update_position`:

```rust
fn send_update_position(sender: &Sender<PlaybackAction>, clock: gst::ClockTime, notify: bool) {
    let pos = clock.mseconds();
    if let Err(e) = sender.send_blocking(PlaybackAction::UpdatePosition(pos, notify)) {
        error!("Failed to send UpdatePosition({pos}): {e}");
    }
}
```

- [ ] **Step 2: Add the `position-ms` property to PlayerState**

In `src/audio/state.rs`, add the field to `struct PlayerState`, after
`pub position: Cell<u64>,`:

```rust
        pub position_ms: Cell<u64>,
```

Add its initialiser in `fn new()`, after `position: Cell::new(0),`:

```rust
                position_ms: Cell::new(0),
```

Add the ParamSpec in `fn properties()`, after the `position` entry:

```rust
                    ParamSpecUInt64::builder("position-ms").read_only().build(),
```

Add the getter arm in `fn property()`, after the `"position"` arm:

```rust
                "position-ms" => obj.position_ms().to_value(),
```

- [ ] **Step 3: Add accessors and change-detection**

In `src/audio/state.rs`, replace the existing `set_position` and add the
millisecond pair:

```rust
    pub fn position(&self) -> u64 {
        self.imp().position.get()
    }

    /// Seconds. Only notifies when the whole-second value actually changes,
    /// so the 4 Hz millisecond tick does not spam second-granularity consumers.
    pub fn set_position(&self, position: u64) {
        let old = self.imp().position.replace(position);
        if old != position {
            self.notify("position");
        }
    }

    pub fn position_ms(&self) -> u64 {
        self.imp().position_ms.get()
    }

    pub fn set_position_ms(&self, position_ms: u64) {
        self.imp().position_ms.replace(position_ms);
        self.notify("position-ms");
    }
```

In `set_current_song`, reset the millisecond field alongside the existing
`position` reset. The body becomes:

```rust
    pub fn set_current_song(&self, song: Option<Song>) {
        self.imp().current_song.replace(song);
        self.imp().position.replace(0);
        self.imp().position_ms.replace(0);
        self.notify("song");
        self.notify("title");
        self.notify("artist");
        self.notify("album");
        self.notify("duration");
        self.notify("cover");
        self.notify("position");
        self.notify("position-ms");
    }
```

- [ ] **Step 4: Convert milliseconds to seconds in the player**

In `src/audio/player.rs`, replace `update_position`:

```rust
    fn update_position(&self, position_ms: u64, notify: bool) {
        self.state.set_position_ms(position_ms);

        let seconds = position_ms / 1000;
        let changed = self.state.position() != seconds;
        self.state.set_position(seconds);

        if changed || notify {
            for c in &self.controllers {
                c.set_position(seconds, notify);
            }
        }
    }
```

- [ ] **Step 5: Verify no other code assumed seconds**

Run: `grep -rn "UpdatePosition" src/`
Expected: exactly three hits — `gst_backend.rs:27`, `gst_backend.rs:28` (the
error message), and `player.rs:31` (the enum variant). No other senders.

- [ ] **Step 6: Verify it compiles and tests still pass**

Run: `cargo test 2>&1 | tail -15`
Expected: PASS — 25 lyrics tests plus 4 i18n tests, no warnings about unused
`position_ms`.

- [ ] **Step 7: Commit**

```bash
git add src/audio/gst_backend.rs src/audio/state.rs src/audio/player.rs
git commit -m "feat(audio): expose millisecond-precision playback position"
```

---

### Task 4: Expose lyrics availability on Song

**Files:**
- Modify: `src/audio/song.rs` — `SongData` struct, `from_uri`, `Default` impl, accessors, and the `Song` property block at `:244-300`

**Interfaces:**
- Consumes: `crate::lyrics::loader::sidecar_path` from Task 2.
- Produces:
  - `SongData::lyrics_path(&self) -> Option<&PathBuf>`
  - `Song::lyrics_path(&self) -> Option<PathBuf>`
  - `Song::has_lyrics(&self) -> bool`
  - A `has-lyrics` GObject property (`bool`, read-only) on `Song`.

- [ ] **Step 1: Add the field to SongData**

In `src/audio/song.rs`, add to `struct SongData`, after `duration: u64,`:

```rust
    lyrics_path: Option<PathBuf>,
```

- [ ] **Step 2: Check how SongData::default() is produced**

Run: `grep -n "impl Default for SongData" -A 20 src/audio/song.rs`

If `Default` is derived, no change is needed. If it is a manual `impl`, add
`lyrics_path: None,` to the returned struct literal. Apply whichever applies.

- [ ] **Step 3: Populate it in from_uri**

In `SongData::from_uri`, after the `duration` is computed and before the
`SongData { ... }` literal is constructed, resolve the sidecar:

```rust
        let lyrics_path = crate::lyrics::loader::sidecar_path(&path);
```

Add `lyrics_path,` to the `SongData { ... }` struct literal. If `from_uri` has
early-return `SongData::default()` paths, leave those alone — a file that is
not audio has no lyrics.

- [ ] **Step 4: Add the SongData accessor**

Add alongside the other `SongData` accessors:

```rust
    pub fn lyrics_path(&self) -> Option<&PathBuf> {
        self.lyrics_path.as_ref()
    }
```

- [ ] **Step 5: Add the has-lyrics property to Song**

In `impl ObjectImpl for Song`, add to the `properties()` vector, after the
`"selected"` entry:

```rust
                    ParamSpecBoolean::builder("has-lyrics").read_only().build(),
```

Add to `fn property()`, after the `"selected"` arm:

```rust
                "has-lyrics" => obj.has_lyrics().to_value(),
```

In `fn set_property()`, inside the `"uri"` arm, add a notify alongside the
existing ones:

```rust
                        obj.notify("has-lyrics");
```

- [ ] **Step 6: Add the Song accessors**

Add to `impl Song`, alongside the other accessors:

```rust
    pub fn lyrics_path(&self) -> Option<PathBuf> {
        self.imp().data.borrow().lyrics_path().cloned()
    }

    pub fn has_lyrics(&self) -> bool {
        self.imp().data.borrow().lyrics_path().is_some()
    }
```

- [ ] **Step 7: Verify it compiles**

Run: `cargo test 2>&1 | tail -15`
Expected: PASS — 29 tests (25 lyrics + 4 i18n), clean build.

- [ ] **Step 8: Commit**

```bash
git add src/audio/song.rs
git commit -m "feat(audio): expose has-lyrics and lyrics path on Song"
```

---

### Task 5: LyricsView widget

**Files:**
- Create: `src/gtk/lyrics-view.blp`
- Create: `src/lyrics_view.rs`
- Modify: `src/main.rs` (add `mod lyrics_view;`)
- Modify: `src/gtk/meson.build:5-14` (add the `.blp` to the input list)
- Modify: `src/amberol.gresource.xml` (add the generated `.ui`)
- Modify: `src/gtk/style.css` (append lyric line styles)

**Interfaces:**
- Consumes: `Lyrics` and `Lyrics::active_line_at` from Task 1.
- Produces:
  - `LyricsView::set_lyrics(&self, lyrics: Option<Lyrics>)`
  - `LyricsView::set_position_ms(&self, position_ms: u64)`

- [ ] **Step 1: Create the blueprint**

Create `src/gtk/lyrics-view.blp`:

```blueprint
// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026

using Gtk 4.0;

template $AmberolLyricsView: Gtk.Widget {
  ScrolledWindow scrolled_window {
    hscrollbar-policy: never;
    vexpand: true;
    hexpand: true;

    child: Box lines_box {
      orientation: vertical;
      spacing: 6;
      valign: start;
      halign: center;
      margin-top: 24;
      margin-bottom: 24;
      margin-start: 12;
      margin-end: 12;
    };
  }
}
```

- [ ] **Step 2: Register the blueprint in the build**

In `src/gtk/meson.build`, add `'lyrics-view.blp'` to the `input: files(...)`
list. The list is alphabetical, so it goes first. It becomes:

```meson
  input: files(
    'lyrics-view.blp',
    'playback-control.blp',
    'playlist-view.blp',
    'queue-row.blp',
    'shortcuts-dialog.blp',
    'song-cover.blp',
    'song-details.blp',
    'volume-control.blp',
    'window.blp',
  ),
```

In `src/amberol.gresource.xml`, add inside the `prefix="/io/bassi/Amberol"`
gresource block, before the `playback-control.ui` line:

```xml
    <file preprocess="xml-stripblanks">lyrics-view.ui</file>
```

- [ ] **Step 3: Write the widget**

Create `src/lyrics_view.rs`:

```rust
// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use std::cell::{Cell, RefCell};

use adw::subclass::prelude::*;
use gtk::{glib, prelude::*, CompositeTemplate};

use crate::lyrics::Lyrics;

mod imp {
    use super::*;

    #[derive(Debug, Default, CompositeTemplate)]
    #[template(resource = "/io/bassi/Amberol/lyrics-view.ui")]
    pub struct LyricsView {
        #[template_child]
        pub scrolled_window: TemplateChild<gtk::ScrolledWindow>,
        #[template_child]
        pub lines_box: TemplateChild<gtk::Box>,

        pub lyrics: RefCell<Option<Lyrics>>,
        pub labels: RefCell<Vec<gtk::Label>>,
        pub active: Cell<Option<usize>>,
    }

    #[glib::object_subclass]
    impl ObjectSubclass for LyricsView {
        const NAME: &'static str = "AmberolLyricsView";
        type Type = super::LyricsView;
        type ParentType = gtk::Widget;

        fn class_init(klass: &mut Self::Class) {
            Self::bind_template(klass);

            klass.set_layout_manager_type::<gtk::BinLayout>();
            klass.set_css_name("lyricsview");
            klass.set_accessible_role(gtk::AccessibleRole::Group);
        }

        fn instance_init(obj: &glib::subclass::InitializingObject<Self>) {
            obj.init_template();
        }
    }

    impl ObjectImpl for LyricsView {
        fn dispose(&self) {
            while let Some(child) = self.obj().first_child() {
                child.unparent();
            }
        }
    }

    impl WidgetImpl for LyricsView {}
}

glib::wrapper! {
    pub struct LyricsView(ObjectSubclass<imp::LyricsView>)
        @extends gtk::Widget,
        @implements gtk::Accessible, gtk::Buildable, gtk::ConstraintTarget;
}

impl Default for LyricsView {
    fn default() -> Self {
        glib::Object::new::<Self>()
    }
}

impl LyricsView {
    pub fn new() -> Self {
        Self::default()
    }

    /// Replaces the displayed lyrics, rebuilding the label list.
    pub fn set_lyrics(&self, lyrics: Option<Lyrics>) {
        let imp = self.imp();

        for label in imp.labels.borrow().iter() {
            imp.lines_box.remove(label);
        }
        imp.labels.borrow_mut().clear();
        imp.active.set(None);

        if let Some(lyrics) = &lyrics {
            let mut labels = imp.labels.borrow_mut();
            for line in &lyrics.lines {
                let label = gtk::Label::builder()
                    .label(&line.text)
                    .wrap(true)
                    .justify(gtk::Justification::Center)
                    .max_width_chars(36)
                    .build();
                label.add_css_class("lyric-line");
                imp.lines_box.append(&label);
                labels.push(label);
            }
        }

        imp.lyrics.replace(lyrics);
        self.scroll_to_top();
    }

    /// Updates the highlighted line for the current playback position.
    pub fn set_position_ms(&self, position_ms: u64) {
        let imp = self.imp();

        let active = match &*imp.lyrics.borrow() {
            Some(lyrics) => lyrics.active_line_at(position_ms),
            None => None,
        };

        if active == imp.active.get() {
            return;
        }

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
        }
        drop(labels);

        imp.active.set(active);

        if let Some(current) = active {
            self.scroll_to(current);
        }
    }

    fn scroll_to_top(&self) {
        let adjustment = self.imp().scrolled_window.vadjustment();
        adjustment.set_value(adjustment.lower());
    }

    fn scroll_to(&self, index: usize) {
        let imp = self.imp();
        let labels = imp.labels.borrow();

        let label = match labels.get(index) {
            Some(l) => l,
            None => return,
        };

        // Before the first allocation there is nothing to scroll to.
        if label.height() == 0 {
            return;
        }

        let box_widget = imp.lines_box.get();
        let offset = match label.translate_coordinates(&box_widget, 0.0, 0.0) {
            Some((_, y)) => y,
            None => return,
        };

        let adjustment = imp.scrolled_window.vadjustment();
        let target = offset + f64::from(label.height()) / 2.0 - adjustment.page_size() / 2.0;
        let max = (adjustment.upper() - adjustment.page_size()).max(adjustment.lower());

        adjustment.set_value(target.clamp(adjustment.lower(), max));
    }
}
```

Add `mod lyrics_view;` to `src/main.rs`, immediately after `mod lyrics;`.

- [ ] **Step 4: Add the styles**

Append to `src/gtk/style.css`:

```css
.lyric-line {
  font-size: 1.1rem;
  opacity: 0.4;
  transition-property: opacity;
  transition-duration: 200ms;
  transition-timing-function: ease;
}

.lyric-line.lyric-active {
  opacity: 1;
  font-weight: bold;
}
```

- [ ] **Step 5: Verify it builds**

Run: `ninja -C builddir 2>&1 | tail -20`
Expected: build succeeds. The blueprint compiles to `lyrics-view.ui` and the
gresource bundles it. A warning that `LyricsView` is never constructed is
expected at this point — Task 6 wires it up.

- [ ] **Step 6: Commit**

```bash
git add src/gtk/lyrics-view.blp src/lyrics_view.rs src/main.rs \
        src/gtk/meson.build src/amberol.gresource.xml src/gtk/style.css
git commit -m "feat(lyrics): add LyricsView widget"
```

---

### Task 6: Wire the lyrics view into the window

**Files:**
- Modify: `src/gtk/window.blp:89-91` (headerbar), `:103` (cover stack)
- Modify: `src/window.rs` — template children, properties, actions, song-change and position handlers

**Interfaces:**
- Consumes: `LyricsView::set_lyrics`, `LyricsView::set_position_ms` (Task 5);
  `loader::load_lyrics` (Task 2); `Song::has_lyrics` (Task 4);
  `PlayerState` `position-ms` property (Task 3).
- Produces: the working feature. Nothing depends on it.

- [ ] **Step 1: Add the stack and the toggle to the blueprint**

In `src/gtk/window.blp`, replace the `main-view` headerbar (currently
`Adw.HeaderBar { show-title: false; }` at line 89) with:

```blueprint
                Adw.HeaderBar {
                  show-title: false;

                  [end]
                  ToggleButton lyrics_button {
                    icon-name: "format-justify-left-symbolic";
                    tooltip-text: _("Show Lyrics");
                    action-name: "lyrics.toggle";

                    accessibility {
                      label: C_("a11y", "Show lyrics");
                    }
                  }
                }
```

Replace the bare `$AmberolSongCover song_cover {}` at line 103 with:

```blueprint
                  Stack cover_stack {
                    transition-type: crossfade;

                    StackPage {
                      name: "cover";

                      child: $AmberolSongCover song_cover {};
                    }

                    StackPage {
                      name: "lyrics";

                      child: $AmberolLyricsView lyrics_view {
                        height-request: 280;
                        width-request: 280;
                      };
                    }
                  }
```

- [ ] **Step 2: Register the type and template children**

In `src/window.rs`, add to the `use crate::{...}` block, in the existing
alphabetical position:

```rust
    lyrics::loader,
    lyrics_view::LyricsView,
```

Add template children to the window's `imp` struct, beside the existing
`song_cover` child:

```rust
        #[template_child]
        pub cover_stack: TemplateChild<gtk::Stack>,
        #[template_child]
        pub lyrics_view: TemplateChild<LyricsView>,
        #[template_child]
        pub lyrics_button: TemplateChild<gtk::ToggleButton>,
```

Add the corresponding `TemplateChild::default(),` initialisers to the struct
literal in `fn new()` (near the existing `song_cover` entry), matching field
order.

`fn instance_init` at `src/window.rs:232` currently contains only
`obj.init_template();`. Custom template types must be registered with the GLib
type system before the template is parsed, so change it to:

```rust
        fn instance_init(obj: &glib::subclass::InitializingObject<Self>) {
            LyricsView::static_type();
            obj.init_template();
        }
```

This mirrors what `song_cover.rs:37` does for `CoverPicture`. Skipping it
produces a runtime panic during template init, not a compile error.

- [ ] **Step 3: Add the lyrics-visible property and action**

In `imp`, add the state cell beside `playlist_visible`:

```rust
        pub lyrics_visible: Cell<bool>,
```

Initialise it in `fn new()`: `lyrics_visible: Cell::new(false),`

Add the ParamSpec beside the other window properties:

```rust
                    ParamSpecBoolean::builder("lyrics-visible").build(),
```

Add the setter arm in `set_property`:

```rust
                "lyrics-visible" => obj.set_lyrics_visible(value.get::<bool>().unwrap()),
```

Add the getter arm in `property`:

```rust
                "lyrics-visible" => self.lyrics_visible.get().to_value(),
```

In `class_init`, beside `klass.install_property_action("queue.toggle", ...)`:

```rust
            klass.install_property_action("lyrics.toggle", "lyrics-visible");
```

- [ ] **Step 4: Implement the visibility setter**

Add to `impl Window`, following the change-detection shape of
`set_playlist_visible` at `src/window.rs:433`:

```rust
    fn set_lyrics_visible(&self, visible: bool) {
        let imp = self.imp();
        if visible != imp.lyrics_visible.replace(visible) {
            if visible {
                imp.cover_stack.set_visible_child_name("lyrics");
            } else {
                imp.cover_stack.set_visible_child_name("cover");
            }
            self.notify("lyrics-visible");
        }
    }
```

- [ ] **Step 5: Load lyrics when the song changes**

The window has **no `player` field**. It reaches the player through
`fn player(&self) -> Option<Rc<AudioPlayer>>` at `src/window.rs:351`. Add this
helper to `impl Window`:

```rust
    fn update_lyrics(&self) {
        let imp = self.imp();

        let lyrics = self
            .player()
            .and_then(|player| player.state().current_song())
            .and_then(|song| song.lyrics_path())
            .and_then(|path| loader::load_from_sidecar(&path));

        let has_lyrics = lyrics.is_some();
        imp.lyrics_view.set_lyrics(lyrics);
        imp.lyrics_button.set_visible(has_lyrics);

        if !has_lyrics {
            self.set_lyrics_visible(false);
        }
    }
```

`Song::lyrics_path()` returns the already-resolved `.lrc` path, which is why
this calls `load_from_sidecar` rather than `load_lyrics` — resolving twice would
be wasted filesystem work.

Call it from the existing `Some("song")` notify handler at `src/window.rs:703`,
adding `win.update_lyrics();` to that closure's body alongside what it already
does.

- [ ] **Step 6: Feed position updates to the view**

Beside the existing `connect_notify_local(Some("position"), ...)` handler at
`src/window.rs:689`, add a second handler:

```rust
            let notify_position_ms_id = state.connect_notify_local(
                Some("position-ms"),
                clone!(
                    #[weak(rename_to = win)]
                    self,
                    move |state, _| {
                        win.imp().lyrics_view.set_position_ms(state.position_ms());
                    }
                ),
            );
            imp.notify_position_ms_id.replace(Some(notify_position_ms_id));
```

Add the matching field to `imp`:

```rust
        pub notify_position_ms_id: RefCell<Option<glib::SignalHandlerId>>,
```

Initialise it as `notify_position_ms_id: RefCell::new(None),` and disconnect it
in the same place the existing `notify_position_id` is taken and disconnected
(around `src/window.rs:760`).

Match the exact `clone!` macro syntax used by the surrounding handlers in this
file — gtk-rs 0.11 uses the attribute form shown above.

- [ ] **Step 7: Build**

Run: `ninja -C builddir 2>&1 | tail -25`
Expected: build succeeds with no errors.

- [ ] **Step 8: Verify startup without a display**

Run:
```bash
timeout 20 env WAYLAND_DISPLAY= DISPLAY= meson devenv -C builddir ./src/amberol 2>&1 | head -8
```
Expected: reaches `Setting up application (profile: development)` and then fails
only with `Failed to open display`.

**This check is weaker than it looks.** The window is constructed only after a
display connects, so this exercises resource loading and application setup but
**not** template instantiation. A misnamed `#[template_child]` will not be caught
here.

Verify template children statically instead, by checking the generated XML
contains the exact ids the Rust code binds to:

```bash
grep -oE 'id="[^"]*"' builddir/src/gtk/window.ui | sort -u | grep -E "cover_stack|lyrics"
grep -oE 'id="[^"]*"' builddir/src/gtk/lyrics-view.ui | sort -u
grep -oE 'class="AmberolLyricsView"' builddir/src/gtk/lyrics-view.ui
```

Expected: `cover_stack`, `lyrics_button`, `lyrics_view` from the first;
`lines_box`, `scrolled_window` from the second; the class name from the third.
Full template instantiation requires a display and is therefore part of the
user's visual verification.

- [ ] **Step 9: Run the full test suite**

Run: `cargo test 2>&1 | tail -15`
Expected: PASS — all 29 tests.

- [ ] **Step 10: Commit**

```bash
git add src/gtk/window.blp src/window.rs
git commit -m "feat(lyrics): show synced lyrics in the main window"
```

- [ ] **Step 11: Hand off for visual verification**

The user performs all GUI testing. Provide them with:

```fish
meson devenv -C ~/GitHub/amberol/builddir ./src/amberol
```

Ask them to confirm, with a song that has a `.lrc` beside it:
1. The lyrics button appears in the header bar only for songs with lyrics.
2. Clicking it swaps the album cover for the lyrics.
3. The active line is highlighted and tracks playback.
4. The view scrolls to keep the active line centred.
5. Songs without a `.lrc` show no button, and the window does not resize when
   switching between the two kinds of song.

---

## Notes for the implementer

- **`gtk::Label::height()`** returns the allocated height; it is 0 before the
  first allocation, which is why `scroll_to` guards on it.
- **Do not add `tempfile`** as a dev-dependency. The loader tests build their own
  scratch directories under `std::env::temp_dir()`.
- **If a template child is misnamed**, the failure appears at runtime as a panic
  during `init_template`, not at compile time. Step 8 of Task 6 exists to catch
  exactly that without opening a window.
- **Blueprint syntax**: `.blp` files use `[end]` for `Adw.HeaderBar` packing, and
  child properties are set inside the widget block. Follow `playback-control.blp`
  for reference if a construct is unclear.
