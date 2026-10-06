"""Aubade — Now Playing full-screen sheet."""
from __future__ import annotations

import gi
import threading
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango
from ..types import Track, thumb_for
from ..lyrics import parse_lrc, current_line, resolve

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ui import AubadeWindow


def _fmt(sec: float) -> str:
    if sec is None or sec != sec or sec < 0:
        return "0:00"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _fmt_remain(sec: float) -> str:
    sec = max(0, int(sec or 0))
    return f"-{sec // 60}:{sec % 60:02d}"


class NowPlayingSheet(Gtk.Box):
    """Full-screen now playing sheet with lyrics, queue, and related tabs."""

    def __init__(self, window: "AubadeWindow") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("np")
        self._window = window
        self._np_built = True
        self._np_seeking = False
        self._np_token = 0
        self._np_track_path: str | None = None
        self._np_lines: list = []
        self._np_labels: list = []
        self._np_line_idx = -2
        self._active_tab = "lyrics"
        self._build()

    def _build(self) -> None:
        self.set_margin_top(12)
        self.set_margin_bottom(20)
        self.set_margin_start(28)
        self.set_margin_end(28)

        # Header with back button
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        back = Gtk.Button.new_from_icon_name("go-down")
        back.add_css_class("icobtn")
        back.set_tooltip_text("Back (Esc)")
        back.connect("clicked", lambda _b: self._window._close_nowplaying())
        top.append(back)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        center.set_hexpand(True)
        center.set_halign(Gtk.Align.CENTER)
        cap = Gtk.Label(label="NOW PLAYING")
        cap.add_css_class("np-caption")
        self.np_top_title = Gtk.Label(label="")
        self.np_top_title.add_css_class("np-title")
        center.append(cap)
        center.append(self.np_top_title)
        top.append(center)

        dots = Gtk.Button.new_from_icon_name("view-more")
        dots.add_css_class("icobtn")
        dots.set_tooltip_text("Up next")
        dots.connect("clicked", self._window._open_queue)
        top.append(dots)
        self.append(top)

        # Main content
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=48)
        content.set_hexpand(True)
        content.set_vexpand(True)
        content.set_halign(Gtk.Align.FILL)
        self.append(content)

        # Left: artwork + track info + transport
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left.set_size_request(440, -1)
        self.np_art = Gtk.Picture()
        self.np_art.set_size_request(440, 440)
        self.np_art.set_content_fit(Gtk.ContentFit.COVER)
        self.np_art.add_css_class("np-art")
        left.append(self.np_art)

        self.np_song = Gtk.Label(label="", xalign=0)
        self.np_song.add_css_class("np-song")
        self.np_song.set_ellipsize(Pango.EllipsizeMode.END)
        left.append(self.np_song)

        self.np_sub = Gtk.Label(label="", xalign=0)
        self.np_sub.add_css_class("np-artist")
        self.np_sub.set_ellipsize(Pango.EllipsizeMode.END)
        left.append(self.np_sub)

        # Actions
        acts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        acts.set_halign(Gtk.Align.END)
        np_share = Gtk.Button.new_from_icon_name(self._best_share_icon())
        np_share.add_css_class("icobtn")
        np_share.connect("clicked", self._on_share)
        self.np_like = Gtk.ToggleButton(label="♡")
        self.np_like.add_css_class("icobtn")
        self.np_like.connect("toggled", self._on_like)
        acts.append(np_share)
        acts.append(self.np_like)
        left.append(acts)

        # Seek
        self.np_seek = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 1000, 1)
        self.np_seek.set_draw_value(False)
        self.np_seek.add_css_class("seek")
        self.np_seek.connect("value-changed", self._on_np_seek)
        np_gc = Gtk.GestureClick(button=1)
        np_gc.connect("pressed", self._on_np_seek_press)
        np_gc.connect("released",
                      lambda *_a: setattr(self, "_np_seeking", False))
        self.np_seek.add_controller(np_gc)
        left.append(self.np_seek)

        # Time
        timerow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.np_cur = Gtk.Label(label="0:00", xalign=0)
        self.np_cur.set_hexpand(True)
        self.np_rem = Gtk.Label(label="-0:00", xalign=1)
        timerow.append(self.np_cur)
        timerow.append(self.np_rem)
        left.append(timerow)

        # Transport
        trans = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        trans.set_halign(Gtk.Align.CENTER)
        self.np_shuffle = Gtk.ToggleButton()
        self.np_shuffle.set_icon_name("media-playlist-shuffle")
        self._sized_icon(self.np_shuffle, 22)
        self.np_shuffle.add_css_class("icobtn")
        self.np_shuffle.connect("toggled", self._on_shuffle)
        self.np_prev = self._sized_icon(
            Gtk.Button.new_from_icon_name("media-skip-backward"), 26)
        self.np_prev.add_css_class("icobtn")
        self.np_prev.connect("clicked", self._on_prev)
        self.np_play = self._sized_icon(
            Gtk.Button.new_from_icon_name("media-playback-start"), 34)
        self.np_play.add_css_class("btn-main")
        self.np_play.add_css_class("np-big")
        self.np_play.connect("clicked", lambda _b: self._window.engine.toggle())
        self.np_next = self._sized_icon(
            Gtk.Button.new_from_icon_name("media-skip-forward"), 26)
        self.np_next.add_css_class("icobtn")
        self.np_next.connect("clicked", self._on_next)
        self.np_repeat = Gtk.ToggleButton()
        self.np_repeat.set_icon_name("media-playlist-repeat")
        self._sized_icon(self.np_repeat, 22)
        self.np_repeat.add_css_class("icobtn")
        self.np_repeat.connect("clicked", self._on_repeat)
        for w in (self.np_shuffle, self.np_prev, self.np_play,
                  self.np_next, self.np_repeat):
            trans.append(w)
        left.append(trans)

        # Volume
        devrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dev_lbl = Gtk.Label(label="This device", xalign=0)
        dev_lbl.add_css_class("np-device")
        dev_lbl.set_hexpand(True)
        devrow.append(dev_lbl)
        self.np_vol = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.np_vol.set_draw_value(False)
        self.np_vol.set_size_request(110, -1)
        self.np_vol.add_css_class("vol")
        self.np_vol.set_value(
            float(self._window.engine.pipe.get_property("volume")) * 100.0)
        self.np_vol.connect("value-changed",
                            lambda s: self._window._set_volume(s.get_value() / 100.0))
        devrow.append(self.np_vol)
        np_queue = Gtk.Button.new_from_icon_name("view-list")
        np_queue.add_css_class("icobtn")
        np_queue.connect("clicked", self._window._open_queue)
        devrow.append(np_queue)
        left.append(devrow)
        content.append(left)

        # Right: lyrics + queue + related tabs
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right.set_hexpand(True)
        right.set_size_request(380, -1)

        # Tab bar
        self.tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.tab_box.set_halign(Gtk.Align.END)
        self._build_tabs()
        right.append(self.tab_box)

        # Lyrics scroll
        self.np_scroll = Gtk.ScrolledWindow()
        self.np_scroll.set_hexpand(True)
        self.np_scroll.set_vexpand(True)
        self.np_scroll.set_policy(Gtk.PolicyType.NEVER,
                                  Gtk.PolicyType.AUTOMATIC)
        self.np_lyrbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                 spacing=18)
        self.np_lyrbox.set_margin_top(24)
        self.np_lyrbox.set_hexpand(True)
        self.np_scroll.set_child(self.np_lyrbox)
        right.append(self.np_scroll)

        # Queue panel (initially hidden)
        self.queue_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.queue_box.set_hexpand(True)
        self.queue_box.set_vexpand(True)
        self.queue_box.set_visible(False)
        right.append(self.queue_box)

        # Related panel (initially hidden)
        self.related_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.related_box.set_hexpand(True)
        self.related_box.set_vexpand(True)
        self.related_box.set_visible(False)
        right.append(self.related_box)

        content.append(right)

        # Sync offset controls
        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tools.set_halign(Gtk.Align.END)
        sync_minus = Gtk.Button(label="−")
        sync_minus.add_css_class("icobtn")
        sync_minus.set_tooltip_text("Lyrics earlier")
        sync_minus.connect("clicked", self._on_sync_shift, -0.5)
        self.np_sync_label = Gtk.Label(label="Sync")
        self.np_sync_label.add_css_class("np-sync")
        sync_plus = Gtk.Button(label="+")
        sync_plus.add_css_class("icobtn")
        sync_plus.set_tooltip_text("Lyrics later")
        sync_plus.connect("clicked", self._on_sync_shift, 0.5)
        tools.append(sync_minus)
        tools.append(self.np_sync_label)
        tools.append(sync_plus)
        # Insert at top of right
        right.insert_child_after(tools, self.tab_box)

    def _best_share_icon(self) -> str:
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for name in ("document-send", "mail-send", "edit-copy", "emblem-shared"):
            if theme is not None and theme.has_icon(name):
                return name
        return "edit-copy"

    def _build_tabs(self) -> None:
        self.tab_btns = {}
        for tab_id, label in (("lyrics", "Lyrics"), ("queue", "Queue"), ("related", "Related")):
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("np-tab")
            btn.set_active(tab_id == self._active_tab)
            btn.connect("toggled", self._on_tab, tab_id)
            self.tab_box.append(btn)
            self.tab_btns[tab_id] = btn

    def _on_tab(self, btn: Gtk.ToggleButton, tab_id: str) -> None:
        if not btn.get_active():
            btn.set_active(True)
            return
        self._active_tab = tab_id
        self.np_scroll.set_visible(tab_id == "lyrics")
        self.queue_box.set_visible(tab_id == "queue")
        self.related_box.set_visible(tab_id == "related")
        if tab_id == "queue":
            self._refresh_queue_panel()
        elif tab_id == "related":
            self._refresh_related_panel()

    def _refresh_queue_panel(self) -> None:
        while (c := self.queue_box.get_first_child()):
            self.queue_box.remove(c)
        queue = self._window.engine.queue
        cur = self._window.engine.index
        if not queue:
            self.queue_box.append(Gtk.Label(label="Queue is empty"))
            return
        for i, t in enumerate(queue):
            row = Gtk.ListBoxRow()
            if i == cur:
                row.add_css_class("playing")
            h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            idx = Gtk.Label(label=f"{i + 1:02d}")
            idx.set_size_request(34, -1)
            idx.add_css_class("idx")
            title = Gtk.Label(label=t.title, xalign=0)
            title.set_hexpand(True)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            artist = Gtk.Label(label=t.artist, xalign=0)
            artist.set_size_request(150, -1)
            artist.set_ellipsize(Pango.EllipsizeMode.END)
            for w in (idx, title, artist):
                h.append(w)
            row.set_child(h)
            self.queue_box.append(row)

    def _refresh_related_panel(self) -> None:
        while (c := self.related_box.get_first_child()):
            self.related_box.remove(c)
        # TODO: implement related artists/tracks from local library
        self.related_box.append(Gtk.Label(label="Related tracks coming soon"))
        self.related_box.get_last_child().add_css_class("np-empty")

    def _on_share(self, _btn: Gtk.Button) -> None:
        cur = self._window.engine.current()
        if cur is None:
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set_text(f"{cur.title} — {cur.artist}")
        self._window.toast.add_toast(Adw.Toast(title="Copied to clipboard"))

    def _on_like(self, btn: Gtk.ToggleButton) -> None:
        if self._window._in_like_sync:
            return
        cur = self._window.engine.current()
        if cur is None or not cur.path:
            btn.set_active(False)
            return
        self._window.store.set_like(cur.path, btn.get_active())
        if btn.get_active():
            self._window.liked.add(cur.path)
        else:
            self._window.liked.discard(cur.path)
        self._window._sync_like_buttons()

    def _on_prev(self, _btn: Gtk.Button) -> None:
        self._window._log_skip()
        self._window.engine.prev()

    def _on_next(self, _btn: Gtk.Button) -> None:
        self._window._log_skip()
        self._window.engine.next()

    def _on_shuffle(self, btn: Gtk.ToggleButton) -> None:
        self._window.engine.shuffle = btn.get_active()
        self._window.store.set_profile("shuffle", "1" if btn.get_active() else "0")
        self._window.mpris.update()
        self._window.playerbar.sync_transport()

    def _on_repeat(self, btn: Gtk.ToggleButton) -> None:
        self._window._on_repeat_np(btn)
        self._window.playerbar.sync_transport()

    def _on_sync_shift(self, _btn: Gtk.Button, delta: float) -> None:
        off = round(self._lyrics_offset() + delta, 1)
        self._window.store.set_profile("lyrics_offset", str(off))
        self.np_sync_label.set_text(f"Sync {off:+.1f}s")
        self._np_line_idx = -2  # force re-highlight

    def _on_np_seek(self, scale: Gtk.Scale) -> None:
        if self._np_seeking:
            self._window.engine.seek_frac(scale.get_value() / 1000.0)
            self._window.mpris.seeked()

    def _on_np_seek_press(self, _gesture, _n: int, x: float, _y: float) -> None:
        self._np_seeking = True
        frac = self._trough_frac(self.np_seek, x)
        self.np_seek.set_value(frac * 1000.0)
        self._window.engine.seek_frac(frac)
        self._window.mpris.seeked()

    def _trough_frac(self, scale: Gtk.Scale, x: float) -> float:
        rect = scale.get_range_rect()
        if rect.width <= 0:
            return 0.0
        return max(0.0, min(1.0, (x - rect.x) / rect.width))

    @staticmethod
    def _sized_icon(btn: Gtk.Button, px: int) -> Gtk.Button:
        child = btn.get_first_child()
        if isinstance(child, Gtk.Image):
            child.set_pixel_size(px)
        return btn

    # ---------- public API ----------
    def refresh(self) -> None:
        """Called when track changes or sheet is opened."""
        track = self._window.engine.current()
        if track is None or not track.path:
            self.np_top_title.set_text("")
            self.np_song.set_text("Nothing playing")
            self.np_sub.set_text("Pick a song from your library")
            self.np_art.set_paintable(None)
            self._set_lyrics([], "", None)
            return

        self.np_top_title.set_text(track.title)
        self.np_song.set_text(track.title)
        self.np_sub.set_text(f"{track.artist} · {track.album}")
        thumb = thumb_for(track.path, 600)
        if thumb:
            self.np_art.set_filename(thumb)
        else:
            self.np_art.set_paintable(None)

        if track.path == self._np_track_path:
            return

        self._np_token += 1
        token = self._np_token
        self._set_lyrics(None, None, track.path)

        # Load lyrics in background
        threading.Thread(target=self._load_lyrics_thread,
                         args=(track, token), daemon=True).start()

    def _load_lyrics_thread(self, track: Track, token: int) -> None:
        try:
            static, synced = resolve(track.path, track.artist,
                                     track.title, self._window.store)
        except Exception:
            static, synced = "", ""
        lines = parse_lrc(synced) if synced else []
        GLib.idle_add(self._fill_lyrics, lines, static, track.path, token)

    def _fill_lyrics(self, lines, static: str, path, token: int) -> bool:
        if token != self._np_token:
            return False
        self._set_lyrics(lines, static, path)
        return False

    def _set_lyrics(self, lines, static: str, path) -> None:
        while (c := self.np_lyrbox.get_first_child()):
            self.np_lyrbox.remove(c)
        self._np_lines = lines or []
        self._np_labels = []
        self._np_line_idx = -2
        self._np_track_path = path
        if self._np_lines:
            for _stamp, words in self._np_lines:
                lbl = Gtk.Label(label=words, xalign=0)
                lbl.set_wrap(True)
                lbl.set_hexpand(True)
                lbl.add_css_class("np-lyr")
                self.np_lyrbox.append(lbl)
                self._np_labels.append(lbl)
        elif static:
            lbl = Gtk.Label(label=static, xalign=0)
            lbl.set_wrap(True)
            lbl.set_hexpand(True)
            lbl.add_css_class("np-lyr")
            self.np_lyrbox.append(lbl)
        else:
            lbl = Gtk.Label(label="No lyrics found", xalign=0)
            lbl.add_css_class("np-empty")
            self.np_lyrbox.append(lbl)

    def _highlight_lyric(self, pos: float) -> None:
        if not self._np_lines:
            return
        idx = current_line(self._np_lines, pos, self._lyrics_offset())
        if idx == self._np_line_idx:
            return
        if 0 <= self._np_line_idx < len(self._np_labels):
            self._np_labels[self._np_line_idx].remove_css_class("np-lyr-cur")
        self._np_line_idx = idx
        if 0 <= idx < len(self._np_labels):
            lbl = self._np_labels[idx]
            lbl.add_css_class("np-lyr-cur")
            adj = self.np_scroll.get_vadjustment()
            y = lbl.get_allocation().y
            target = y - adj.get_page_size() / 2 + lbl.get_allocation().height / 2
            adj.set_value(max(0.0, min(target, adj.get_upper() - adj.get_page_size())))

    def tick(self) -> None:
        if not self._np_built or self._window.appstack.get_visible_child_name() != "np":
            return
        pos = self._window.engine.position()
        dur = self._window.engine.duration()
        self.np_cur.set_text(_fmt(pos))
        self.np_rem.set_text(_fmt_remain(dur - pos if dur else 0))
        if dur > 0 and not self._np_seeking:
            self.np_seek.set_value(pos / dur * 1000.0)
        self._highlight_lyric(pos)

    def _lyrics_offset(self) -> float:
        try:
            return float(self._window.store.get_profile("lyrics_offset", "0.0"))
        except ValueError:
            return 0.0