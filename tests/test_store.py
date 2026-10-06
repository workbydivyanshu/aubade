"""store.py — SQLite cache + play/like/skip stats.

Headless, no GTK, no network. Every test runs against a throwaway DB in a
temp dir (see _support.TempDirTestCase), never ~/.local/share/aubade.

    /usr/bin/python3 -m unittest discover -s tests -v
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402  must precede aubade imports (path + XDG sandbox)
from _support import TempDirTestCase, add_track  # noqa: E402


class StoreTracksTest(TempDirTestCase):
    def test_upsert_inserts_then_updates_in_place(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "Alpha", artist="A", album="One",
                  genre="Rock", length=100.0, mtime=111.0, disc_number=1,
                  track_number=3, lyrics="la", synced="[00:01.00]la")

        self.assertEqual(store.track_count(), 1)
        self.assertEqual(store.all_paths(), {"/m/a.mp3"})
        self.assertEqual(store.known_mtime("/m/a.mp3"), 111.0)

        row = store.all_tracks()[0]
        self.assertEqual(row.title, "Alpha")
        self.assertEqual(row.artist, "A")
        self.assertEqual(row.album, "One")
        self.assertEqual(row.genre, "Rock")
        self.assertEqual(row.lyrics, "la")
        self.assertEqual(row.synced, "[00:01.00]la")
        # all_tracks() has no disc/track columns, so check the row itself.
        numbered = store.db.execute(
            "SELECT disc_number, track_number, added_ts FROM tracks WHERE path=?",
            ("/m/a.mp3",)).fetchone()
        self.assertEqual((numbered["disc_number"], numbered["track_number"]), (1, 3))
        self.assertGreater(numbered["added_ts"], 0.0)

        # Same path again -> update, never a duplicate row.
        add_track(store, "/m/a.mp3", "Alpha (remix)", artist="B", album="Two",
                  length=200.0, mtime=222.0)
        self.assertEqual(store.track_count(), 1)
        self.assertEqual(store.known_mtime("/m/a.mp3"), 222.0)
        row = store.all_tracks()[0]
        self.assertEqual((row.title, row.artist, row.album), ("Alpha (remix)", "B", "Two"))

    def test_upsert_keeps_original_added_ts(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "Alpha")
        first = store.db.execute(
            "SELECT added_ts FROM tracks WHERE path=?", ("/m/a.mp3",)
        ).fetchone()["added_ts"]
        self.assertGreater(first, 0.0)
        time.sleep(0.01)
        add_track(store, "/m/a.mp3", "Alpha edited")
        again = store.db.execute(
            "SELECT added_ts FROM tracks WHERE path=?", ("/m/a.mp3",)
        ).fetchone()["added_ts"]
        self.assertEqual(first, again, "re-sync must not reset added_ts")

    def test_known_mtime_unknown_path_is_none(self):
        store = self.new_store()
        self.assertIsNone(store.known_mtime("/m/ghost.mp3"))

    def test_all_tracks_ordered_by_artist_album_title(self):
        store = self.new_store()
        add_track(store, "/m/3.mp3", "Zebra", artist="B", album="Two")
        add_track(store, "/m/1.mp3", "Apple", artist="A", album="Two")
        add_track(store, "/m/2.mp3", "Mango", artist="A", album="One")
        order = [(t.artist, t.album, t.title) for t in store.all_tracks()]
        self.assertEqual(order, [("A", "One", "Mango"), ("A", "Two", "Apple"),
                                 ("B", "Two", "Zebra")])

    def test_remove_paths_drops_tracks_plays_and_likes(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "Alpha")
        add_track(store, "/m/b.mp3", "Beta")
        add_track(store, "/m/c.mp3", "Gamma")
        store.record_play("/m/a.mp3")
        store.record_play("/m/b.mp3")
        store.record_play("/m/c.mp3")
        store.set_like("/m/a.mp3", True)

        removed = store.remove_paths({"/m/a.mp3", "/m/c.mp3", "/m/missing.mp3"})
        self.assertEqual(removed, 2, "unknown paths are not counted")
        self.assertEqual(store.track_count(), 1)
        self.assertEqual(store.all_paths(), {"/m/b.mp3"})
        self.assertFalse(store.is_liked("/m/a.mp3"))
        self.assertEqual(store.liked_paths(), set())
        self.assertEqual(store.counts(), {"tracks": 1, "plays": 1, "likes": 0},
                         "only plays belonging to removed paths are dropped")
        self.assertIsNone(store.known_mtime("/m/a.mp3"))

    def test_remove_paths_empty_set_is_noop(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "Alpha")
        self.assertEqual(store.remove_paths(set()), 0)
        self.assertEqual(store.track_count(), 1)

    def test_album_and_artist_queries(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "Alpha", artist="A", album="One",
                  album_artist="AA", genre="Rock", disc_number=1, track_number=1)
        add_track(store, "/m/b.mp3", "Beta", artist="A", album="One",
                  album_artist="AA", genre="Rock", disc_number=1, track_number=2)
        add_track(store, "/m/c.mp3", "Loose", artist="B", album="Unknown album")

        albums = {r["album"]: r for r in store.albums()}
        self.assertEqual(set(albums), {"One"}, "Unknown album must be filtered")
        self.assertEqual(albums["One"]["album_artist"], "AA")
        self.assertEqual(albums["One"]["c"], 2)

        tracks = store.album_tracks("One", "AA")
        self.assertEqual([t.title for t in tracks], ["Alpha", "Beta"])
        self.assertEqual(store.first_track_path("One", "AA"), "/m/a.mp3")

        artists = {r["artist"]: r for r in store.artists()}
        self.assertEqual((artists["A"]["c"], artists["B"]["c"]), (2, 1))
        self.assertEqual([t.title for t in store.tracks_for_artist("A")],
                         ["Alpha", "Beta"])

    def test_genres_sorted_by_count_with_limit(self):
        store = self.new_store()
        add_track(store, "/m/1.mp3", "a", genre="Jazz")
        add_track(store, "/m/2.mp3", "b", genre="Jazz")
        add_track(store, "/m/3.mp3", "c", genre="Pop")
        add_track(store, "/m/4.mp3", "d", genre="")  # excluded
        self.assertEqual(store.top_genres(4), [("Jazz", 2), ("Pop", 1)])
        self.assertEqual(store.top_genres(1), [("Jazz", 2)])
        self.assertEqual([t.title for t in store.tracks_for_genre("Jazz")],
                         ["a", "b"])


class StoreEventsTest(TempDirTestCase):
    def test_toggle_like_flips_and_set_like_is_idempotent(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "Alpha")

        self.assertFalse(store.is_liked("/m/a.mp3"))
        # NB: toggle_like() is annotated -> bool but returns set_like()'s None;
        # only the persisted state is meaningful today.
        store.toggle_like("/m/a.mp3")
        self.assertTrue(store.is_liked("/m/a.mp3"))
        self.assertEqual(store.liked_paths(), {"/m/a.mp3"})
        store.toggle_like("/m/a.mp3")
        self.assertFalse(store.is_liked("/m/a.mp3"))
        self.assertEqual(store.liked_paths(), set())

        store.set_like("/m/a.mp3", True)
        store.set_like("/m/a.mp3", True)
        self.assertEqual(store.counts()["likes"], 1)
        self.assertEqual([t.title for t in store.liked_tracks_list()], ["Alpha"])

        store.set_like("/m/a.mp3", False)
        store.set_like("/m/a.mp3", False)
        self.assertEqual(store.counts()["likes"], 0)
        self.assertEqual(store.liked_tracks_list(), [])

    def test_record_play_counts_and_orders(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "Alpha", artist="A")
        add_track(store, "/m/b.mp3", "Beta", artist="B")

        store.record_play("/m/a.mp3")
        store.record_play("/m/a.mp3")
        store.record_play("/m/b.mp3")

        plays = {r["path"]: r for r in store.all_plays()}
        self.assertEqual(set(plays), {"/m/a.mp3", "/m/b.mp3"})
        self.assertEqual(plays["/m/a.mp3"]["times"], 2)
        self.assertEqual(plays["/m/b.mp3"]["times"], 1)
        self.assertEqual(plays["/m/a.mp3"]["title"], "Alpha")
        self.assertGreater(plays["/m/b.mp3"]["ts"], plays["/m/a.mp3"]["ts"],
                           "b was played last")
        self.assertEqual([r["path"] for r in store.all_plays(1)], ["/m/b.mp3"])

        recent = store.recent_plays(1)
        self.assertEqual([r["path"] for r in recent], ["/m/b.mp3"])
        self.assertEqual([t.title for t in store.most_played_tracks(1)], ["Alpha"])

    def test_plays_for_unknown_track_are_counted_but_not_joined(self):
        store = self.new_store()
        store.record_play("/m/not-in-library.mp3")
        self.assertEqual(store.counts()["plays"], 1)
        self.assertEqual(store.all_plays(), [], "all_plays joins the tracks table")

    def test_clear_plays_wipes_plays_and_skips(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "Alpha")
        store.record_play("/m/a.mp3")
        store.record_skip("/m/a.mp3")
        self.assertEqual(
            store.db.execute("SELECT COUNT(*) c FROM skips").fetchone()["c"], 1)
        store.clear_plays()
        self.assertEqual(store.counts(), {"tracks": 1, "plays": 0, "likes": 0})
        self.assertEqual(store.all_plays(), [])


class StoreStatsTest(TempDirTestCase):
    def test_empty_store_reports_no_data(self):
        store = self.new_store()
        self.assertEqual(store.counts(), {"tracks": 0, "plays": 0, "likes": 0})
        self.assertIsNone(store.top_artist())
        self.assertIsNone(store.top_album())
        self.assertEqual(store.top_genres(4), [])
        self.assertEqual(store.albums(), [])
        self.assertEqual(store.artists(), [])
        self.assertEqual(store.recent_added(), [])
        self.assertEqual(store.most_played_tracks(), [])

    def test_top_artist_prefers_plays_then_track_count(self):
        store = self.new_store()
        add_track(store, "/m/a1.mp3", "A1", artist="Quiet")
        add_track(store, "/m/a2.mp3", "A2", artist="Quiet")
        add_track(store, "/m/b1.mp3", "B1", artist="Loud")
        # No plays yet -> fallback is the artist with most tracks.
        self.assertEqual(store.top_artist(), ("Quiet", 2, 0))

        store.record_play("/m/b1.mp3")
        self.assertEqual(store.top_artist(), ("Loud", 1, 1))

    def test_top_album_prefers_plays_inside_window(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "A", artist="X", album="Played")
        add_track(store, "/m/b.mp3", "B", artist="X", album="Quiet")
        store.record_play("/m/a.mp3")

        self.assertEqual(store.top_album(days=7), ("Played", "X"))
        # Zero-width window: the play is out of range, so it falls back to the
        # most recently added real album instead.
        self.assertEqual(store.top_album(days=0.0), ("Quiet", "X"))

    def test_top_album_falls_back_to_newest_added(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "A", artist="X", album="Older")
        add_track(store, "/m/b.mp3", "B", artist="X", album="Newer")
        newest = store.db.execute(
            "SELECT album FROM tracks ORDER BY added_ts DESC LIMIT 1"
        ).fetchone()["album"]
        self.assertEqual(store.top_album(days=7), (newest, "X"))

    def test_recent_added_ordered_by_added_ts_desc(self):
        store = self.new_store()
        add_track(store, "/m/1.mp3", "One")
        add_track(store, "/m/2.mp3", "Two")
        add_track(store, "/m/3.mp3", "Three")
        self.assertEqual([t.title for t in store.recent_added(2)], ["Three", "Two"])

    def test_sorted_views_and_profile_roundtrip(self):
        store = self.new_store()
        add_track(store, "/m/a.mp3", "Alpha", artist="A")
        add_track(store, "/m/b.mp3", "Beta", artist="B")
        self.assertEqual([t.title for t in store.all_tracks_sorted("title")],
                         ["Alpha", "Beta"])
        self.assertEqual([t.title for t in store.all_tracks_sorted("artist")],
                         ["Alpha", "Beta"])

        self.assertEqual(store.get_profile("theme", "fallback"), "fallback")
        store.set_profile("theme", "dark")
        self.assertEqual(store.get_profile("theme"), "dark")
        store.set_profile("theme", "light")
        self.assertEqual(store.get_profile("theme", "fallback"), "light")


class StoreLyricsTest(TempDirTestCase):
    def test_lyrics_cache_missing_then_roundtrip(self):
        store = self.new_store()
        self.assertEqual(store.cached_lyrics("/m/a.mp3"), (None, None))

        store.save_lyrics("/m/a.mp3", "static words", "[00:01.00]words")
        self.assertEqual(store.cached_lyrics("/m/a.mp3"),
                         ("static words", "[00:01.00]words"))
        store.save_lyrics("/m/a.mp3", "new static", "")
        self.assertEqual(store.cached_lyrics("/m/a.mp3"), ("new static", ""))

    def test_embedded_lyrics_come_from_the_tracks_row(self):
        store = self.new_store()
        self.assertEqual(store.embedded_lyrics("/m/a.mp3"), ("", ""))
        add_track(store, "/m/a.mp3", "A", lyrics="plain", synced="[00:02.00]plain")
        self.assertEqual(store.embedded_lyrics("/m/a.mp3"),
                         ("plain", "[00:02.00]plain"))


if __name__ == "__main__":
    unittest.main()