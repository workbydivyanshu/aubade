"""GStreamer audio engine: gapless queue, shuffle/repeat, seek/volume.

Uses playbin + 'about-to-finish' for gapless handoff. All callbacks are
invoked on the GLib main thread (bus signal watch).
"""
from __future__ import annotations

import random
import threading
from typing import Callable

from gi.repository import GLib, Gst

from .library import Track


class Engine:
    def __init__(self) -> None:
        self.pipe = Gst.ElementFactory.make("playbin", "aubade")
        if self.pipe is None:
            raise RuntimeError("GStreamer playbin unavailable")
        self.pipe.set_property("volume", 0.8)

        self.queue: list[Track] = []
        self.index: int = -1
        self.shuffle: bool = False
        self.repeat_all: bool = False
        self.repeat_one: bool = False
        self.playing: bool = False
        self.loaded = False  # a track is loaded in the pipeline

        self.on_track: Callable[[Track | None, bool], None] | None = None
        self.on_queue: Callable[[], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self._last_emit: tuple | None = None
        self._main_tid = threading.get_ident()
        self._queue_idle = 0

        self.pipe.connect("about-to-finish", self._on_about_to_finish)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::error", self._on_bus_error)

    # ---------- queue ----------
    def set_queue(self, tracks: list[Track], start: int = 0) -> None:
        self.queue = [t for t in tracks if t.playable]
        self.index = start if self.queue else -1
        self._notify_queue()

    def _notify_queue(self) -> None:
        """Tell the owner the queue/index changed. Listeners (persistence) run
        on the main thread only, so calls from the GStreamer streaming thread
        are marshalled through a single coalesced idle."""
        if threading.get_ident() != self._main_tid:
            if not self._queue_idle:
                self._queue_idle = GLib.idle_add(self._flush_queue)
            return
        self._emit_queue()

    def _flush_queue(self) -> bool:
        self._queue_idle = 0
        self._emit_queue()
        return False

    def _emit_queue(self) -> None:
        if self.on_queue is not None:
            self.on_queue()

    def current(self) -> Track | None:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    def _pick_next(self) -> int:
        if not self.queue:
            return -1
        if self.shuffle and len(self.queue) > 1:
            nxt = self.index
            while nxt == self.index:
                nxt = random.randrange(len(self.queue))
            return nxt
        nxt = self.index + 1
        if nxt >= len(self.queue):
            return 0 if self.repeat_all else -1
        return nxt

    def _pick_prev(self) -> int:
        if not self.queue:
            return -1
        if self.position() > 3.0 and self.playing:
            return self.index  # restart track
        if self.shuffle and len(self.queue) > 1:
            return random.randrange(len(self.queue))
        prv = self.index - 1
        if prv < 0:
            return len(self.queue) - 1 if self.repeat_all else 0
        return prv

    # ---------- transport ----------
    def _load(self, i: int) -> bool:
        track = self.queue[i] if 0 <= i < len(self.queue) else None
        if track is None:
            return False
        self.index = i
        self.pipe.set_property("uri", track.uri)
        self.loaded = True
        self._notify_queue()
        return True

    def play_index(self, i: int) -> None:
        if self._load(i):
            self.pipe.set_state(Gst.State.PLAYING)
            self.playing = True
            self._emit()

    def play(self) -> None:
        if self.index < 0 and self.queue:
            self.play_index(0)
            return
        # a restored queue has an index but nothing loaded in the pipeline
        if not self.loaded:
            self.play_index(self.index)
            return
        self.pipe.set_state(Gst.State.PLAYING)
        self.playing = True
        self._emit()

    def pause(self) -> None:
        self.pipe.set_state(Gst.State.PAUSED)
        self.playing = False
        self._emit()

    def toggle(self) -> None:
        if self.playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self.pipe.set_state(Gst.State.NULL)
        self.playing = False
        self.loaded = False
        self._emit()

    def shutdown(self) -> None:
        """Tear down the pipeline first so no GStreamer callback can fire
        into interpreter shutdown (about-to-finish runs on the streaming
        thread and would otherwise invoke Python during finalization)."""
        try:
            self.pipe.get_bus().remove_signal_watch()
        except Exception:
            pass
        try:
            self.pipe.set_state(Gst.State.NULL)
        except Exception:
            pass
        self.playing = False
        self.loaded = False
        self.on_queue = None
        self.on_track = None

    def next(self, auto: bool = False) -> None:
        nxt = self._pick_next()
        if nxt < 0:
            if not auto:
                self.stop()
            return
        if auto:
            # gapless path already set the URI; just sync index
            self.index = nxt
            self._notify_queue()
            self._emit()
        else:
            self.play_index(nxt)

    def prev(self) -> None:
        prv = self._pick_prev()
        if prv == self.index and self.position() > 3.0:
            self.seek_sec(0)
            return
        self.play_index(prv)

    # ---------- modes ----------
    def toggle_shuffle(self) -> bool:
        self.shuffle = not self.shuffle
        return self.shuffle

    def toggle_repeat(self) -> str:
        """Cycle off -> all -> one -> off. Returns mode."""
        if not self.repeat_all and not self.repeat_one:
            self.repeat_all = True
        elif self.repeat_all:
            self.repeat_all, self.repeat_one = False, True
        else:
            self.repeat_one = False
        return self.repeat_mode()

    def repeat_mode(self) -> str:
        if self.repeat_one:
            return "one"
        return "all" if self.repeat_all else "off"

    def set_repeat_mode(self, mode: str) -> None:
        self.repeat_all = mode == "all"
        self.repeat_one = mode == "one"

    # ---------- seek / volume ----------
    def seek_frac(self, frac: float) -> None:
        dur = self.duration()
        if dur > 0:
            self.seek_sec(max(0.0, min(1.0, frac)) * dur)

    def seek_sec(self, sec: float) -> None:
        self.pipe.seek_simple(
            Gst.Format.TIME, Gst.SeekFlags.FLUSH, int(sec * Gst.SECOND)
        )

    def position(self) -> float:
        ok, pos = self.pipe.query_position(Gst.Format.TIME)
        return pos / Gst.SECOND if ok else 0.0

    def duration(self) -> float:
        ok, dur = self.pipe.query_duration(Gst.Format.TIME)
        if (not ok or dur <= 0) and (t := self.current()) and t.length > 0:
            return t.length
        return dur / Gst.SECOND if ok and dur > 0 else 0.0

    def set_volume(self, v: float) -> None:
        self.pipe.set_property("volume", max(0.0, min(1.0, v)))

    @property
    def volume(self) -> float:
        return self.pipe.get_property("volume")

    def set_shuffle(self, on: bool) -> None:
        self.shuffle = on

    # ---------- queue management ----------
    def add_to_queue(self, track: Track) -> None:
        """Append track to the end of the queue."""
        if track.playable:
            self.queue.append(track)
            if self.index == -1:
                self.index = 0
            self._notify_queue()

    def play_next(self, track: Track) -> None:
        """Insert track immediately after the current track."""
        if not track.playable:
            return
        insert_at = self.index + 1 if self.index >= 0 else 0
        self.queue.insert(insert_at, track)
        if self.index == -1:
            self.index = 0
        self._notify_queue()

    def play_last(self, track: Track) -> None:
        """Insert track at the end of the queue (before any repeat-one loop)."""
        if not track.playable:
            return
        self.queue.append(track)
        if self.index == -1:
            self.index = 0
        self._notify_queue()

    def remove_from_queue(self, index: int) -> bool:
        """Remove track at index. Returns True if removed."""
        if 0 <= index < len(self.queue):
            # Adjust current index if we removed before or at current
            if index < self.index:
                self.index -= 1
            elif index == self.index and self.index >= len(self.queue) - 1:
                self.index = max(0, self.index - 1)
            self.queue.pop(index)
            if not self.queue:
                self.index = -1
            self._notify_queue()
            return True
        return False

    def move_in_queue(self, from_index: int, to_index: int) -> bool:
        """Move track from from_index to to_index. Returns True on success."""
        if not (0 <= from_index < len(self.queue)) or not (0 <= to_index < len(self.queue)):
            return False
        if from_index == to_index:
            return True
        track = self.queue.pop(from_index)
        self.queue.insert(to_index, track)
        # Adjust current index
        if from_index == self.index:
            self.index = to_index
        elif from_index < self.index <= to_index:
            self.index -= 1
        elif to_index <= self.index < from_index:
            self.index += 1
        self._notify_queue()
        return True

    def clear_queue(self, keep_current: bool = False) -> None:
        """Clear the queue. If keep_current, keep the currently playing track."""
        if keep_current and self.index >= 0 and self.index < len(self.queue):
            current = self.queue[self.index]
            self.queue = [current]
            self.index = 0
        else:
            self.queue.clear()
            self.index = -1
        self._notify_queue()

    # ---------- internals ----------
    def _on_about_to_finish(self, _pipe) -> None:
        # Runs on GStreamer's streaming thread: touch only the pipeline
        # here, marshal everything UI-facing to the main thread, and only
        # when the state actually changed (some backends spam this signal,
        # which would otherwise flood the main loop with no-op idles).
        if self.repeat_one and (t := self.current()):
            self.pipe.set_property("uri", t.uri)
            self.loaded = True
            return
        nxt = self._pick_next()
        if nxt >= 0:
            self.index = nxt
            self.pipe.set_property("uri", self.queue[nxt].uri)
            self.loaded = True
            self.playing = True
            self._notify_queue()
            cur = self.queue[nxt]
            if ((cur.path, True) != self._last_emit
                    and self.on_track is not None):
                GLib.idle_add(self._emit)

    def _on_eos(self, _bus, _msg) -> None:
        if self.repeat_one:
            self.seek_sec(0)
            self.play()
            return
        nxt = self._pick_next()
        if nxt >= 0 and nxt != self.index:
            self.play_index(nxt)
        else:
            self.stop()

    def _on_bus_error(self, _bus, msg) -> None:
        err, _dbg = msg.parse_error()
        self.playing = False
        self.pipe.set_state(Gst.State.NULL)
        self._emit()
        if self.on_error:
            self.on_error(str(err))

    def _emit(self) -> None:
        if self.on_track is None:
            return
        cur = self.current()
        key = ((cur.path if cur else None), self.playing)
        if key == self._last_emit:
            return
        self._last_emit = key
        self.on_track(cur, self.playing)
