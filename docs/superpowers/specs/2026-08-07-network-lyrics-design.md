# Network lyrics fetching — design

Date: 2026-08-07
Status: approved, not yet implemented
Sub-project: 2 of 3

## Context

Aubade currently shows time-synced lyrics only for songs that have a sidecar
`.lrc` file. This adds an online source so lyrics appear without the user
preparing files by hand.

Sub-project 1 (rebrand to Aubade) is complete and merged to `main`.
Sub-project 3 (Apple Music-grade UI) follows this one.

## Goal

Fetch time-synced lyrics from LRCLIB when no sidecar file exists, cache the
result on disk, and display it through the existing lyrics view — without
blocking the UI and without writing into the user's music library.

## Non-goals

- No writing to the user's music folders. Fetched lyrics live in the cache only.
- No additional providers in v1. The trait exists so Kugou or NetEase can be
  added later, but only LRCLIB ships now.
- No lyrics editing, uploading, or contributing back to LRCLIB.
- No word-level karaoke. Sync stays line-level, as established in sub-project 1.
- No account, API key, or per-user identifier.

## Resolution order

First hit wins:

1. **Sidecar `.lrc`** beside the audio file
2. **Disk cache**
3. **LRCLIB** over the network
4. **Nothing** — the toggle stays hidden, exactly as today

The user has 2,649 existing sidecar files. Those keep working untouched and
never trigger a network request.

## LRCLIB API

Verified against the live service on 2026-08-07.

- `GET https://lrclib.net/api/get` with query parameters `artist_name`,
  `track_name`, `album_name`, `duration` (seconds)
- A track with no match returns HTTP 404
- Falls back to `GET https://lrclib.net/api/search` with `artist_name` and
  `track_name` on 404. This returns a JSON **array** of candidates (up to 20),
  each with the same field shape as `/api/get`, ordered by relevance. The first
  candidate whose `duration` is within ±3s of the local file is accepted; if
  none qualifies, the result is a transient miss.
- No authentication, no API key
- Response fields used: `syncedLyrics` (a string in LRC format),
  `instrumental` (bool), `duration` (float, for match confirmation)
- `plainLyrics` is ignored: it carries no timestamps, and unsynced lyrics are
  out of scope
- `instrumental: true` is a definitive answer, not a failure. It is cached as a
  negative result so the track is never queried again.

`syncedLyrics` is already LRC-formatted and feeds directly into the existing
`Lyrics::parse`, which has been validated against 2,000 real files.

## Components

### `src/lyrics/provider.rs`

```rust
pub struct TrackQuery {
    pub artist: String,
    pub title: String,
    pub album: Option<String>,
    pub duration_secs: u64,
}

pub trait LyricsProvider {
    fn name(&self) -> &'static str;
    async fn fetch(&self, query: &TrackQuery) -> ProviderResult;
}

pub enum ProviderResult {
    Found(Lyrics),
    /// The track exists and definitively has no lyrics (e.g. instrumental).
    NoneExist,
    /// Lookup failed; may succeed later.
    Failed,
}
```

The three-way result matters: `NoneExist` is cached permanently, `Failed` is
cached only briefly. Collapsing them into `Option` would either re-query
instrumentals forever or permanently blacklist tracks that failed because the
network was down.

### `src/lyrics/lrclib.rs`

The LRCLIB implementation of `LyricsProvider`. Owns URL construction, the HTTP
call, and JSON decoding. No caching logic and no GTK types.

### `src/lyrics/cache.rs`

```rust
pub fn cache_key(query: &TrackQuery) -> String;
pub fn load(key: &str) -> Option<CacheEntry>;
pub fn store(key: &str, entry: &CacheEntry);
```

- Location: `~/.cache/aubade/lyrics/`
- Key: SHA-256 of the normalised `artist|title|album|duration`, lowercased with
  whitespace collapsed, so trivial tag differences hit the same entry
- Positive entries stored as `<key>.lrc`
- Negative entries stored as `<key>.miss`, containing a timestamp and whether
  the miss was definitive (`NoneExist`) or transient (`Failed`)
- Transient misses expire after 7 days; definitive misses never expire

## HTTP

libsoup 3 via the `soup3` crate (0.9), which depends on glib ^0.22 and gio
^0.22. The project already resolves glib 0.22.8 through gtk4 0.11.4, so there is
no version skew and no second async runtime: requests run on the GLib main
context alongside the rest of the application.

- Descriptive User-Agent identifying Aubade and its repository, which is what
  LRCLIB asks of clients
- 10 second timeout, so a hanging request cannot wedge the lyrics view
- One request per song change at most

## Settings and privacy

This is the first network request the application has ever made. Artist and
track names leave the machine, so the behaviour is explicit and controllable.

- A new GSettings key, `fetch-lyrics-online`, boolean, default `true`
- Exposed as a visible toggle in the UI
- When disabled, no network request is made under any circumstance. Cached
  results still display.
- No telemetry, no analytics, no identifier of any kind is transmitted

## Error handling

Every failure degrades to "no lyrics". None produces a dialog or blocks playback.

| Condition | Behaviour |
|---|---|
| Setting disabled | No request. Sidecar and cache still work. |
| Missing artist or title tag | No request. Guessing produces wrong matches. |
| Offline, DNS failure, timeout | Cache as transient miss, retry after expiry |
| HTTP error status | Cache as transient miss, log at `warn` |
| Malformed JSON | Cache as transient miss, log at `warn` |
| `instrumental: true` | Cache as definitive miss, never re-query |
| Empty `syncedLyrics` | Cache as definitive miss |
| Song changes mid-request | Discard the result; it belongs to a stale track |

That last row matters: playback can move on while a request is in flight, and
applying a late response would show the wrong song's lyrics.

## Testing

- `cache_key` normalisation, and the positive/negative/expiry behaviour of the
  cache, are pure logic and get real unit tests
- The LRCLIB response decoder is tested against **recorded JSON fixtures**
  committed to the repository, so tests run offline and do not depend on
  LRCLIB's data staying constant. Fixtures cover: a synced hit, an instrumental
  track, a 404, and malformed JSON.
- Fixtures store the response *shape*. Any lyric text in a fixture is replaced
  with invented placeholder lines.
- The live network path is verified once by hand, on the user's display, with
  a track that has no sidecar file.

## Risk register

| Risk | Consequence | Mitigation |
|---|---|---|
| Stale response applied after song change | Wrong lyrics shown | Tag each request with the song; discard mismatches |
| Wrong match from fuzzy search | Wrong lyrics shown | Confirm duration within ±3s before accepting a search result |
| Network call on the main thread | UI freeze | soup3 async on the GLib main context; never blocking |
| Repeated queries for tracks with no lyrics | Pointless traffic | Definitive negative caching |
| `soup3` version skew with gtk4's glib | Build failure | Verified: both resolve glib 0.22 |

## Branching

Work happens on a `lyrics-online` branch off `main`.
