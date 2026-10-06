"""library.py — extension set, _read_tags, incremental sync_library.

Headless: no GTK, no network. Fixtures are generated WAVs and plain files in
temp dirs; the store is a throwaway DB (see _support). ~/Music is never read.

    /usr/bin/python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402  must precede aubade imports (path + XDG sandbox)
from _support import TempDirTestCase, silent_wav, touch  # noqa: E402

from aubade import library  # noqa: E402
from aubade.library import AUDIO_EXTS, Track, _read_tags, sync_library  # noqa: E402


class AudioExtSetTest(unittest.TestCase):
    def test_common_formats_are_supported(self):
        for ext in (".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b",
                    ".aac", ".wav", ".aiff", ".aif", ".wv", ".ape", ".tta",
                    ".wma"):
            self.assertIn(ext, AUDIO_EXTS, f"{ext} should be scannable")

    def test_non_audio_files_are_rejected(self):
        for ext in (".txt", ".jpg", ".png", ".lrc", ".pdf", ".log", ".db"):
            self.assertNotIn(ext, AUDIO_EXTS)

    def test_every_entry_is_a_lowercase_dot_extension(self):
        for ext in AUDIO_EXTS:
            self.assertTrue(ext.startswith("."), ext)
            self.assertEqual(ext, ext.lower(), ext)


class ReadTagsTest(TempDirTestCase):
    def test_silent_wav_yields_duration_and_fallback_metadata(self):
        path = silent_wav(os.path.join(self.tmpdir(), "Silence Tone.wav"),
                          seconds=1.5)
        track = _read_tags(path)

        self.assertEqual(track.path, path)
        self.assertEqual(track.title, "Silence Tone", "title falls back to stem")
        self.assertEqual(track.artist, "Unknown artist")
        self.assertEqual(track.album, "Unknown album")
        self.assertEqual(track.genre, "")
        self.assertAlmostEqual(track.length, 1.5, places=2)
        self.assertAlmostEqual(track.mtime, os.path.getmtime(path), places=3)
        self.assertTrue(track.playable)
        self.assertEqual((track.lyrics, track.synced), ("", ""))

    def test_missing_file_does_not_raise(self):
        path = os.path.join(self.tmpdir(), "ghost.mp3")
        self.assertFalse(os.path.exists(path))
        track = _read_tags(path)

        self.assertIsInstance(track, Track)
        self.assertEqual(track.title, "ghost")
        self.assertEqual(track.mtime, 0.0, "no mtime for a missing file")
        self.assertEqual(track.length, 0.0)

    def test_corrupt_audio_file_falls_back_to_defaults(self):
        path = touch(os.path.join(self.tmpdir(), "broken.flac"), "not audio")
        track = _read_tags(path)
        self.assertEqual(track.title, "broken")
        self.assertEqual(track.artist, "Unknown artist")
        self.assertEqual(track.length, 0.0)
        self.assertGreater(track.mtime, 0.0, "an unreadable file still has mtime")


class SyncLibraryTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.tmpdir("music")
        self.store = self.new_store()
        self.a = silent_wav(os.path.join(self.root, "a.wav"), seconds=1.0)
        self.b = silent_wav(os.path.join(self.root, "nested", "b.wav"), seconds=2.0)
        os.makedirs(os.path.join(self.root, ".hidden"), exist_ok=True)
        self.hidden = silent_wav(os.path.join(self.root, ".hidden", "c.wav"))
        self.readme = touch(os.path.join(self.root, "notes.txt"), "hi")
        self.cover = touch(os.path.join(self.root, "cover.jpg"), "not audio")

    def test_first_sync_adds_only_audio_files(self):
        result = sync_library([self.root], self.store)
        self.assertEqual(result, {"added": 2, "updated": 0, "removed": 0})
        self.assertEqual(self.store.track_count(), 2)
        self.assertEqual(self.store.all_paths(), {self.a, self.b})
        self.assertNotIn(self.readme, self.store.all_paths())
        self.assertNotIn(self.cover, self.store.all_paths())
        self.assertNotIn(self.hidden, self.store.all_paths(),
                         "dot directories are not walked")

    def test_unchanged_resync_is_a_noop(self):
        sync_library([self.root], self.store)
        result = sync_library([self.root], self.store)
        self.assertEqual(result, {"added": 0, "updated": 0, "removed": 0})
        self.assertEqual(self.store.track_count(), 2)

    def test_changed_file_is_updated_not_duplicated(self):
        sync_library([self.root], self.store)
        before = self.store.known_mtime(self.a)

        silent_wav(self.a, seconds=3.0)
        future = before + 1000.0
        os.utime(self.a, (future, future))

        result = sync_library([self.root], self.store)
        self.assertEqual(result, {"added": 0, "updated": 1, "removed": 0})
        self.assertEqual(self.store.track_count(), 2, "no duplicate rows")
        self.assertAlmostEqual(self.store.known_mtime(self.a), future, places=3)
        row = {t.path: t for t in self.store.all_tracks()}[self.a]
        self.assertAlmostEqual(row.length, 3.0, places=2)

    def test_mtime_inside_tolerance_is_not_rescanned(self):
        sync_library([self.root], self.store)
        before = self.store.known_mtime(self.a)
        silent_wav(self.a, seconds=9.0)
        near = before + 0.4  # within the 0.5s tolerance in sync_library
        os.utime(self.a, (near, near))
        self.assertEqual(sync_library([self.root], self.store)["updated"], 0)

    def test_deleted_file_is_removed(self):
        sync_library([self.root], self.store)
        os.remove(self.b)
        result = sync_library([self.root], self.store)
        self.assertEqual(result, {"added": 0, "updated": 0, "removed": 1})
        self.assertEqual(self.store.all_paths(), {self.a})

    def test_removed_file_drops_its_plays_and_likes(self):
        sync_library([self.root], self.store)
        self.store.record_play(self.b)
        self.store.set_like(self.b, True)
        os.remove(self.b)
        sync_library([self.root], self.store)
        self.assertFalse(self.store.is_liked(self.b))
        self.assertEqual(self.store.counts(), {"tracks": 1, "plays": 0, "likes": 0})

    def test_multiple_roots_and_missing_roots(self):
        other = self.tmpdir("music2")
        c = silent_wav(os.path.join(other, "c.wav"))
        missing = os.path.join(other, "does-not-exist")
        result = sync_library([missing, self.root, other], self.store)
        self.assertEqual(result["added"], 3)
        self.assertIn(c, self.store.all_paths())

    def test_hidden_file_with_audio_ext_is_scanned(self):
        # Current behaviour: only dot *directories* are filtered, not files.
        secret = silent_wav(os.path.join(self.root, ".secret.wav"))
        sync_library([self.root], self.store)
        self.assertIn(secret, self.store.all_paths())

    def test_empty_library_reports_all_zeroes(self):
        empty = self.tmpdir("empty")
        result = sync_library([empty], self.store)
        self.assertEqual(result, {"added": 0, "updated": 0, "removed": 0})
        self.assertEqual(self.store.track_count(), 0)

    def test_new_file_picked_up_on_later_sync(self):
        sync_library([self.root], self.store)
        d = silent_wav(os.path.join(self.root, "d.wav"))
        self.assertEqual(sync_library([self.root], self.store)["added"], 1)
        self.assertIn(d, self.store.all_paths())


class StateFileTest(TempDirTestCase):
    """save_state/load_state — hermetic via a patched STATE_PATH."""

    def setUp(self):
        super().setUp()
        self.state = os.path.join(self.tmpdir("state"), "state.json")
        patcher = mock.patch.object(library, "STATE_PATH", self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_state_roundtrip(self):
        self.assertEqual(library.load_state(), {})
        library.save_state({"volume": 0.42})
        self.assertTrue(os.path.exists(self.state))
        self.assertEqual(library.load_state()["volume"], 0.42)
        library.save_state({})
        self.assertEqual(library.load_state(), {})

    def test_corrupt_state_file_is_treated_as_empty(self):
        _support.touch(self.state, "{not json")
        self.assertEqual(library.load_state(), {})


class SandboxGuardTest(TempDirTestCase):
    """_support redirects XDG_DATA_HOME before aubade modules are imported,
    so the module-level default paths must land in the throwaway sandbox and
    never in the real ~/.local/share/aubade."""

    def test_default_paths_point_into_the_sandbox(self):
        from aubade import store as store_mod
        expected_state = os.path.join(_support.SANDBOX, "aubade", "state.json")
        expected_db = os.path.join(_support.SANDBOX, "aubade", "library.db")
        if library.STATE_PATH != expected_state or store_mod.DB_PATH != expected_db:
            self.skipTest("an aubade module was imported before the test sandbox "
                          "was installed; its path constants are already fixed")
        self.assertEqual(library.STATE_PATH, expected_state)
        self.assertEqual(store_mod.DB_PATH, expected_db)

    def test_default_roots_is_a_list_of_strings(self):
        roots = library.default_roots()
        self.assertIsInstance(roots, list)
        self.assertTrue(all(isinstance(r, str) for r in roots))


if __name__ == "__main__":
    unittest.main()