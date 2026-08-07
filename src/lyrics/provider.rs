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
/// `NoneExist` and `Failed` are deliberately distinct: the first is a
/// definitive answer worth caching forever, the second is worth retrying later.
/// Collapsing them into `Option` would either re-query instrumentals endlessly
/// or permanently blacklist tracks that failed while the machine was offline.
#[derive(Debug)]
pub enum ProviderResult {
    Found(Lyrics),
    NoneExist,
    Failed,
}
