// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026

//! The library: what Aubade knows about a music collection between runs.
//!
//! Amberol, which Aubade grew out of, only ever had a queue — a flat list of
//! files with no memory. Albums, artists, play counts and anything that browses
//! them need entities that outlive a session, which is what lives here.
//!
//! The index is a single JSON file rather than a database. At the size this is
//! built for — tens of thousands of tracks — loading it whole costs less than
//! keeping a schema, a migration path and a query layer alive.

mod scan;
mod track;

use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
};

use log::{debug, warn};
use serde::{Deserialize, Serialize};

pub use scan::{now_secs, ScanStats};
pub use track::{fold_key, Track, UNKNOWN_ALBUM, UNKNOWN_ARTIST};

/// Bumped when the on-disk shape changes in a way old files cannot satisfy.
/// A mismatch throws the index away and rescans rather than guessing.
const INDEX_VERSION: u32 = 1;

#[derive(Serialize, Deserialize)]
struct Index {
    version: u32,
    roots: Vec<PathBuf>,
    tracks: Vec<Track>,
}

/// An album, derived from the tracks that claim it.
#[derive(Debug, Clone)]
pub struct Album {
    pub title: String,
    pub artist: String,
    pub year: u32,
    /// Indices into [`Library::tracks`], in disc then track order.
    pub tracks: Vec<usize>,
}

/// An artist, derived from the albums credited to them.
#[derive(Debug, Clone)]
pub struct Artist {
    pub name: String,
    /// Indices into [`Library::albums`], newest first.
    pub albums: Vec<usize>,
    pub track_count: usize,
}

#[derive(Default)]
pub struct Library {
    tracks: Vec<Track>,
    roots: Vec<PathBuf>,
    albums: Vec<Album>,
    artists: Vec<Artist>,
    /// Path to track index, so playback can report a finished song back.
    by_path: HashMap<PathBuf, usize>,
}

impl Library {
    pub fn new() -> Self {
        Self::default()
    }

    fn index_path() -> PathBuf {
        // User data, not cache: play counts must survive a cache wipe.
        let mut path = gtk::glib::user_data_dir();
        path.push("aubade");
        path.push("library.json");
        path
    }

    /// Loads the index, or returns an empty library if there isn't a usable one.
    pub fn load() -> Self {
        let path = Self::index_path();

        let contents = match fs::read_to_string(&path) {
            Ok(contents) => contents,
            Err(e) => {
                debug!("No library index at {}: {}", path.display(), e);
                return Self::new();
            }
        };

        let index: Index = match serde_json::from_str(&contents) {
            Ok(index) => index,
            Err(e) => {
                warn!("Library index is unreadable, starting over: {}", e);
                return Self::new();
            }
        };

        if index.version != INDEX_VERSION {
            debug!(
                "Library index is version {}, expected {}; rescanning",
                index.version, INDEX_VERSION
            );
            return Self {
                roots: index.roots,
                ..Self::new()
            };
        }

        let mut library = Self {
            tracks: index.tracks,
            roots: index.roots,
            ..Self::new()
        };
        library.reindex();
        library
    }

    pub fn save(&self) -> std::io::Result<()> {
        let path = Self::index_path();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }

        let index = Index {
            version: INDEX_VERSION,
            roots: self.roots.clone(),
            tracks: self.tracks.clone(),
        };
        let json = serde_json::to_string(&index)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;

        // Write beside the target and rename, so a crash mid-write cannot
        // leave a truncated index behind.
        let temporary = path.with_extension("json.tmp");
        fs::write(&temporary, json)?;
        fs::rename(&temporary, &path)
    }

    pub fn roots(&self) -> &[PathBuf] {
        &self.roots
    }

    /// Adds a folder to watch. Nested and duplicate roots are ignored, so that
    /// a track cannot be indexed twice.
    pub fn add_root(&mut self, path: PathBuf) -> bool {
        if self
            .roots
            .iter()
            .any(|existing| path == *existing || path.starts_with(existing))
        {
            return false;
        }

        // A new parent supersedes any root beneath it.
        self.roots.retain(|existing| !existing.starts_with(&path));
        self.roots.push(path);
        true
    }

    pub fn remove_root(&mut self, path: &Path) {
        self.roots.retain(|existing| existing != path);
    }

    /// Rescans every root and rebuilds the derived views.
    ///
    /// The tag reading inside is blocking; callers on the main thread should
    /// hand [`Library::take_tracks`]/[`scan::scan`] to a worker instead.
    pub fn rescan<F>(&mut self, progress: F) -> ScanStats
    where
        F: FnMut(usize, usize),
    {
        let (tracks, stats) = scan::scan(&self.roots, &self.tracks, progress);
        self.tracks = tracks;
        self.reindex();
        stats
    }

    /// Replaces the track list with the result of a scan run elsewhere.
    pub fn adopt(&mut self, tracks: Vec<Track>) {
        self.tracks = tracks;
        self.reindex();
    }

    pub fn tracks(&self) -> &[Track] {
        &self.tracks
    }

    pub fn albums(&self) -> &[Album] {
        &self.albums
    }

    pub fn artists(&self) -> &[Artist] {
        &self.artists
    }

    pub fn is_empty(&self) -> bool {
        self.tracks.is_empty()
    }

    pub fn track(&self, index: usize) -> Option<&Track> {
        self.tracks.get(index)
    }

    pub fn album(&self, index: usize) -> Option<&Album> {
        self.albums.get(index)
    }

    /// The tracks of an album, in playing order.
    pub fn album_tracks(&self, index: usize) -> Vec<&Track> {
        self.albums
            .get(index)
            .map(|album| album.tracks.iter().filter_map(|i| self.tracks.get(*i)).collect())
            .unwrap_or_default()
    }

    /// Records a play against `path`, for the ranked shelves to sort on.
    /// Returns false if the file is not in the library.
    pub fn mark_played(&mut self, path: &Path) -> bool {
        match self.by_path.get(path) {
            Some(&index) => {
                let track = &mut self.tracks[index];
                track.play_count = track.play_count.saturating_add(1);
                track.last_played = Some(scan::now_secs());
                true
            }
            None => false,
        }
    }

    /// Most played first; tracks never played are left out entirely rather
    /// than padding the shelf with arbitrary ones.
    pub fn most_played(&self, limit: usize) -> Vec<usize> {
        let mut ranked: Vec<usize> = (0..self.tracks.len())
            .filter(|i| self.tracks[*i].play_count > 0)
            .collect();
        ranked.sort_by(|a, b| {
            self.tracks[*b]
                .play_count
                .cmp(&self.tracks[*a].play_count)
                .then_with(|| self.tracks[*a].title.cmp(&self.tracks[*b].title))
        });
        ranked.truncate(limit);
        ranked
    }

    /// Albums with the most recently added tracks first.
    pub fn recently_added_albums(&self, limit: usize) -> Vec<usize> {
        let mut ranked: Vec<usize> = (0..self.albums.len()).collect();
        ranked.sort_by_key(|i| std::cmp::Reverse(self.album_added(*i)));
        ranked.truncate(limit);
        ranked
    }

    fn album_added(&self, index: usize) -> i64 {
        self.albums[index]
            .tracks
            .iter()
            .filter_map(|i| self.tracks.get(*i))
            .map(|t| t.added)
            .max()
            .unwrap_or(0)
    }

    /// Case-insensitive substring match across title, artist and album.
    pub fn search(&self, query: &str, limit: usize) -> Vec<usize> {
        let needle = fold_key(query);
        if needle.is_empty() {
            return Vec::new();
        }

        let mut hits = Vec::new();
        for (index, track) in self.tracks.iter().enumerate() {
            let matched = fold_key(&track.title).contains(&needle)
                || fold_key(&track.artist).contains(&needle)
                || fold_key(&track.album).contains(&needle);
            if matched {
                hits.push(index);
                if hits.len() >= limit {
                    break;
                }
            }
        }
        hits
    }

    /// Rebuilds albums, artists and the path lookup from the track list.
    fn reindex(&mut self) {
        self.by_path = self
            .tracks
            .iter()
            .enumerate()
            .map(|(i, t)| (t.path.clone(), i))
            .collect();

        // Group by album artist and album title together: two different
        // artists can each have a "Greatest Hits".
        let mut album_of: HashMap<(String, String), usize> = HashMap::new();
        let mut albums: Vec<Album> = Vec::new();

        for (index, track) in self.tracks.iter().enumerate() {
            let key = (fold_key(&track.album_artist), fold_key(&track.album));
            let album_index = *album_of.entry(key).or_insert_with(|| {
                albums.push(Album {
                    title: track.album.clone(),
                    artist: track.album_artist.clone(),
                    year: 0,
                    tracks: Vec::new(),
                });
                albums.len() - 1
            });

            albums[album_index].tracks.push(index);
            // The earliest non-zero year wins; a stray untagged track should
            // not blank out an album's date.
            let year = track.year;
            let current = albums[album_index].year;
            if year != 0 && (current == 0 || year < current) {
                albums[album_index].year = year;
            }
        }

        for album in albums.iter_mut() {
            album.tracks.sort_by_key(|i| {
                let track = &self.tracks[*i];
                (track.disc_no, track.track_no, track.title.clone())
            });
        }

        albums.sort_by(|a, b| {
            fold_key(&a.artist)
                .cmp(&fold_key(&b.artist))
                .then_with(|| a.year.cmp(&b.year))
                .then_with(|| fold_key(&a.title).cmp(&fold_key(&b.title)))
        });

        let mut artist_of: HashMap<String, usize> = HashMap::new();
        let mut artists: Vec<Artist> = Vec::new();

        for (index, album) in albums.iter().enumerate() {
            let artist_index = *artist_of
                .entry(fold_key(&album.artist))
                .or_insert_with(|| {
                    artists.push(Artist {
                        name: album.artist.clone(),
                        albums: Vec::new(),
                        track_count: 0,
                    });
                    artists.len() - 1
                });

            artists[artist_index].albums.push(index);
            artists[artist_index].track_count += album.tracks.len();
        }

        for artist in artists.iter_mut() {
            artist
                .albums
                .sort_by_key(|i| std::cmp::Reverse(albums[*i].year));
        }
        artists.sort_by_key(|a| fold_key(&a.name));

        self.albums = albums;
        self.artists = artists;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn track(artist: &str, album_artist: &str, album: &str, title: &str, no: u32) -> Track {
        Track {
            path: PathBuf::from(format!("/m/{}/{}/{}.flac", album_artist, album, title)),
            mtime: 0,
            title: String::from(title),
            artist: String::from(artist),
            album_artist: String::from(album_artist),
            album: String::from(album),
            track_no: no,
            disc_no: 1,
            year: 2000,
            genre: None,
            duration: 1000,
            play_count: 0,
            last_played: None,
            added: 0,
        }
    }

    fn library_of(tracks: Vec<Track>) -> Library {
        let mut library = Library::new();
        library.adopt(tracks);
        library
    }

    #[test]
    fn tracks_group_into_albums_and_artists() {
        let library = library_of(vec![
            track("Radiohead", "Radiohead", "Kid A", "Idioteque", 8),
            track("Radiohead", "Radiohead", "Kid A", "Everything", 1),
            track("Portishead", "Portishead", "Dummy", "Roads", 5),
        ]);

        assert_eq!(library.albums().len(), 2);
        assert_eq!(library.artists().len(), 2);
    }

    #[test]
    fn album_tracks_come_back_in_disc_and_track_order() {
        let library = library_of(vec![
            track("Radiohead", "Radiohead", "Kid A", "Idioteque", 8),
            track("Radiohead", "Radiohead", "Kid A", "Everything", 1),
        ]);

        let kid_a = library
            .albums()
            .iter()
            .position(|a| a.title == "Kid A")
            .unwrap();
        let titles: Vec<&str> = library
            .album_tracks(kid_a)
            .iter()
            .map(|t| t.title.as_str())
            .collect();

        assert_eq!(titles, vec!["Everything", "Idioteque"]);
    }

    #[test]
    fn the_same_album_title_under_two_artists_stays_two_albums() {
        let library = library_of(vec![
            track("A", "A", "Greatest Hits", "One", 1),
            track("B", "B", "Greatest Hits", "Two", 1),
        ]);

        assert_eq!(library.albums().len(), 2);
    }

    #[test]
    fn a_compilation_groups_under_its_album_artist() {
        let library = library_of(vec![
            track("Solo One", "Various Artists", "Comp", "One", 1),
            track("Solo Two", "Various Artists", "Comp", "Two", 2),
        ]);

        assert_eq!(library.albums().len(), 1);
        assert_eq!(library.albums()[0].artist, "Various Artists");
    }

    #[test]
    fn casing_differences_do_not_split_an_album() {
        let library = library_of(vec![
            track("Radiohead", "Radiohead", "Kid A", "One", 1),
            track("radiohead", "radiohead", "kid a", "Two", 2),
        ]);

        assert_eq!(library.albums().len(), 1);
        assert_eq!(library.albums()[0].tracks.len(), 2);
    }

    #[test]
    fn playing_a_track_raises_its_count() {
        let mut library = library_of(vec![track("A", "A", "Album", "Song", 1)]);
        let path = library.tracks()[0].path.clone();

        assert!(library.mark_played(&path));
        assert_eq!(library.tracks()[0].play_count, 1);
        assert!(library.tracks()[0].last_played.is_some());
    }

    #[test]
    fn playing_an_unknown_path_is_reported_rather_than_ignored() {
        let mut library = library_of(vec![track("A", "A", "Album", "Song", 1)]);
        assert!(!library.mark_played(Path::new("/nowhere.flac")));
    }

    #[test]
    fn most_played_ranks_and_omits_the_unplayed() {
        let mut library = library_of(vec![
            track("A", "A", "Album", "Rare", 1),
            track("A", "A", "Album", "Favourite", 2),
        ]);

        let favourite = library.tracks()[1].path.clone();
        library.mark_played(&favourite);
        library.mark_played(&favourite);

        let ranked = library.most_played(10);
        assert_eq!(ranked.len(), 1);
        assert_eq!(library.tracks()[ranked[0]].title, "Favourite");
    }

    #[test]
    fn search_spans_title_artist_and_album() {
        let library = library_of(vec![
            track("Radiohead", "Radiohead", "Kid A", "Idioteque", 1),
            track("Portishead", "Portishead", "Dummy", "Roads", 1),
        ]);

        assert_eq!(library.search("idiot", 10).len(), 1);
        assert_eq!(library.search("dummy", 10).len(), 1);
        assert_eq!(library.search("head", 10).len(), 2);
        assert_eq!(library.search("  ", 10).len(), 0);
    }

    #[test]
    fn a_nested_root_is_not_added_twice() {
        let mut library = Library::new();
        assert!(library.add_root(PathBuf::from("/music")));
        assert!(!library.add_root(PathBuf::from("/music/rock")));
        assert_eq!(library.roots().len(), 1);
    }

    #[test]
    fn a_parent_root_replaces_the_roots_beneath_it() {
        let mut library = Library::new();
        library.add_root(PathBuf::from("/music/rock"));
        library.add_root(PathBuf::from("/music/jazz"));
        assert!(library.add_root(PathBuf::from("/music")));

        assert_eq!(library.roots(), &[PathBuf::from("/music")]);
    }
}
