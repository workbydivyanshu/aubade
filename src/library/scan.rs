// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026

use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use log::debug;

use super::track::Track;

/// Extensions lofty can read tags from. Matching on the extension keeps the
/// walk free of I/O; anything that slips through is dropped when the tag read
/// fails.
const AUDIO_EXTENSIONS: &[&str] = &[
    "mp3", "flac", "ogg", "oga", "opus", "m4a", "m4b", "mp4", "aac", "wav", "aiff", "aif", "wv",
    "ape", "mpc", "spx",
];

fn is_audio(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| {
            let e = e.to_lowercase();
            AUDIO_EXTENSIONS.contains(&e.as_str())
        })
        .unwrap_or(false)
}

fn mtime_of(meta: &fs::Metadata) -> i64 {
    meta.modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

pub fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// A candidate file found on disk, before its tags are read.
struct Candidate {
    path: PathBuf,
    mtime: i64,
}

fn walk(root: &Path, out: &mut Vec<Candidate>, depth: u32) {
    // Deep symlink loops are the only realistic way to spin here forever.
    if depth > 32 {
        return;
    }

    let entries = match fs::read_dir(root) {
        Ok(entries) => entries,
        Err(e) => {
            debug!("Cannot read {}: {}", root.display(), e);
            return;
        }
    };

    for entry in entries.flatten() {
        let path = entry.path();
        let meta = match entry.metadata() {
            Ok(meta) => meta,
            Err(_) => continue,
        };

        if meta.is_dir() {
            walk(&path, out, depth + 1);
        } else if meta.is_file() && is_audio(&path) {
            out.push(Candidate {
                path,
                mtime: mtime_of(&meta),
            });
        }
    }
}

#[derive(Debug, Default, Clone, Copy)]
pub struct ScanStats {
    pub added: usize,
    pub updated: usize,
    pub removed: usize,
    pub unchanged: usize,
}

impl ScanStats {
    pub fn is_noop(&self) -> bool {
        self.added == 0 && self.updated == 0 && self.removed == 0
    }
}

/// Rebuilds the track list for `roots`.
///
/// Tracks whose path and mtime both match an entry in `known` are carried over
/// untouched, which is what keeps play counts and a rescan of an unchanged
/// library cheap. Files that have vanished from disk are dropped.
///
/// This touches no GTK types and is meant to run off the main thread.
pub fn scan<F>(roots: &[PathBuf], known: &[Track], mut progress: F) -> (Vec<Track>, ScanStats)
where
    F: FnMut(usize, usize),
{
    let mut candidates = Vec::new();
    for root in roots {
        walk(root, &mut candidates, 0);
    }

    let previous: HashMap<&Path, &Track> =
        known.iter().map(|t| (t.path.as_path(), t)).collect();

    let total = candidates.len();
    let now = now_secs();
    let mut stats = ScanStats::default();
    let mut tracks = Vec::with_capacity(total);

    for (index, candidate) in candidates.into_iter().enumerate() {
        progress(index, total);

        match previous.get(candidate.path.as_path()) {
            Some(existing) if existing.mtime == candidate.mtime => {
                stats.unchanged += 1;
                tracks.push((*existing).clone());
            }
            existing => {
                let was_known = existing.is_some();
                // Carry listening history across an edit to the file's tags.
                let (play_count, last_played, added) = existing
                    .map(|t| (t.play_count, t.last_played, t.added))
                    .unwrap_or((0, None, now));

                if let Some(mut track) = Track::read(&candidate.path, candidate.mtime, added) {
                    track.play_count = play_count;
                    track.last_played = last_played;
                    tracks.push(track);

                    if was_known {
                        stats.updated += 1;
                    } else {
                        stats.added += 1;
                    }
                }
            }
        }
    }

    progress(total, total);

    let surviving: std::collections::HashSet<&Path> =
        tracks.iter().map(|t| t.path.as_path()).collect();
    stats.removed = known
        .iter()
        .filter(|t| !surviving.contains(t.path.as_path()))
        .count();

    (tracks, stats)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_audio_extensions_are_candidates() {
        assert!(is_audio(Path::new("/m/a.FLAC")));
        assert!(is_audio(Path::new("/m/a.mp3")));
        assert!(!is_audio(Path::new("/m/cover.jpg")));
        assert!(!is_audio(Path::new("/m/notes.txt")));
        assert!(!is_audio(Path::new("/m/no-extension")));
    }

    #[test]
    fn a_scan_of_nothing_is_a_noop() {
        let (tracks, stats) = scan(&[], &[], |_, _| {});
        assert!(tracks.is_empty());
        assert!(stats.is_noop());
    }

    #[test]
    fn missing_files_are_counted_as_removed() {
        let known = vec![Track {
            path: PathBuf::from("/gone/song.flac"),
            mtime: 1,
            title: String::from("Song"),
            artist: String::from("A"),
            album_artist: String::from("A"),
            album: String::from("B"),
            track_no: 1,
            disc_no: 1,
            year: 2020,
            genre: None,
            duration: 1000,
            play_count: 7,
            last_played: None,
            added: 0,
        }];

        let (tracks, stats) = scan(&[], &known, |_, _| {});
        assert!(tracks.is_empty());
        assert_eq!(stats.removed, 1);
    }
}
