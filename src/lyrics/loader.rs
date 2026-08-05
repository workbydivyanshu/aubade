// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

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

#[cfg(test)]
mod tests {
    use std::fs;

    use super::*;

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
