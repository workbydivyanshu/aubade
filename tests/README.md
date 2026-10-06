# Aubade test suite

Automated smoke tests for the native GTK4 player in `../aubade/`. Standard
library `unittest` only — no pytest, no network, no fixture plugins.

## Run

From the project root (`/home/divyu/aubade/aubade`):

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```

Other useful invocations:

```bash
/usr/bin/python3 -m unittest discover -s tests -t .     # package-style names
/usr/bin/python3 tests/test_store.py                   # single file
/usr/bin/python3 -m unittest discover -s tests -k ParseLrc   # filter by name
env -u DISPLAY -u WAYLAND_DISPLAY \
  /usr/bin/python3 -m unittest discover -s tests       # force headless skips
```

The suite is order-independent, runs in well under a second, and the cwd does
not matter (`sys.path` is fixed up by `tests/_support.py`).

## Requirements

* `/usr/bin/python3` (3.14 here) — the app must run under system python.
* `python3-gi` + GTK 4 + `Gst` 1.0 for the one integration module, and
  `python3-mutagen` for tag reads. Everything else is stdlib.

## Files

| File | Covers | Needs a display? |
| --- | --- | --- |
| `_support.py` | fixtures: temp dirs, throwaway `Store`, `silent_wav()`, `fake_track()`, XDG sandbox | no |
| `test_store.py` | `store.py` — upsert, `known_mtime`, `all_paths`, `remove_paths`, likes, plays/skips, derived stats, lyrics cache, profile | no |
| `test_library.py` | `library.py` — `AUDIO_EXTS`, `_read_tags` on a generated WAV / missing / corrupt file, `sync_library` add-change-delete, `save_state`/`load_state` | no |
| `test_lyrics.py` | `lyrics.py` — `parse_lrc` (2- and 3-digit ms, metadata, sorting), `is_synced`, `current_line` index math, `.lrc` sidecars, `resolve_local` priority chain | no |
| `test_engine_queue.py` | `player.Engine` — `set_queue`, `play_next`, `play_last`, `add_to_queue`, `remove_from_queue`, `move_in_queue`, `clear_queue`, repeat/shuffle flags | **yes, skipped headless** |

## Headless / skip behaviour

`test_engine_queue.py` builds a real GStreamer `playbin`, so it is decorated
with three guards and reports as `skipped` (never as an error) when:

1. neither `DISPLAY` nor `WAYLAND_DISPLAY` is set,
2. `Gtk.init_check()` fails (no session bus / headless),
3. `Gst.init()` fails or the `playbin` element factory is missing.

Even with GTK available it never sets the pipeline to `PLAYING`, so no audio
sink or sound card is required. The other 66 tests are pure Python and pass on
a headless box.

## Isolation guarantees

* Every `Store` is created on a fresh SQLite file inside a temp dir, so the real
  `~/.local/share/aubade/library.db` is never opened. `SandboxGuardTest`
  asserts the module-level default paths point into the sandbox (it skips if
  some other module imported `aubade.*` before the sandbox was installed).
* `_support` also overrides `XDG_DATA_HOME` to a temp dir before any `aubade.*`
  import, which redirects `store.DB_PATH` and `library.STATE_PATH`; the temp
  dir is removed via `atexit`.
* `~/Music` is never read: `sync_library` is only ever pointed at generated
  temp trees, and `default_roots()` is checked without being traversed.
* `lyrics.fetch_network` is patched out (`unittest.mock`) in the two `resolve`
  tests, so nothing hits LRCLIB or lyrics.ovh.
* Audio fixtures are generated on the fly with `wave` — silent mono 16-bit
  WAVs — so no media files are needed.

## Notes on current behaviour

A few tests assert what the code *actually* does rather than what the signature
suggests. Worth knowing if one of them ever starts failing:

* `Store.toggle_like()` is annotated `-> bool` but returns `set_like()`'s
  `None`; only the persisted state is meaningful.
* `parse_lrc` strips timestamps only, so an inline `[ar:...]` tag stays in the
  line text (`"[ar:Artist]Real line"`).
* `is_synced` requires 2 or 3 fractional digits, so `[00:01.5]` is not synced.
* `sync_library` filters dot *directories* but not dot *files*, so `.secret.wav`
  is scanned.
* `Store.all_tracks()` does not select `disc_number`/`track_number`, so those
  are asserted straight off the SQL row.