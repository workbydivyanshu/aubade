// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026

use std::path::{Path, PathBuf};

use gtk::prelude::FileExt;
use itertools::Itertools;
use lofty::{
    config::ParseOptions,
    file::AudioFile,
    prelude::{Accessor, TaggedFileExt},
    probe::Probe,
    tag::{ItemKey, Tag},
};
use serde::{Deserialize, Serialize};

/// One audio file, as the library remembers it.
///
/// Artwork is deliberately absent: it is decoded from the file on demand by
/// [`crate::audio::Song`]. Keeping it out of here is what lets the index stay
/// small enough to load in one go.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Track {
    pub path: PathBuf,
    /// Seconds since the epoch, used to decide whether tags need re-reading.
    pub mtime: i64,
    pub title: String,
    pub artist: String,
    pub album_artist: String,
    pub album: String,
    pub track_no: u32,
    pub disc_no: u32,
    pub year: u32,
    #[serde(default)]
    pub genre: Option<String>,
    /// Milliseconds.
    pub duration: u64,
    #[serde(default)]
    pub play_count: u32,
    #[serde(default)]
    pub last_played: Option<i64>,
    pub added: i64,
}

impl Track {
    /// Reads tags from `path`. Returns `None` if the file cannot be parsed as
    /// audio at all.
    pub fn read(path: &Path, mtime: i64, added: i64) -> Option<Track> {
        let tagged = Probe::open(path)
            .ok()?
            .options(ParseOptions::new().read_cover_art(false))
            .guess_file_type()
            .ok()?
            .read()
            .ok()?;

        let duration = tagged.properties().duration().as_millis() as u64;
        let tag = tagged.primary_tag().or_else(|| tagged.tags().first());

        let mut track = Track {
            path: path.to_path_buf(),
            mtime,
            title: String::new(),
            artist: String::new(),
            album_artist: String::new(),
            album: String::new(),
            track_no: 0,
            disc_no: 0,
            year: 0,
            genre: None,
            duration,
            play_count: 0,
            last_played: None,
            added,
        };

        if let Some(tag) = tag {
            track.fill_from_tag(tag);
        }

        track.apply_fallbacks(path);
        Some(track)
    }

    fn fill_from_tag(&mut self, tag: &Tag) {
        self.title = tag.title().map(|s| s.trim().to_string()).unwrap_or_default();
        self.album = tag.album().map(|s| s.trim().to_string()).unwrap_or_default();

        let artists = tag.get_strings(ItemKey::TrackArtist).join(", ");
        self.artist = artists.trim().to_string();

        self.album_artist = tag
            .get_string(ItemKey::AlbumArtist)
            .map(|s| s.trim().to_string())
            .unwrap_or_default();

        self.track_no = tag.track().unwrap_or(0);
        self.disc_no = tag.disk().unwrap_or(0);
        self.year = year_of(tag);
        self.genre = tag
            .genre()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
    }

    /// Fills in what the tags did not say, so that grouping never has to deal
    /// with empty keys.
    fn apply_fallbacks(&mut self, path: &Path) {
        if self.title.is_empty() {
            self.title = path
                .file_stem()
                .map(|s| s.to_string_lossy().into_owned())
                .unwrap_or_else(|| String::from("Unknown Title"));
        }

        if self.artist.is_empty() {
            self.artist = self.album_artist.clone();
        }
        if self.artist.is_empty() {
            self.artist = String::from(UNKNOWN_ARTIST);
        }

        // A compilation tags every track with a different artist; without an
        // album artist those tracks would each become their own album, so the
        // containing folder is a better guess than the track artist.
        if self.album_artist.is_empty() {
            self.album_artist = self.artist.clone();
        }

        if self.album.is_empty() {
            self.album = path
                .parent()
                .and_then(|p| p.file_name())
                .map(|s| s.to_string_lossy().into_owned())
                .unwrap_or_else(|| String::from(UNKNOWN_ALBUM));
        }
    }

    pub fn uri(&self) -> String {
        gtk::gio::File::for_path(&self.path).uri().to_string()
    }
}

/// Pulls a release year out of whichever date tag the file happens to carry.
///
/// Dates arrive as bare years, as ISO stamps like `1997-09-29`, and with stray
/// padding, so the leading four digits are all that can be relied on.
fn year_of(tag: &Tag) -> u32 {
    for key in [ItemKey::Year, ItemKey::RecordingDate, ItemKey::ReleaseDate] {
        if let Some(value) = tag.get_string(key) {
            let digits: String = value.trim().chars().take_while(|c| c.is_ascii_digit()).collect();
            if digits.len() == 4 {
                if let Ok(year) = digits.parse() {
                    return year;
                }
            }
        }
    }
    0
}

pub const UNKNOWN_ARTIST: &str = "Unknown Artist";
pub const UNKNOWN_ALBUM: &str = "Unknown Album";

/// Grouping key: case- and whitespace-insensitive, so "The Beatles" and
/// "the beatles " land in the same bucket.
pub fn fold_key(s: &str) -> String {
    s.trim().to_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bare(path: &str) -> Track {
        Track {
            path: PathBuf::from(path),
            mtime: 0,
            title: String::new(),
            artist: String::new(),
            album_artist: String::new(),
            album: String::new(),
            track_no: 0,
            disc_no: 0,
            year: 0,
            genre: None,
            duration: 0,
            play_count: 0,
            last_played: None,
            added: 0,
        }
    }

    #[test]
    fn untagged_file_falls_back_to_its_path() {
        let mut track = bare("/music/Kid A/02 - The National Anthem.flac");
        track.apply_fallbacks(&track.path.clone());

        assert_eq!(track.title, "02 - The National Anthem");
        assert_eq!(track.album, "Kid A");
        assert_eq!(track.artist, UNKNOWN_ARTIST);
        assert_eq!(track.album_artist, UNKNOWN_ARTIST);
    }

    #[test]
    fn album_artist_defaults_to_the_track_artist() {
        let mut track = bare("/music/x/y.flac");
        track.artist = String::from("Portishead");
        track.apply_fallbacks(&track.path.clone());

        assert_eq!(track.album_artist, "Portishead");
    }

    #[test]
    fn a_missing_track_artist_borrows_the_album_artist() {
        let mut track = bare("/music/x/y.flac");
        track.album_artist = String::from("Various Artists");
        track.apply_fallbacks(&track.path.clone());

        assert_eq!(track.artist, "Various Artists");
    }

    #[test]
    fn fold_key_ignores_case_and_padding() {
        assert_eq!(fold_key(" The Beatles "), fold_key("the beatles"));
    }
}
