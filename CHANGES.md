# Changes

## Unreleased

### Added

- Time-synced lyrics from sidecar `.lrc` files. The lyrics view replaces the
  album cover, highlights the line matching the current playback position, and
  scrolls to keep it centred. The header bar toggle appears only for songs that
  have lyrics.
- Millisecond-precision playback position, exposed alongside the existing
  second-granularity position so lyrics can track playback accurately.
- Online lyrics lookup via LRCLIB for songs with no local `.lrc` file, with a
  disk cache and a setting to disable all network access. Local files always
  take precedence, and tracks that genuinely have no lyrics are remembered so
  they are never queried twice.
- A full-screen now-playing view, reached from the header bar or F11, showing
  large synced lyrics over a blurred album-art backdrop. Lines fade with
  distance from the one currently playing.

### Changed

- The project is now Aubade, application id
  `io.github.workbydivyanshu.Aubade`.
