"""player.Engine queue logic — the one GTK/GStreamer-dependent integration test.

Queue bookkeeping is pure Python, but Engine() builds a real Gst playbin, so
this module skips itself when there is no display, when Gtk cannot initialise,
or when GStreamer has no playbin. No audio sink is needed and nothing is ever
set to PLAYING: only queue/move/remove bookkeeping runs.

Skip conditions (checked at import time):
  * no DISPLAY / WAYLAND_DISPLAY environment variable
  * Gtk.init_check() fails (headless session)
  * Gst.init() fails or the playbin element factory is missing

    /usr/bin/python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402  must precede aubade imports (path + XDG sandbox)
from _support import fake_track  # noqa: E402


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _gtk_ready() -> bool:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        result = Gtk.init_check()
    except Exception:
        return False
    # PyGObject >= 3.52 returns a bare bool; older returns (ok, argv).
    return bool(result[0] if isinstance(result, tuple) else result)


def _playbin_ready() -> bool:
    if not _gtk_ready():
        return False
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        return Gst.ElementFactory.make("playbin", "aubade-tests-probe") is not None
    except Exception:
        return False


needs_display = unittest.skipUnless(
    _has_display(), "no DISPLAY/WAYLAND_DISPLAY — skipping GTK integration test")
needs_gtk = unittest.skipUnless(
    _has_display() and _gtk_ready(), "Gtk.init_check() failed — headless session")
needs_playbin = unittest.skipUnless(
    _has_display() and _gtk_ready() and _playbin_ready(),
    "GStreamer playbin unavailable — skipping engine test")


def _titles(engine):
    return [t.title for t in engine.queue]


@needs_display
@needs_gtk
@needs_playbin
class EngineQueueTest(unittest.TestCase):
    """Queue mutations only — playback is never started."""

    @classmethod
    def setUpClass(cls):
        from aubade.player import Engine
        cls.engine = Engine()

    @classmethod
    def tearDownClass(cls):
        cls.engine.shutdown()

    def setUp(self):
        self.engine.clear_queue()
        self.engine.playing = False

    # ---------- set_queue ----------
    def test_set_queue_sets_queue_and_start_index(self):
        self.engine.set_queue([fake_track("a"), fake_track("b"), fake_track("c")], 1)
        self.assertEqual(_titles(self.engine), ["a", "b", "c"])
        self.assertEqual(self.engine.index, 1)
        self.assertEqual(self.engine.current().title, "b")

    def test_set_queue_filters_unplayable_tracks(self):
        tracks = [fake_track("a"), fake_track("skip", playable=False),
                  fake_track("c")]
        self.engine.set_queue(tracks, 0)
        self.assertEqual(_titles(self.engine), ["a", "c"])

    def test_set_queue_empty_resets_index(self):
        self.engine.set_queue([fake_track("a")], 0)
        self.engine.set_queue([], 0)
        self.assertEqual(self.engine.queue, [])
        self.assertEqual(self.engine.index, -1)
        self.assertIsNone(self.engine.current())

    def test_set_queue_default_start_is_zero(self):
        self.engine.set_queue([fake_track("a"), fake_track("b")])
        self.assertEqual(self.engine.index, 0)

    # ---------- play_next / play_last / add_to_queue ----------
    def test_play_next_inserts_after_current(self):
        self.engine.set_queue([fake_track("a"), fake_track("c")], 0)
        self.engine.play_next(fake_track("b"))
        self.assertEqual(_titles(self.engine), ["a", "b", "c"])
        self.assertEqual(self.engine.index, 0, "current track is unchanged")
        self.assertEqual(self.engine.current().title, "a")

    def test_play_next_on_empty_queue_starts_at_zero(self):
        self.engine.play_next(fake_track("only"))
        self.assertEqual(_titles(self.engine), ["only"])
        self.assertEqual(self.engine.index, 0)

    def test_play_last_appends_at_the_end(self):
        self.engine.set_queue([fake_track("a"), fake_track("b")], 0)
        self.engine.play_last(fake_track("z"))
        self.assertEqual(_titles(self.engine), ["a", "b", "z"])
        self.assertEqual(self.engine.index, 0)

    def test_play_last_on_empty_queue_starts_at_zero(self):
        self.engine.play_last(fake_track("only"))
        self.assertEqual(_titles(self.engine), ["only"])
        self.assertEqual(self.engine.index, 0)

    def test_unplayable_tracks_are_never_queued(self):
        self.engine.set_queue([fake_track("a")], 0)
        bad = fake_track("bad", playable=False)
        self.engine.play_next(bad)
        self.engine.play_last(bad)
        self.engine.add_to_queue(bad)
        self.assertEqual(_titles(self.engine), ["a"])
        self.assertEqual(self.engine.index, 0)

    def test_add_to_queue_appends(self):
        self.engine.set_queue([fake_track("a")], 0)
        self.engine.add_to_queue(fake_track("b"))
        self.assertEqual(_titles(self.engine), ["a", "b"])

    def test_queue_mutation_does_not_start_playback(self):
        self.engine.set_queue([fake_track("a")], 0)
        self.engine.play_next(fake_track("b"))
        self.engine.play_last(fake_track("c"))
        self.assertFalse(self.engine.playing)
        self.assertEqual(self.engine.position(), 0.0)
        self.assertEqual(self.engine.duration(), 0.0)

    # ---------- remove_from_queue ----------
    def test_remove_before_current_shifts_index(self):
        self.engine.set_queue([fake_track("a"), fake_track("b"), fake_track("c")], 2)
        self.assertTrue(self.engine.remove_from_queue(0))
        self.assertEqual(_titles(self.engine), ["b", "c"])
        self.assertEqual(self.engine.index, 1)
        self.assertEqual(self.engine.current().title, "c")

    def test_remove_after_current_keeps_index(self):
        self.engine.set_queue([fake_track("a"), fake_track("b"), fake_track("c")], 0)
        self.assertTrue(self.engine.remove_from_queue(2))
        self.assertEqual(self.engine.index, 0)
        self.assertEqual(self.engine.current().title, "a")

    def test_remove_current_last_item_clamps_back(self):
        self.engine.set_queue([fake_track("a"), fake_track("b")], 1)
        self.assertTrue(self.engine.remove_from_queue(1))
        self.assertEqual(_titles(self.engine), ["a"])
        self.assertEqual(self.engine.index, 0)

    def test_remove_last_remaining_resets_index(self):
        self.engine.set_queue([fake_track("a")], 0)
        self.assertTrue(self.engine.remove_from_queue(0))
        self.assertEqual(self.engine.queue, [])
        self.assertEqual(self.engine.index, -1)

    def test_remove_out_of_range_returns_false(self):
        self.engine.set_queue([fake_track("a")], 0)
        self.assertFalse(self.engine.remove_from_queue(5))
        self.assertFalse(self.engine.remove_from_queue(-1))
        self.assertEqual(_titles(self.engine), ["a"])

    # ---------- move_in_queue ----------
    def test_move_forward_tracks_current(self):
        self.engine.set_queue([fake_track("a"), fake_track("b"), fake_track("c")], 0)
        self.assertTrue(self.engine.move_in_queue(0, 2))
        self.assertEqual(_titles(self.engine), ["b", "c", "a"])
        self.assertEqual(self.engine.index, 2)
        self.assertEqual(self.engine.current().title, "a")

    def test_move_backward_tracks_current(self):
        self.engine.set_queue([fake_track("a"), fake_track("b"), fake_track("c")], 2)
        self.assertTrue(self.engine.move_in_queue(2, 0))
        self.assertEqual(_titles(self.engine), ["c", "a", "b"])
        self.assertEqual(self.engine.index, 0)
        self.assertEqual(self.engine.current().title, "c")

    def test_move_across_current_keeps_same_track_playing(self):
        self.engine.set_queue([fake_track("a"), fake_track("b"), fake_track("c")], 1)
        self.assertTrue(self.engine.move_in_queue(0, 2))
        self.assertEqual(_titles(self.engine), ["b", "c", "a"])
        self.assertEqual(self.engine.index, 0)
        self.assertEqual(self.engine.current().title, "b")

    def test_move_to_same_index_is_a_noop(self):
        self.engine.set_queue([fake_track("a"), fake_track("b")], 0)
        self.assertTrue(self.engine.move_in_queue(1, 1))
        self.assertEqual(_titles(self.engine), ["a", "b"])
        self.assertEqual(self.engine.index, 0)

    def test_move_out_of_range_returns_false(self):
        self.engine.set_queue([fake_track("a"), fake_track("b")], 0)
        self.assertFalse(self.engine.move_in_queue(0, 7))
        self.assertFalse(self.engine.move_in_queue(-1, 0))
        self.assertFalse(self.engine.move_in_queue(5, 0))
        self.assertEqual(_titles(self.engine), ["a", "b"])

    # ---------- clear_queue ----------
    def test_clear_queue_empties_everything(self):
        self.engine.set_queue([fake_track("a"), fake_track("b")], 1)
        self.engine.clear_queue()
        self.assertEqual(self.engine.queue, [])
        self.assertEqual(self.engine.index, -1)
        self.assertIsNone(self.engine.current())

    def test_clear_queue_keep_current_keeps_one_track(self):
        self.engine.set_queue([fake_track("a"), fake_track("b"), fake_track("c")], 1)
        self.engine.clear_queue(keep_current=True)
        self.assertEqual(_titles(self.engine), ["b"])
        self.assertEqual(self.engine.index, 0)
        self.assertEqual(self.engine.current().title, "b")

    def test_clear_queue_keep_current_on_empty_queue_is_a_noop(self):
        self.engine.set_queue([], 0)
        self.engine.clear_queue(keep_current=True)
        self.assertEqual(self.engine.queue, [])
        self.assertEqual(self.engine.index, -1)

    # ---------- misc queue-adjacent state ----------
    def test_repeat_and_shuffle_flags_are_plain_state(self):
        self.engine.set_queue([fake_track("a"), fake_track("b")], 0)
        self.assertEqual(self.engine.repeat_mode(), "off")
        self.assertEqual(self.engine.toggle_repeat(), "all")
        self.assertEqual(self.engine.toggle_repeat(), "one")
        self.assertEqual(self.engine.toggle_repeat(), "off")
        self.engine.set_repeat_mode("one")
        self.assertEqual(self.engine.repeat_mode(), "one")
        self.assertTrue(self.engine.toggle_shuffle())
        self.engine.set_shuffle(False)
        self.assertFalse(self.engine.shuffle)
        self.engine.set_volume(2.0)
        self.assertAlmostEqual(self.engine.volume, 1.0, places=3)
        self.engine.set_volume(-1.0)
        self.assertAlmostEqual(self.engine.volume, 0.0, places=3)

    def test_current_is_none_when_index_out_of_range(self):
        self.engine.set_queue([fake_track("a")], 0)
        self.engine.index = 7
        self.assertIsNone(self.engine.current())
        self.engine.index = -1
        self.assertIsNone(self.engine.current())


if __name__ == "__main__":
    unittest.main()