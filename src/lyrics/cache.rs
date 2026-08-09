// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use std::{
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

use gtk::glib;
use log::warn;
use sha2::{Digest, Sha256};

use super::{provider::TrackQuery, Lyrics};

/// How long a failed lookup is remembered before we try again. Definitive
/// answers (the track exists and has no lyrics) are never retried.
const TRANSIENT_MISS_TTL_SECS: u64 = 7 * 24 * 60 * 60;

pub enum CacheEntry {
    Hit(Lyrics),
    Miss { definitive: bool, stored_at: u64 },
}

impl CacheEntry {
    pub fn is_expired(&self) -> bool {
        match self {
            CacheEntry::Hit(_) => false,
            CacheEntry::Miss {
                definitive: true, ..
            } => false,
            CacheEntry::Miss { stored_at, .. } => {
                now_secs().saturating_sub(*stored_at) > TRANSIENT_MISS_TTL_SECS
            }
        }
    }
}

pub fn now_secs() -> u64 {
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

/// Stable, filename-safe cache key. Normalising means trivial tag differences
/// — case, padding, doubled spaces — resolve to the same entry.
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
            return Some(CacheEntry::Miss {
                definitive,
                stored_at,
            });
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
        CacheEntry::Miss {
            definitive,
            stored_at,
        } => {
            let tag = if *definitive {
                "definitive"
            } else {
                "transient"
            };
            std::fs::write(
                dir.join(format!("{key}.miss")),
                format!("{tag} {stored_at}"),
            )
        }
    };

    if let Err(e) = result {
        warn!("Unable to write lyrics cache entry: {e}");
    }
}

/// Reads a saved timing nudge for a track, in milliseconds.
///
/// Kept separate from the lyrics entry so it survives the lyrics being
/// re-fetched, and so it applies to sidecar files that were never cached.
pub fn load_offset(key: &str) -> Option<i64> {
    let path = cache_dir().join(format!("{key}.offset"));
    std::fs::read_to_string(path)
        .ok()
        .and_then(|t| t.trim().parse().ok())
}

pub fn store_offset(key: &str, offset_ms: i64) {
    let dir = cache_dir();
    if let Err(e) = std::fs::create_dir_all(&dir) {
        warn!("Unable to create lyrics cache directory: {e}");
        return;
    }

    let path = dir.join(format!("{key}.offset"));
    let result = if offset_ms == 0 {
        // Zero is the default; do not leave a file behind for it.
        match std::fs::remove_file(&path) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e),
            _ => Ok(()),
        }
    } else {
        std::fs::write(&path, offset_ms.to_string())
    };

    if let Err(e) = result {
        warn!("Unable to write lyrics offset: {e}");
    }
}

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
        assert_ne!(
            base,
            cache_key(&query("Other", "Title", Some("Album"), 200))
        );
        assert_ne!(
            base,
            cache_key(&query("Artist", "Other", Some("Album"), 200))
        );
        assert_ne!(
            base,
            cache_key(&query("Artist", "Title", Some("Other"), 200))
        );
        assert_ne!(
            base,
            cache_key(&query("Artist", "Title", Some("Album"), 201))
        );
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

        let stale = CacheEntry::Miss {
            definitive: false,
            stored_at: old,
        };
        assert!(stale.is_expired());

        let permanent = CacheEntry::Miss {
            definitive: true,
            stored_at: old,
        };
        assert!(!permanent.is_expired());

        let fresh = CacheEntry::Miss {
            definitive: false,
            stored_at: now_secs(),
        };
        assert!(!fresh.is_expired());
    }

    #[test]
    fn offsets_round_trip_and_clear() {
        let key = format!("offsettest{}", std::process::id());

        store_offset(&key, -750);
        assert_eq!(load_offset(&key), Some(-750));

        store_offset(&key, 500);
        assert_eq!(load_offset(&key), Some(500));

        // Zero means default, and should not leave a file behind.
        store_offset(&key, 0);
        assert_eq!(load_offset(&key), None);
    }

    #[test]
    fn missing_offset_reads_as_none() {
        assert_eq!(load_offset("no-such-key-at-all"), None);
    }

    #[test]
    fn hits_never_expire() {
        let entry = CacheEntry::Hit(crate::lyrics::Lyrics::parse("[00:01.00]placeholder"));
        assert!(!entry.is_expired());
    }
}
