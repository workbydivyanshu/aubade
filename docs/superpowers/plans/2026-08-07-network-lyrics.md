# Network Lyrics Fetching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch time-synced lyrics from LRCLIB when no sidecar `.lrc` exists, cache the result on disk, and display it through the existing lyrics view without blocking the UI.

**Architecture:** A `LyricsProvider` trait with a three-way result, an LRCLIB implementation split into pure decoding (unit-tested against fixtures) and HTTP transport (libsoup3 on the GLib main context), and a disk cache that records both hits and misses.

**Tech Stack:** Rust 2018, GTK4 (gtk4-rs 0.11), libadwaita 0.9, libsoup3 (`soup3` 0.9), serde_json, sha2 — the last two already dependencies.

## Global Constraints

- **Resolution order:** sidecar `.lrc` → disk cache → LRCLIB → nothing. First hit wins.
- **Never write to the user's music folders.** Fetched lyrics go to `~/.cache/aubade/lyrics/` only.
- **No blocking the main thread.** All HTTP is async on the GLib main context.
- **GSettings key:** `fetch-lyrics-online`, boolean, default `true`. When false, zero network activity.
- **User-Agent:** `Aubade/<version> (https://github.com/workbydivyanshu/aubade)`
- **Timeout:** 10 seconds per request.
- **Test fixtures contain invented placeholder text, never real lyrics.**
- Work on branch `lyrics-online`, already created off `main`.
- Run all commands from `/home/divyu/GitHub/amberol`.
- The app cannot be rebuilt while running; kill it first. Run it via
  `meson devenv -C builddir ./src/debug/aubade`, and copy
  `builddir/src/aubade.gresource` next to the debug binary first.

---

### Task 1: Provider types and disk cache

**Files:**
- Create: `src/lyrics/provider.rs`
- Create: `src/lyrics/cache.rs`
- Modify: `src/lyrics/mod.rs`

**Interfaces:**
- Consumes: `Lyrics` from `src/lyrics/lrc.rs`.
- Produces:
  - `TrackQuery { artist: String, title: String, album: Option<String>, duration_secs: u64 }`
  - `enum ProviderResult { Found(Lyrics), NoneExist, Failed }`
  - `cache::cache_key(&TrackQuery) -> String`
  - `cache::load(&str) -> Option<CacheEntry>`
  - `cache::store(&str, &CacheEntry)`
  - `enum CacheEntry { Hit(Lyrics), Miss { definitive: bool, stored_at: u64 } }`

- [ ] **Step 1: Write the failing tests**

Create `src/lyrics/cache.rs` with only this test module:

```rust
// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lyrics::provider::TrackQuery;

    fn query(artist: &str, title: &str, album: Option<&str>, dur: u64) -> TrackQuery {
        TrackQuery {
            artist: artist.to_string(),
            title: title.to_string(),
            album: album.map(|s| s.to_string()),
            duration_secs: dur,
        }
    }

    #[test]
    fn key_is_stable_for_identical_input() {
        let a = cache_key(&query("Artist", "Title", Some("Album"), 200));
        let b = cache_key(&query("Artist", "Title", Some("Album"), 200));
        assert_eq!(a, b);
    }

    #[test]
    fn key_ignores_case_and_surrounding_whitespace() {
        let a = cache_key(&query("Artist", "Title", Some("Album"), 200));
        let b = cache_key(&query("  ARTIST ", "title  ", Some("AlBuM"), 200));
        assert_eq!(a, b);
    }

    #[test]
    fn key_collapses_internal_whitespace() {
        let a = cache_key(&query("The  Band", "My   Song", None, 100));
        let b = cache_key(&query("The Band", "My Song", None, 100));
        assert_eq!(a, b);
    }

    #[test]
    fn key_differs_on_meaningful_change() {
        let base = cache_key(&query("Artist", "Title", Some("Album"), 200));
        assert_ne!(base, cache_key(&query("Other", "Title", Some("Album"), 200)));
        assert_ne!(base, cache_key(&query("Artist", "Other", Some("Album"), 200)));
        assert_ne!(base, cache_key(&query("Artist", "Title", Some("Other"), 200)));
        assert_ne!(base, cache_key(&query("Artist", "Title", Some("Album"), 201)));
    }

    #[test]
    fn key_is_filename_safe() {
        let k = cache_key(&query("A/B\\C", "D:E*F", None, 1));
        assert!(k.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn transient_miss_expires_definitive_miss_does_not() {
        let week = 7 * 24 * 60 * 60;
        let old = now_secs() - (week + 60);

        let stale = CacheEntry::Miss { definitive: false, stored_at: old };
        assert!(stale.is_expired());

        let permanent = CacheEntry::Miss { definitive: true, stored_at: old };
        assert!(!permanent.is_expired());

        let fresh = CacheEntry::Miss { definitive: false, stored_at: now_secs() };
        assert!(!fresh.is_expired());
    }

    #[test]
    fn hits_never_expire() {
        let entry = CacheEntry::Hit(crate::lyrics::Lyrics::parse("[00:01.00]placeholder"));
        assert!(!entry.is_expired());
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test lyrics::cache 2>&1 | tail -10`
Expected: FAIL — `cannot find function cache_key in this scope`.

- [ ] **Step 3: Create the provider types**

Create `src/lyrics/provider.rs`:

```rust
// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use super::Lyrics;

/// What we know about the playing track, used to look lyrics up.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TrackQuery {
    pub artist: String,
    pub title: String,
    pub album: Option<String>,
    pub duration_secs: u64,
}

/// The outcome of a lookup.
///
/// `NoneExist` and `Failed` are deliberately distinct: the first is a definitive
/// answer worth caching forever, the second is worth retrying later. Collapsing
/// them into `Option` would either re-query instrumentals endlessly or
/// permanently blacklist tracks that failed while offline.
#[derive(Debug)]
pub enum ProviderResult {
    Found(Lyrics),
    NoneExist,
    Failed,
}
```

- [ ] **Step 4: Implement the cache**

Insert above the test module in `src/lyrics/cache.rs`:

```rust
use std::{
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

use log::warn;
use sha2::{Digest, Sha256};

use super::{provider::TrackQuery, Lyrics};

const TRANSIENT_MISS_TTL_SECS: u64 = 7 * 24 * 60 * 60;

pub enum CacheEntry {
    Hit(Lyrics),
    Miss { definitive: bool, stored_at: u64 },
}

impl CacheEntry {
    pub fn is_expired(&self) -> bool {
        match self {
            CacheEntry::Hit(_) => false,
            CacheEntry::Miss { definitive: true, .. } => false,
            CacheEntry::Miss { stored_at, .. } => {
                now_secs().saturating_sub(*stored_at) > TRANSIENT_MISS_TTL_SECS
            }
        }
    }
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn normalise(s: &str) -> String {
    s.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

/// Stable, filename-safe key. Normalisation means trivial tag differences
/// (case, padding, doubled spaces) resolve to the same cache entry.
pub fn cache_key(query: &TrackQuery) -> String {
    let mut hasher = Sha256::new();
    hasher.update(normalise(&query.artist));
    hasher.update("|");
    hasher.update(normalise(&query.title));
    hasher.update("|");
    hasher.update(normalise(query.album.as_deref().unwrap_or("")));
    hasher.update("|");
    hasher.update(query.duration_secs.to_string());
    format!("{:x}", hasher.finalize())
}

fn cache_dir() -> PathBuf {
    let mut dir = glib::user_cache_dir();
    dir.push("aubade");
    dir.push("lyrics");
    dir
}

pub fn load(key: &str) -> Option<CacheEntry> {
    let dir = cache_dir();

    let hit = dir.join(format!("{key}.lrc"));
    if hit.is_file() {
        if let Ok(bytes) = std::fs::read(&hit) {
            let lyrics = Lyrics::parse(&String::from_utf8_lossy(&bytes));
            if !lyrics.is_empty() {
                return Some(CacheEntry::Hit(lyrics));
            }
        }
    }

    let miss = dir.join(format!("{key}.miss"));
    if miss.is_file() {
        if let Ok(text) = std::fs::read_to_string(&miss) {
            let mut parts = text.trim().splitn(2, ' ');
            let definitive = parts.next() == Some("definitive");
            let stored_at = parts.next().and_then(|s| s.parse().ok()).unwrap_or(0);
            return Some(CacheEntry::Miss { definitive, stored_at });
        }
    }

    None
}

pub fn store(key: &str, entry: &CacheEntry) {
    let dir = cache_dir();
    if let Err(e) = std::fs::create_dir_all(&dir) {
        warn!("Unable to create lyrics cache directory: {e}");
        return;
    }

    let result = match entry {
        CacheEntry::Hit(lyrics) => {
            let mut out = String::new();
            for line in &lyrics.lines {
                let cs = line.time_ms / 10 % 100;
                let secs = line.time_ms / 1000 % 60;
                let mins = line.time_ms / 60_000;
                out.push_str(&format!("[{mins:02}:{secs:02}.{cs:02}]{}\n", line.text));
            }
            std::fs::write(dir.join(format!("{key}.lrc")), out)
        }
        CacheEntry::Miss { definitive, stored_at } => {
            let tag = if *definitive { "definitive" } else { "transient" };
            std::fs::write(dir.join(format!("{key}.miss")), format!("{tag} {stored_at}"))
        }
    };

    if let Err(e) = result {
        warn!("Unable to write lyrics cache entry: {e}");
    }
}
```

Add to `src/lyrics/mod.rs`, keeping alphabetical order:

```rust
pub mod cache;
pub mod provider;
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cargo test lyrics:: 2>&1 | tail -6`
Expected: PASS — 32 tests (25 existing + 7 new).

- [ ] **Step 6: Commit**

```bash
cargo fmt
git add src/lyrics/
git commit -m "feat(lyrics): add provider types and disk cache"
```

---

### Task 2: LRCLIB response decoding

**Files:**
- Create: `src/lyrics/lrclib.rs`
- Create: `tests/fixtures/lrclib_hit.json`, `lrclib_instrumental.json`, `lrclib_search.json`, `lrclib_malformed.json`
- Modify: `src/lyrics/mod.rs`

**Interfaces:**
- Consumes: `TrackQuery`, `ProviderResult` from Task 1.
- Produces:
  - `lrclib::decode_get(body: &str) -> ProviderResult`
  - `lrclib::decode_search(body: &str, duration_secs: u64) -> ProviderResult`
  - `lrclib::get_url(&TrackQuery) -> String`
  - `lrclib::search_url(&TrackQuery) -> String`

Decoding is separated from HTTP so it can be tested offline against fixtures.

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/lrclib_hit.json` — note the placeholder lyric text:

```json
{
  "id": 496,
  "trackName": "Placeholder Song",
  "artistName": "Placeholder Artist",
  "albumName": "Placeholder Album",
  "duration": 239.0,
  "instrumental": false,
  "plainLyrics": "placeholder line one\nplaceholder line two",
  "syncedLyrics": "[00:12.34]placeholder line one\n[00:20.00]placeholder line two"
}
```

`tests/fixtures/lrclib_instrumental.json`:

```json
{
  "id": 497,
  "trackName": "Placeholder Instrumental",
  "artistName": "Placeholder Artist",
  "albumName": "Placeholder Album",
  "duration": 180.0,
  "instrumental": true,
  "plainLyrics": null,
  "syncedLyrics": null
}
```

`tests/fixtures/lrclib_search.json`:

```json
[
  {
    "id": 1,
    "trackName": "Placeholder Song",
    "artistName": "Placeholder Artist",
    "albumName": "Wrong Album",
    "duration": 300.0,
    "instrumental": false,
    "syncedLyrics": "[00:05.00]wrong duration candidate"
  },
  {
    "id": 2,
    "trackName": "Placeholder Song",
    "artistName": "Placeholder Artist",
    "albumName": "Right Album",
    "duration": 201.0,
    "instrumental": false,
    "syncedLyrics": "[00:09.00]correct candidate"
  }
]
```

`tests/fixtures/lrclib_malformed.json`:

```json
{"id": 1, "trackName":
```

- [ ] **Step 2: Write the failing tests**

Create `src/lyrics/lrclib.rs` with only this test module:

```rust
// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lyrics::provider::{ProviderResult, TrackQuery};

    fn fixture(name: &str) -> String {
        std::fs::read_to_string(format!(
            "{}/tests/fixtures/{name}",
            env!("CARGO_MANIFEST_DIR")
        ))
        .unwrap()
    }

    fn query() -> TrackQuery {
        TrackQuery {
            artist: "Placeholder Artist".into(),
            title: "Placeholder Song".into(),
            album: Some("Placeholder Album".into()),
            duration_secs: 200,
        }
    }

    #[test]
    fn decodes_a_synced_hit() {
        match decode_get(&fixture("lrclib_hit.json")) {
            ProviderResult::Found(l) => {
                assert_eq!(l.lines.len(), 2);
                assert_eq!(l.lines[0].time_ms, 12_340);
            }
            other => panic!("expected Found, got {other:?}"),
        }
    }

    #[test]
    fn instrumental_is_definitively_none() {
        assert!(matches!(
            decode_get(&fixture("lrclib_instrumental.json")),
            ProviderResult::NoneExist
        ));
    }

    #[test]
    fn malformed_json_is_a_failure_not_a_panic() {
        assert!(matches!(
            decode_get(&fixture("lrclib_malformed.json")),
            ProviderResult::Failed
        ));
    }

    #[test]
    fn empty_body_is_a_failure() {
        assert!(matches!(decode_get(""), ProviderResult::Failed));
    }

    #[test]
    fn search_picks_the_candidate_matching_duration() {
        match decode_search(&fixture("lrclib_search.json"), 200) {
            ProviderResult::Found(l) => assert_eq!(l.lines[0].time_ms, 9_000),
            other => panic!("expected Found, got {other:?}"),
        }
    }

    #[test]
    fn search_rejects_when_no_candidate_matches_duration() {
        assert!(matches!(
            decode_search(&fixture("lrclib_search.json"), 30),
            ProviderResult::Failed
        ));
    }

    #[test]
    fn search_of_empty_array_is_a_failure() {
        assert!(matches!(decode_search("[]", 200), ProviderResult::Failed));
    }

    #[test]
    fn urls_are_percent_encoded() {
        let mut q = query();
        q.artist = "A & B".into();
        let url = get_url(&q);
        assert!(url.starts_with("https://lrclib.net/api/get?"));
        assert!(!url.contains("A & B"));
        assert!(url.contains("duration=200"));
    }
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cargo test lyrics::lrclib 2>&1 | tail -8`
Expected: FAIL — `cannot find function decode_get in this scope`.

- [ ] **Step 4: Implement decoding and URL construction**

Insert above the test module in `src/lyrics/lrclib.rs`:

```rust
use glib::Uri;
use log::warn;
use serde_json::Value;

use super::{
    provider::{ProviderResult, TrackQuery},
    Lyrics,
};

/// Accept a search candidate only if its duration is within this many seconds
/// of the local file, so a same-title different-song match is rejected.
const DURATION_TOLERANCE_SECS: i64 = 3;

fn encode(s: &str) -> String {
    Uri::escape_string(s, None, false).to_string()
}

pub fn get_url(query: &TrackQuery) -> String {
    let mut url = format!(
        "https://lrclib.net/api/get?artist_name={}&track_name={}&duration={}",
        encode(&query.artist),
        encode(&query.title),
        query.duration_secs,
    );
    if let Some(album) = &query.album {
        url.push_str(&format!("&album_name={}", encode(album)));
    }
    url
}

pub fn search_url(query: &TrackQuery) -> String {
    format!(
        "https://lrclib.net/api/search?artist_name={}&track_name={}",
        encode(&query.artist),
        encode(&query.title),
    )
}

fn entry_to_result(value: &Value) -> ProviderResult {
    if value.get("instrumental").and_then(Value::as_bool) == Some(true) {
        return ProviderResult::NoneExist;
    }

    match value.get("syncedLyrics").and_then(Value::as_str) {
        Some(text) if !text.trim().is_empty() => {
            let lyrics = Lyrics::parse(text);
            if lyrics.is_empty() {
                ProviderResult::NoneExist
            } else {
                ProviderResult::Found(lyrics)
            }
        }
        // Present but empty means the track is known and has no synced lyrics.
        _ => ProviderResult::NoneExist,
    }
}

pub fn decode_get(body: &str) -> ProviderResult {
    match serde_json::from_str::<Value>(body) {
        Ok(value) => entry_to_result(&value),
        Err(e) => {
            warn!("Unable to decode LRCLIB response: {e}");
            ProviderResult::Failed
        }
    }
}

pub fn decode_search(body: &str, duration_secs: u64) -> ProviderResult {
    let candidates = match serde_json::from_str::<Value>(body) {
        Ok(Value::Array(a)) => a,
        Ok(_) => return ProviderResult::Failed,
        Err(e) => {
            warn!("Unable to decode LRCLIB search response: {e}");
            return ProviderResult::Failed;
        }
    };

    for candidate in &candidates {
        let candidate_secs = match candidate.get("duration").and_then(Value::as_f64) {
            Some(d) => d as i64,
            None => continue,
        };
        if (candidate_secs - duration_secs as i64).abs() > DURATION_TOLERANCE_SECS {
            continue;
        }
        if let ProviderResult::Found(l) = entry_to_result(candidate) {
            return ProviderResult::Found(l);
        }
    }

    ProviderResult::Failed
}
```

Add `pub mod lrclib;` to `src/lyrics/mod.rs`.

`ProviderResult` needs `Debug` for the test panics — it already derives it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cargo test lyrics:: 2>&1 | tail -6`
Expected: PASS — 40 tests (32 + 8 new).

- [ ] **Step 6: Commit**

```bash
cargo fmt
git add src/lyrics/ tests/fixtures/
git commit -m "feat(lyrics): decode LRCLIB responses against offline fixtures"
```

---

### Task 3: HTTP transport via libsoup3

**Files:**
- Modify: `Cargo.toml`, `meson.build`
- Modify: `src/lyrics/lrclib.rs`

**Interfaces:**
- Consumes: `get_url`, `search_url`, `decode_get`, `decode_search` from Task 2.
- Produces: `lrclib::fetch(query: &TrackQuery) -> ProviderResult` (async).

- [ ] **Step 1: Add the dependency**

In `Cargo.toml`, under `[dependencies]`:

```toml
soup3 = "0.9"
```

`soup3` 0.9 requires glib ^0.22 and gio ^0.22; the project already resolves
glib 0.22.8 via gtk4 0.11.4, so no version pinning is needed.

In `meson.build`, beside the other `dependency()` calls:

```meson
dependency('libsoup-3.0', version: '>= 3.0')
```

- [ ] **Step 2: Verify it resolves before writing code against it**

```bash
cargo build 2>&1 | grep -E "^error|Compiling soup3|Finished" | head -5
```
Expected: `Compiling soup3 v0.9.x` then `Finished`. If cargo reports a version
conflict on glib, stop — do not pin versions blindly; report the conflict.

- [ ] **Step 3: Implement the async fetch**

Append to `src/lyrics/lrclib.rs`, above the test module:

```rust
use soup::prelude::*;

const TIMEOUT_SECS: u32 = 10;

fn user_agent() -> String {
    format!(
        "Aubade/{} (https://github.com/workbydivyanshu/aubade)",
        crate::config::VERSION
    )
}

async fn get_body(session: &soup::Session, url: &str) -> Option<String> {
    let message = soup::Message::new("GET", url)?;

    let bytes = match session
        .send_and_read_future(&message, glib::Priority::DEFAULT)
        .await
    {
        Ok(b) => b,
        Err(e) => {
            warn!("LRCLIB request failed: {e}");
            return None;
        }
    };

    let status = message.status();
    if status != soup::Status::Ok {
        // 404 is the normal "no match" answer, not an error worth shouting about.
        if status != soup::Status::NotFound {
            warn!("LRCLIB returned status {status:?}");
        }
        return None;
    }

    Some(String::from_utf8_lossy(&bytes).to_string())
}

/// Looks a track up on LRCLIB, falling back to search when the exact
/// lookup misses.
pub async fn fetch(query: &TrackQuery) -> ProviderResult {
    let session = soup::Session::new();
    session.set_timeout(TIMEOUT_SECS);
    session.set_user_agent(Some(&user_agent()));

    if let Some(body) = get_body(&session, &get_url(query)).await {
        match decode_get(&body) {
            ProviderResult::Found(l) => return ProviderResult::Found(l),
            ProviderResult::NoneExist => return ProviderResult::NoneExist,
            ProviderResult::Failed => {}
        }
    }

    match get_body(&session, &search_url(query)).await {
        Some(body) => decode_search(&body, query.duration_secs),
        None => ProviderResult::Failed,
    }
}
```

The crate is `soup3`, so the code above needs this alias at the top of the file:

```rust
use soup3 as soup;
```

Alias rather than writing `soup3::` throughout, so the code reads the way the
libsoup documentation does.

- [ ] **Step 4: Verify it builds and existing tests still pass**

```bash
cargo test 2>&1 | grep -E "test result|^error|^warning" | head -6
```
Expected: PASS — 40 tests, no warnings. `fetch` is not unit-tested; it is
verified live in Task 6.

- [ ] **Step 5: Commit**

```bash
cargo fmt
git add Cargo.toml Cargo.lock meson.build src/lyrics/lrclib.rs
git commit -m "feat(lyrics): fetch from LRCLIB over libsoup3"
```

---

### Task 4: The online-fetching setting

**Files:**
- Modify: `data/io.github.workbydivyanshu.Aubade.gschema.xml`
- Modify: `src/gtk/window.blp` (menu entry)
- Modify: `src/window.rs`

**Interfaces:**
- Produces: a `fetch-lyrics-online` boolean setting, readable from `Window`.

- [ ] **Step 1: Add the schema key**

In the gschema, inside `<schema>`, alongside the existing keys:

```xml
<key name="fetch-lyrics-online" type="b">
  <default>true</default>
  <summary>Fetch lyrics online</summary>
  <description>
    Look up time-synced lyrics from LRCLIB when a song has no local lyrics
    file. When disabled, Aubade makes no network requests.
  </description>
</key>
```

- [ ] **Step 2: Rebuild so the schema is recompiled**

```bash
ninja -C builddir 2>&1 | grep -E "^error|Finished" | head -3
```
Expected: `Finished`. A malformed schema fails the build here rather than at
runtime.

- [ ] **Step 3: Add the menu toggle**

The primary menu is `menu primary_menu` in **`src/gtk/playback-control.blp`**
(line 149), not `window.blp`. The toggles section around line 179 already holds
`win.enable-recoloring` and `app.background-play`. Add a third item to that same
section, after `_Background Playback`:

```blueprint
    item {
      label: _("_Fetch Lyrics Online");
      action: "win.fetch-lyrics-online";
    }
```

The `win.` prefix is correct here: the setting is bound on the window, matching
`win.enable-recoloring`. `app.background-play` uses `app.` because it lives on
the application.

- [ ] **Step 4: Wire the action to the setting**

In `src/window.rs`, in the same place other settings are bound, add to
`impl Window`:

```rust
    fn setup_lyrics_setting(&self) {
        let action = self.imp().settings.create_action("fetch-lyrics-online");
        self.add_action(&action);
    }

    pub fn fetch_lyrics_online(&self) -> bool {
        self.imp().settings.boolean("fetch-lyrics-online")
    }
```

Call `self.setup_lyrics_setting();` from `constructed()` in the window's
`ObjectImpl`, after `parent_constructed()`.

`gio::Settings::create_action` produces a stateful action already bound to the
key in both directions, so no manual synchronisation is needed.

- [ ] **Step 5: Verify the setting round-trips**

```bash
ninja -C builddir 2>&1 | grep -E "^error|Finished" | head -3
GSETTINGS_SCHEMA_DIR=builddir/data gsettings get io.github.workbydivyanshu.Aubade fetch-lyrics-online
```
Expected: `Finished`, then `true`.

- [ ] **Step 6: Commit**

```bash
git add data/ src/
git commit -m "feat(lyrics): add the fetch-lyrics-online setting"
```

---

### Task 5: Window integration with a stale-response guard

**Files:**
- Modify: `src/window.rs` — `update_lyrics`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: the working feature.

**The critical detail:** playback can move on while a request is in flight.
Applying a late response would show the previous song's lyrics. Every request is
tagged with the song's URI and the result discarded if it no longer matches.

- [ ] **Step 1: Rewrite `update_lyrics`**

Replace the existing `update_lyrics` in `src/window.rs`:

```rust
    /// Resolves lyrics for the current song: sidecar, then cache, then network.
    fn update_lyrics(&self) {
        let imp = self.imp();

        let song = match self.player().and_then(|p| p.state().current_song()) {
            Some(s) => s,
            None => {
                imp.lyrics_view.set_lyrics(None);
                imp.lyrics_button.set_visible(false);
                self.set_lyrics_visible(false);
                return;
            }
        };

        // 1. A sidecar file beside the audio always wins.
        if let Some(lyrics) = song.lyrics_path().and_then(|p| loader::load_from_sidecar(&p)) {
            self.apply_lyrics(Some(lyrics));
            return;
        }

        let query = TrackQuery {
            artist: song.artist(),
            title: song.title(),
            album: Some(song.album()),
            duration_secs: song.duration(),
        };

        // 2. The cache, including remembered misses.
        let key = cache::cache_key(&query);
        if let Some(entry) = cache::load(&key) {
            if !entry.is_expired() {
                match entry {
                    cache::CacheEntry::Hit(l) => self.apply_lyrics(Some(l)),
                    cache::CacheEntry::Miss { .. } => self.apply_lyrics(None),
                }
                return;
            }
        }

        // Nothing local: hide the toggle until a network result arrives.
        self.apply_lyrics(None);

        if !self.fetch_lyrics_online() {
            return;
        }
        if query.artist.is_empty() || query.title.is_empty() {
            debug!("Skipping lyrics lookup: incomplete metadata");
            return;
        }

        // 3. The network, asynchronously.
        let uri = song.uri();
        glib::MainContext::default().spawn_local(clone!(
            #[weak(rename_to = win)]
            self,
            async move {
                let result = crate::lyrics::lrclib::fetch(&query).await;

                // The song may have changed while this was in flight.
                let still_current = win
                    .player()
                    .and_then(|p| p.state().current_song())
                    .map(|s| s.uri() == uri)
                    .unwrap_or(false);
                if !still_current {
                    debug!("Discarding lyrics for a song that is no longer playing");
                    return;
                }

                let entry = match result {
                    ProviderResult::Found(l) => {
                        win.apply_lyrics(Some(l.clone()));
                        cache::CacheEntry::Hit(l)
                    }
                    ProviderResult::NoneExist => cache::CacheEntry::Miss {
                        definitive: true,
                        stored_at: cache::now_secs(),
                    },
                    ProviderResult::Failed => cache::CacheEntry::Miss {
                        definitive: false,
                        stored_at: cache::now_secs(),
                    },
                };
                cache::store(&key, &entry);
            }
        ));
    }

    /// Shows lyrics, or hides the toggle entirely when there are none.
    fn apply_lyrics(&self, lyrics: Option<Lyrics>) {
        let imp = self.imp();
        let has_lyrics = lyrics.is_some();

        imp.lyrics_view.set_lyrics(lyrics);
        imp.lyrics_button.set_visible(has_lyrics);

        if !has_lyrics {
            self.set_lyrics_visible(false);
        }
    }
```

- [ ] **Step 2: Add the imports**

To the `use crate::{...}` block in `src/window.rs`:

```rust
    lyrics::{
        cache,
        loader,
        provider::{ProviderResult, TrackQuery},
        Lyrics,
    },
```

Remove the now-duplicated `lyrics::loader` entry if present.

- [ ] **Step 3: Make `now_secs` public**

`cache::now_secs` is used by `window.rs`. In `src/lyrics/cache.rs`, change
`fn now_secs()` to `pub fn now_secs()`.

- [ ] **Step 4: Build and test**

```bash
cargo test 2>&1 | grep -E "test result|^error|^warning" | head -8
ninja -C builddir 2>&1 | grep -E "^error|warning|Finished" | head -5
```
Expected: 40 tests pass; build finishes with no warnings.

- [ ] **Step 5: Commit**

```bash
cargo fmt
git add src/
git commit -m "feat(lyrics): fetch online when no local lyrics exist"
```

---

### Task 6: End-to-end verification

**Files:** none.

- [ ] **Step 1: Pick a track with no sidecar**

```bash
find ~/Music -maxdepth 2 -name "*.opus" -o -maxdepth 2 -name "*.mp3" | while read -r f; do
  [ -f "${f%.*}.lrc" ] || { echo "$f"; break; }
done
```
Note the path. It must have real artist and title tags, so a voice memo is a
poor choice — prefer a track from a music folder.

- [ ] **Step 2: Clear any cached entry so the network path actually runs**

```bash
rm -rf ~/.cache/aubade/lyrics
```

- [ ] **Step 3: Launch with that track**

```bash
pkill -f "src/debug/aubade"
cp builddir/src/aubade.gresource builddir/src/debug/
XDG_RUNTIME_DIR=/run/user/1001 WAYLAND_DISPLAY=wayland-1 GDK_BACKEND=wayland \
  meson devenv -C builddir ./src/debug/aubade "<path from step 1>" &
```

- [ ] **Step 4: Capture and read the window**

```bash
export XDG_RUNTIME_DIR=/run/user/1001
export HYPRLAND_INSTANCE_SIGNATURE=5c9377c15f85c50648f35ca5a213754f95b93ca0_1785760842_966495143
for i in $(seq 1 20); do hyprctl clients -j | grep -qi aubade && break; sleep 1; done
G=$(hyprctl clients -j | python3 -c "import json,sys; c=[x for x in json.load(sys.stdin) if 'Aubade' in x['class']][0]; print(f\"{c['at'][0]},{c['at'][1]} {c['size'][0]}x{c['size'][1]}\")")
WAYLAND_DISPLAY=wayland-1 grim -g "$G" /tmp/aubade-online.png
```

**Confirm the captured window is actually Aubade before interpreting it** — a
stale geometry lookup can capture an unrelated window. Re-query the class
immediately before capturing.

Required: the lyrics toggle appears within a few seconds of the song loading,
and toggling it shows synced lyrics that track playback.

- [ ] **Step 5: Verify the cache was written**

```bash
ls ~/.cache/aubade/lyrics/
```
Expected: one `.lrc` or `.miss` file.

- [ ] **Step 6: Verify the setting genuinely disables the network**

```bash
pkill -f "src/debug/aubade"
rm -rf ~/.cache/aubade/lyrics
GSETTINGS_SCHEMA_DIR=builddir/data gsettings set io.github.workbydivyanshu.Aubade fetch-lyrics-online false
```
Relaunch as in Step 3 and confirm no lyrics appear and no cache files are
written. Then set it back to `true`.

This is the check that proves the privacy switch does what it claims.

- [ ] **Step 7: Update the changelog and commit**

Add to `CHANGES.md` under `### Added`:

```markdown
- Online lyrics lookup via LRCLIB for songs with no local `.lrc` file, with a
  disk cache and a setting to disable all network access.
```

```bash
git add CHANGES.md
git commit -m "docs: note online lyrics lookup in the changelog"
```

---

## Notes for the implementer

- **`soup::Session::send_and_read_future` returns `glib::Bytes`.** It resolves on
  the GLib main context, so no runtime and no thread marshalling is needed.
- **404 is the expected answer for an unknown track**, not an error. Do not log
  it at `warn` or the log fills up with normal misses.
- **Do not unit-test `fetch`.** A test that hits the live network is slow,
  flaky, and breaks when LRCLIB's data changes. Decoding is tested against
  fixtures; the transport is verified once by hand.
- **Fixtures must never contain real lyric text.** Use invented placeholder
  lines, as the committed fixtures do.
