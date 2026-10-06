"""Aubade — right rail (tags, history, now playing card)."""
from __future__ import annotations

import hashlib

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from ..types import Track, thumb_for

def _ago(ts: float) -> str:
    import time
    d = max(0.0, time.time() - ts)
    if d < 60:
        return "just now"
    if d < 3600:
        m = int(d // 60)
        return f"{m} min ago"
    if d < 86400:
        h = int(d // 3600)
        return f"{h} hr ago"
    return f"{int(d // 86400)} d ago"

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ui import AubadeWindow






EMPTY_PLAYED = "Plays will appear here."
EMPTY_TAGS = "Genres from your files will appear here."


class RightRail(Gtk.Box):
    """Right rail with genre chips, recently played, and now-playing card."""

    def __init__(self, window: "AubadeWindow") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("rail")
        self.set_size_request(316, -1)
        self._window = window
        self._build()

    def _build(self) -> None:
        # Load folder button
        load = Gtk.Button(label="+ Load Music folder")
        load.add_css_class("loadbox")
        load.connect("clicked", self._window._pick_folder)
        self.append(load)

        # Tags / genres
        self.append(self._rail_head("LIBRARY", "Your Tags"))
        self.chips_flow = Gtk.FlowBox(homogeneous=False,
                                       selection_mode=Gtk.SelectionMode.NONE)
        self.chips_flow.set_max_children_per_line(2)
        self.append(self.chips_flow)

        # Recently played
        seeall = Gtk.Button(label="See all")
        seeall.add_css_class("flat")
        seeall.add_css_class("more")
        seeall.connect("clicked", self._on_history)
        played_head = self._rail_head("HISTORY", "Recently Played", seeall)
        self.append(played_head)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.played_box = Gtk.ListBox()
        self.played_box.add_css_class("played")
        scroll.set_child(self.played_box)
        self.append(scroll)

        # Now playing card
        now_head = self._rail_head("NOW PLAYING", "Current Track")
        self.append(now_head)
        self.nowcard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.nowcard.add_css_class("nowcard")
        self.nc_art = Gtk.Picture()
        self.nc_art.set_size_request(64, 64)
        self.nc_art.set_content_fit(Gtk.ContentFit.COVER)
        self.nc_art.add_css_class("bar-art")
        toprow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        toprow.append(self.nc_art)
        ntxt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        ntxt.set_hexpand(True)
        ntxt.set_valign(Gtk.Align.CENTER)
        self.nc_title = Gtk.Label(label="Nothing playing", xalign=0)
        self.nc_title.add_css_class("bar-title")
        self.nc_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.nc_artist = Gtk.Label(label="—", xalign=0)
        self.nc_artist.add_css_class("sub")
        self.nc_artist.set_ellipsize(Pango.EllipsizeMode.END)
        ntxt.append(self.nc_title)
        ntxt.append(self.nc_artist)
        toprow.append(ntxt)
        self.nowcard.append(toprow)
        nc_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.nc_play = Gtk.Button(label="▶  Play")
        self.nc_play.add_css_class("btn-play")
        self.nc_play.connect("clicked", lambda _b: self._play_from_nc())
        self.nc_save = Gtk.ToggleButton(label="Save  ♥")
        self.nc_save.add_css_class("btn-ghost")
        self.nc_save.connect("toggled", self._on_like)
        nc_btns.append(self.nc_play)
        nc_btns.append(self.nc_save)
        self.nowcard.append(nc_btns)
        self.append(self.nowcard)

        # Initial refresh
        self._refresh_tags()
        self._refresh_played()
        self._refresh_nowcard()

    def _rail_head(self, overline: str, title: str,
                    action: Gtk.Widget | None = None) -> Gtk.Widget:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        cap = Gtk.Label(label=overline, xalign=0)
        cap.add_css_class("overline")
        wrap.append(cap)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lbl = Gtk.Label(label=title, xalign=0)
        lbl.add_css_class("h-rail")
        lbl.set_hexpand(True)
        box.append(lbl)
        if action is not None:
            box.append(action)
        wrap.append(box)
        return wrap

    def _on_history(self, _btn: Gtk.Button) -> None:
        win = Gtk.Window(title="Play history", transient_for=self._window,
                         modal=True, default_width=420, default_height=500)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        box = Gtk.ListBox()
        box.add_css_class("tracks")
        plays = self._window.store.all_plays(200)
        if not plays:
            box.append(Gtk.Label(label=EMPTY_PLAYED))
        for p in plays:
            row = Gtk.ListBoxRow()
            h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            t = Gtk.Label(label=f"{p['title']} — {p['artist']}", xalign=0)
            t.set_hexpand(True)
            t.set_ellipsize(Pango.EllipsizeMode.END)
            h.append(t)
            sub = Gtk.Label(
                label=f"{p['times']}× · {_ago(p['ts'])}")
            sub.add_css_class("sub")
            h.append(sub)
            row.set_child(h)
            box.append(row)
        scroll.set_child(box)
        outer.append(scroll)
        clear = Gtk.Button(label="Clear history")
        clear.connect("clicked", self._clear_history, win)
        outer.append(clear)
        win.set_child(outer)
        win.present()

    def _clear_history(self, _btn: Gtk.Button, win: Gtk.Window) -> None:
        self._window.store.clear_plays()
        self._window._last_played_path = None
        self._refresh_played()
        self._window._refresh_hero()
        win.destroy()
        self._window.toast.add_toast(Adw.Toast(title="Play history cleared"))

    # ---------- genre chips ----------
    def _refresh_tags(self) -> None:
        while (c := self.chips_flow.get_first_child()):
            self.chips_flow.remove(c)
        genres = self._window.store.top_genres(4)
        if not genres:
            lbl = Gtk.Label(label=EMPTY_TAGS)
            lbl.add_css_class("sub")
            self.chips_flow.append(lbl)
            return
        for genre, count in genres:
            chip = Gtk.ToggleButton()
            chip.add_css_class("chip")
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
            dot = Gtk.Label(label="●")
            dot.add_css_class("gdot")
            dot.add_css_class(
                f"gd{int(hashlib.md5(genre.encode()).hexdigest(), 16) % 4}")
            inner.append(dot)
            name = Gtk.Label(label=genre)
            name.set_hexpand(True)
            inner.append(name)
            badge = Gtk.Label(label=str(count))
            badge.add_css_class("count")
            inner.append(badge)
            chip.set_child(inner)
            chip.set_active(self._window._active_genre == genre)
            chip.connect("toggled", self._on_genre, genre)
            self.chips_flow.append(chip)

    def _on_genre(self, btn: Gtk.ToggleButton, genre: str) -> None:
        if btn.get_active():
            self._window._active_genre = genre
            for sib in self._iter_flow(self.chips_flow):
                if sib is not btn:
                    sib.set_active(False)
        else:
            self._window._active_genre = None
        self._window._apply_filter()

    @staticmethod
    def _iter_flow(flow: Gtk.FlowBox):
        child = flow.get_first_child()
        while child:
            inner = child.get_first_child()
            if isinstance(inner, Gtk.ToggleButton):
                yield inner
            child = child.get_next_sibling()

    # ---------- recently played ----------
    def _refresh_played(self) -> None:
        while (row := self.played_box.get_first_child()):
            self.played_box.remove(row)
        plays = self._window.store.recent_plays(8)
        if not plays:
            lbl = Gtk.Label(label=EMPTY_PLAYED)
            lbl.add_css_class("sub")
            self.played_box.append(lbl)
            return
        for p in plays:
            self._add_played(p["title"], p["artist"], _ago(p["ts"]),
                             thumb_for(p["path"], 48))

    def _add_played(self, title: str, artist: str, when: str,
                     art_path: str | None = None) -> None:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.add_css_class("ritem")
        if art_path:
            pic = Gtk.Picture.new_for_filename(art_path)
            pic.set_size_request(40, 40)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.add_css_class("thumb")
            box.append(pic)
        else:
            th = Gtk.Label(label=(title[:1] or "?").upper())
            th.add_css_class("thumb")
            th.add_css_class(f"th{len(title) % 4}")
            box.append(th)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        t = Gtk.Label(label=title, xalign=0)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        t.set_max_width_chars(20)
        txt.append(t)
        sub = Gtk.Label(label=artist, xalign=0)
        sub.add_css_class("sub")
        txt.append(sub)
        txt.set_hexpand(True)
        box.append(txt)
        when_lbl = Gtk.Label(label=when)
        when_lbl.add_css_class("when")
        box.append(when_lbl)
        row.set_child(box)
        self.played_box.prepend(row)

    # ---------- now playing card ----------
    def _refresh_nowcard(self) -> None:
        track = self._window.engine.current()
        if track is None or not track.path:
            self.nc_title.set_text("Nothing playing")
            self.nc_artist.set_text("—")
            self.nc_art.set_paintable(None)
            return
        self.nc_title.set_text(track.title)
        self.nc_artist.set_text(track.artist)
        thumb = thumb_for(track.path, 200)
        if thumb:
            self.nc_art.set_filename(thumb)
        else:
            self.nc_art.set_paintable(None)
        self._window._sync_like_buttons()

    def _play_from_nc(self) -> None:
        if self._window.engine.current() is None:
            self._window._play_from(0)
        else:
            self._window.engine.toggle()

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


