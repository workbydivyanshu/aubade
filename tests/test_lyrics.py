"""lyrics.py — LRC parsing, synced detection, line lookup, local resolution.

Headless and offline: only the local chain (embedded -> .lrc sidecar -> DB
cache) is exercised. fetch_network is patched out wherever it is reachable.

    /usr/bin/python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402  must precede aubade imports (path + XDG sandbox)
from _support import TempDirTestCase  # noqa: E402

from aubade import lyrics  # noqa: E402
from aubade.lyrics import (current_line, is_synced, parse_lrc,  # noqa: E402
                           read_embedded, read_sidecar, resolve, resolve_local)

LRC = """[ar:Test Artist]
[ti:Test Title]
[00:00.00]Intro line
[00:05.50]Second line
[00:12.34]Third line
[01:02.345]Fourth line
"""


class IsSyncedTest(unittest.TestCase):
    def test_two_and_three_digit_milliseconds_are_synced(self):
        self.assertTrue(is_synced("[00:01.23]hi"))
        self.assertTrue(is_synced("[00:01.234]hi"))
        self.assertTrue(is_synced("[12:34.56]hi"))
        self.assertTrue(is_synced("plain\n[00:00.00]first stamp\n"))

    def test_static_and_empty_text_are_not_synced(self):
        self.assertFalse(is_synced(""))
        self.assertFalse(is_synced("Just a plain lyric sheet\nno stamps"))
        self.assertFalse(is_synced("[ar:Artist]"))
        self.assertFalse(is_synced("[00:01.5]hi"),
                         "1-digit ms does not match the LRC grammar")


class ParseLrcTest(unittest.TestCase):
    def test_full_document(self):
        lines = parse_lrc(LRC)
        self.assertEqual([words for _, words in lines],
                         ["Intro line", "Second line", "Third line", "Fourth line"])

    def test_timestamp_math_for_two_and_three_digit_ms(self):
        stamps = parse_lrc(LRC)
        self.assertAlmostEqual(stamps[0][0], 0.0, places=4)
        self.assertAlmostEqual(stamps[1][0], 5.50, places=4)
        self.assertAlmostEqual(stamps[2][0], 12.34, places=4)
        self.assertAlmostEqual(stamps[3][0], 62.345, places=4)
        self.assertEqual(stamps[3][1], "Fourth line")

    def test_single_digit_seconds(self):
        self.assertEqual(parse_lrc("[00:9.50]nine"), [(9.5, "nine")])

    def test_metadata_and_noise_lines_are_skipped(self):
        text = "\n".join([
            "[ar:Artist]",
            "[al:Album]",
            "[length:03:21]",
            "[offset:+500]",
            "",
            "   ",
            "no timestamp at all",
            "[00:10.00]kept",
        ])
        self.assertEqual(parse_lrc(text), [(10.0, "kept")])

    def test_empty_text_after_timestamps_is_skipped(self):
        self.assertEqual(parse_lrc("[00:10.00]\n[00:20.00]words"), [(20.0, "words")])

    def test_metadata_before_a_timestamp_is_kept_in_the_words(self):
        # parse_lrc strips only timestamps, so an inline [ar:...] tag survives
        # into the line text. Documented current behaviour.
        self.assertEqual(parse_lrc("[ar:Artist][00:05.00]Real line"),
                         [(5.0, "[ar:Artist]Real line")])

    def test_repeated_timestamps_emit_one_entry_each(self):
        self.assertEqual(
            parse_lrc("[00:01.00][00:02.00]Chorus"),
            [(1.0, "Chorus"), (2.0, "Chorus")])

    def test_output_is_sorted_by_time(self):
        text = "[00:30.00]late\n[00:10.00]early\n[00:20.00]middle"
        self.assertEqual([w for _, w in parse_lrc(text)],
                         ["early", "middle", "late"])

    def test_empty_input(self):
        self.assertEqual(parse_lrc(""), [])
        self.assertEqual(parse_lrc(None), [])


class CurrentLineTest(unittest.TestCase):
    def setUp(self):
        self.lines = [(0.0, "a"), (10.0, "b"), (20.0, "c"), (30.0, "d")]

    def test_boundaries(self):
        self.assertEqual(current_line(self.lines, 0.0), 0)
        self.assertEqual(current_line(self.lines, 9.999), 0)
        self.assertEqual(current_line(self.lines, 10.0), 1)
        self.assertEqual(current_line(self.lines, 19.5), 1)
        self.assertEqual(current_line(self.lines, 999.0), 3, "clamps to the last")

    def test_before_the_first_stamp(self):
        self.assertEqual(current_line([(5.0, "a"), (9.0, "b")], 1.0), -1)
        self.assertEqual(current_line([], 1.0), -1)

    def test_offset_shifts_the_lookup_point(self):
        self.assertEqual(current_line(self.lines, 9.9, offset=0.2), 1)
        self.assertEqual(current_line(self.lines, 10.0, offset=-1.0), 0)
        self.assertEqual(current_line(self.lines, 0.0, offset=-5.0), -1)

    def test_works_on_parsed_lrc(self):
        lines = parse_lrc(LRC)
        self.assertEqual(current_line(lines, 0.0), 0)
        self.assertEqual(current_line(lines, 5.5), 1)
        self.assertEqual(current_line(lines, 62.3), 2)
        self.assertEqual(current_line(lines, 62.4), 3)
        self.assertEqual(lines[current_line(lines, 12.4)][1], "Third line")


class SidecarTest(TempDirTestCase):
    def test_reads_synced_lrc_next_to_the_track(self):
        audio = os.path.join(self.tmpdir(), "song.wav")
        sidecar = os.path.splitext(audio)[0] + ".lrc"
        with open(sidecar, "w", encoding="utf-8") as handle:
            handle.write(LRC)
        self.assertEqual(read_sidecar(audio), LRC)
        self.assertEqual(len(parse_lrc(read_sidecar(audio))), 4)

    def test_uppercase_sidecar_is_found(self):
        audio = os.path.join(self.tmpdir(), "song.wav")
        with open(os.path.splitext(audio)[0] + ".LRC", "w", encoding="utf-8") as h:
            h.write("[00:03.00]Upper")
        self.assertEqual(read_sidecar(audio), "[00:03.00]Upper")

    def test_missing_and_unsynced_sidecars_return_empty(self):
        audio = os.path.join(self.tmpdir(), "song.wav")
        self.assertEqual(read_sidecar(audio), "")
        with open(os.path.splitext(audio)[0] + ".lrc", "w", encoding="utf-8") as h:
            h.write("just words, no stamps\n")
        self.assertEqual(read_sidecar(audio), "")

    def test_read_embedded_missing_file(self):
        self.assertEqual(read_embedded(os.path.join(self.tmpdir(), "gone.mp3")),
                         ("", ""))


class ResolveChainTest(TempDirTestCase):
    """Local resolution order, offline. Store is a throwaway DB."""

    def setUp(self):
        super().setUp()
        self.store = self.new_store()
        self.audio = os.path.join(self.tmpdir(), "song.wav")

    def test_nothing_found(self):
        self.assertEqual(resolve_local(self.audio, self.store), ("", "", False))

    def test_embedded_synced_wins_over_everything(self):
        _support.add_track(self.store, self.audio, "Song", synced="[00:01.00]emb")
        self.store.save_lyrics(self.audio, "cached", "[00:02.00]cached")
        static, synced, found = resolve_local(self.audio, self.store)
        self.assertTrue(found)
        self.assertEqual((static, synced), ("", "[00:01.00]emb"))

    def test_sidecar_beats_cache(self):
        with open(os.path.splitext(self.audio)[0] + ".lrc", "w",
                  encoding="utf-8") as handle:
            handle.write("[00:05.00]sidecar")
        self.store.save_lyrics(self.audio, "cached", "[00:02.00]cached")
        self.assertEqual(resolve_local(self.audio, self.store),
                         ("", "[00:05.00]sidecar", True))

    def test_cache_used_when_no_embedded_or_sidecar(self):
        self.store.save_lyrics(self.audio, "cached static", "[00:02.00]cached")
        self.assertEqual(resolve_local(self.audio, self.store),
                         ("cached static", "[00:02.00]cached", True))

    def test_embedded_static_is_the_last_local_resort(self):
        _support.add_track(self.store, self.audio, "Song", lyrics="plain words")
        self.assertEqual(resolve_local(self.audio, self.store),
                         ("plain words", "", True))

    def test_resolve_fetches_once_then_reads_the_cache(self):
        with mock.patch.object(lyrics, "fetch_network",
                               return_value=("net words", "")) as fetch:
            self.assertEqual(resolve(self.audio, "A", "T", self.store),
                             ("net words", ""))
            fetch.assert_called_once_with("A", "T")
        # Second call is served from SQLite, no further network access.
        with mock.patch.object(lyrics, "fetch_network",
                               side_effect=AssertionError("network used")):
            self.assertEqual(resolve(self.audio, "A", "T", self.store),
                             ("net words", ""))

    def test_resolve_network_miss_is_cached_as_empty(self):
        with mock.patch.object(lyrics, "fetch_network", return_value=("", "")):
            self.assertEqual(resolve(self.audio, "A", "T", self.store), ("", ""))
        self.assertEqual(self.store.cached_lyrics(self.audio), ("", ""))


if __name__ == "__main__":
    unittest.main()