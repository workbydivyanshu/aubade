// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use gtk::glib::Uri;
use log::warn;
use serde_json::Value;

use super::{
    provider::{ProviderResult, TrackQuery},
    Lyrics,
};

/// Accept a search candidate only when its duration is within this many
/// seconds of the local file. Without it, a same-title different-recording
/// match sails through and the lyrics drift badly.
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

/// The search endpoint matches loosely, so album and duration are deliberately
/// omitted here; duration is applied afterwards when picking a candidate.
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
        // The track is known but carries no synced lyrics. That is an answer,
        // not a failure, so it is cached permanently.
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

    #[test]
    fn search_url_omits_album_and_duration() {
        let url = search_url(&query());
        assert!(url.starts_with("https://lrclib.net/api/search?"));
        assert!(!url.contains("album_name"));
        assert!(!url.contains("duration"));
    }
}
