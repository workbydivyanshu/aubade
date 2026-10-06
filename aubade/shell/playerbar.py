"""Aubade — player bar (bottom transport + seek + volume)."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk

from ..types import PlaybackEngine, Track, thumb_for

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ui import AubadeWindow






def _icon(name: str, fallback: str = "audio-x-generic") -> Gtk.Image:
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    if theme is not None and theme.has_icon(name):
        return Gtk.Image.new_from_icon_name(name)
    return Gtk.Image.new_from_icon_name(fallback)


class PlayerBar(Gtk.Box):
    """Bottom player bar with transport, seek, volume, and now-playing trigger."""

    def __init__(self, engine: PlaybackEngine, window: "AubadeWindow") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("npbar")
        self._engine = engine
        self._window = window
        self._seeking = False
        self._build()

    def _build(self) -> None:
        # Main row: art + title/artist + transport + queue/volume/fs
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        # Left: artwork + track info
        self.bar_art = Gtk.Picture()
        self.bar_art.set_size_request(48, 48)
        self.bar_art.set_content_fit(Gtk.ContentFit.COVER)
        self.bar_art.add_css_class("bar-art")
        row.append(self.bar_art)

        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        txt.set_valign(Gtk.Align.CENTER)
        self.bar_title = Gtk.Label(label="Nothing playing", xalign=0)
        self.bar_title.add_css_class("bar-title")
        self.bar_artist = Gtk.Label(label="Pick a song to start", xalign=0)
        self.bar_artist.add_css_class("sub")
        txt.append(self.bar_title)
        txt.append(self.bar_artist)
        row.append(txt)

        # Now Playing opener
        self.np_open_btn = self._sized_icon(
            Gtk.Button.new_from_icon_name("go-up"), 18)
        self.np_open_btn.add_css_class("icobtn")
        self.np_open_btn.set_tooltip_text("Now Playing")
        self.np_open_btn.connect("clicked", lambda _b: self._window._open_nowplaying())
        row.append(self.np_open_btn)

        # Like button
        self.like_btn = Gtk.ToggleButton(label="♡")
        self.like_btn.add_css_class("icobtn")
        self.like_btn.set_tooltip_text("Like")
        self.like_btn.connect("toggled", self._on_like)
        row.append(self.like_btn)

        # Share button
        share_btn = self._sized_icon(
            Gtk.Button.new_from_icon_name(self._best_share_icon()), 18)
        share_btn.add_css_class("icobtn")
        share_btn.set_tooltip_text("Copy title and artist")
        share_btn.connect("clicked", self._on_share)
        row.append(share_btn)

        # CSS cannot set widget alignment: the row is 48px tall (artwork
        # sets its height) and the default FILL valign would stretch these
        # round buttons into ovals, so pin each to its natural height.
        for _b in (self.np_open_btn, self.like_btn, share_btn):
            _b.set_valign(Gtk.Align.CENTER)

        # Spacer
        row.append(self._spacer())

        # Center transport — one tight cluster (4px gaps instead of the
        # row's 12) so shuffle/prev/play/next/repeat read as a unit.
        transport = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                            spacing=4)
        transport.set_valign(Gtk.Align.CENTER)

        self.shuffle_btn = Gtk.ToggleButton()
        self.shuffle_btn.set_icon_name("media-playlist-shuffle")
        self._sized_icon(self.shuffle_btn, 20)
        self.shuffle_btn.add_css_class("icobtn")
        self.shuffle_btn.set_tooltip_text("Shuffle")
        self.shuffle_btn.connect("toggled", self._on_shuffle)
        transport.append(self.shuffle_btn)

        self.prev_btn = self._sized_icon(
            Gtk.Button.new_from_icon_name("media-skip-backward"), 26)
        self.prev_btn.add_css_class("icobtn")
        self.prev_btn.connect("clicked", self._on_prev)
        transport.append(self.prev_btn)

        self.play_btn = self._sized_icon(
            Gtk.Button.new_from_icon_name("media-playback-start"), 22)
        self.play_btn.add_css_class("btn-main")
        self.play_btn.connect("clicked", lambda _b: self._engine.toggle())
        transport.append(self.play_btn)

        self.next_btn = self._sized_icon(
            Gtk.Button.new_from_icon_name("media-skip-forward"), 26)
        self.next_btn.add_css_class("icobtn")
        self.next_btn.connect("clicked", self._on_next)
        transport.append(self.next_btn)

        self.repeat_btn = Gtk.ToggleButton()
        self.repeat_btn.set_icon_name("media-playlist-repeat")
        self._sized_icon(self.repeat_btn, 20)
        self.repeat_btn.add_css_class("icobtn")
        self.repeat_btn.set_tooltip_text("Repeat: off → all → one")
        self.repeat_btn.connect("toggled", self._on_repeat)
        transport.append(self.repeat_btn)

        for _b in (self.shuffle_btn, self.prev_btn, self.play_btn,
                   self.next_btn, self.repeat_btn):
            _b.set_valign(Gtk.Align.CENTER)
        row.append(transport)

        row.append(self._spacer())

        # Right: queue, volume, fullscreen
        self.queue_btn = Gtk.Button()
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        if theme is not None and theme.has_icon("view-list"):
            self.queue_btn.set_icon_name("view-list")
        else:
            self.queue_btn.set_label("Queue")
        self._sized_icon(self.queue_btn, 20)
        self.queue_btn.add_css_class("icobtn")
        self.queue_btn.set_tooltip_text("Up next")
        self.queue_btn.connect("clicked", self._on_queue)
        self.queue_btn.set_valign(Gtk.Align.CENTER)
        row.append(self.queue_btn)

        vol_icon = _icon("audio-volume-medium", "audio-speakers")
        vol_icon.set_pixel_size(18)
        row.append(vol_icon)

        self.vol_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol_scale.set_draw_value(False)
        self.vol_scale.set_size_request(110, -1)
        self.vol_scale.add_css_class("vol")
        self.vol_scale.connect("value-changed", self._on_volume_scale)
        vol_click = Gtk.GestureClick(button=1)
        vol_click.connect("pressed", self._on_vol_press)
        self.vol_scale.add_controller(vol_click)
        row.append(self.vol_scale)

        self.fs_btn = Gtk.Button()
        self.fs_btn.set_icon_name("view-fullscreen")
        self._sized_icon(self.fs_btn, 20)
        self.fs_btn.add_css_class("icobtn")
        self.fs_btn.set_tooltip_text("Fullscreen")
        self.fs_btn.connect("clicked", self._on_fullscreen)
        self.fs_btn.set_valign(Gtk.Align.CENTER)
        row.append(self.fs_btn)

        self.append(row)

        # Seek row
        seekrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.t_cur = Gtk.Label(label="0:00")
        self.seek = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 1000, 1)
        self.seek.set_draw_value(False)
        self.seek.set_hexpand(True)
        self.seek.add_css_class("seek")
        self.seek.connect("value-changed", self._on_seek)
        seek_click = Gtk.GestureClick(button=1)
        seek_click.connect("pressed", self._on_seek_press)
        seek_click.connect("released", lambda *_a: setattr(self, "_seeking", False))
        self.seek.add_controller(seek_click)
        self.t_dur = Gtk.Label(label="0:00")
        seekrow.append(self.t_cur)
        seekrow.append(self.seek)
        seekrow.append(self.t_dur)
        self.append(seekrow)

        # Initial volume
        self.vol_scale.set_value(self._engine.volume * 100.0)

    def _best_share_icon(self) -> str:
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for name in ("document-send", "mail-send", "edit-copy", "emblem-shared"):
            if theme is not None and theme.has_icon(name):
                return name
        return "edit-copy"

    @staticmethod
    def _sized_icon(btn: Gtk.Button, px: int) -> Gtk.Button:
        child = btn.get_first_child()
        if isinstance(child, Gtk.Image):
            child.set_pixel_size(px)
        return btn

    @staticmethod
    def _spacer() -> Gtk.Widget:
        s = Gtk.Box()
        s.set_hexpand(True)
        return s

    # ---------- callbacks ----------
    def _on_like(self, btn: Gtk.ToggleButton) -> None:
        if self._window._in_like_sync:
            return
        cur = self._engine.current()
        if cur is None or not cur.path:
            btn.set_active(False)
            return
        self._window.store.set_like(cur.path, btn.get_active())
        if btn.get_active():
            self._window.liked.add(cur.path)
        else:
            self._window.liked.discard(cur.path)
        self._window._sync_like_buttons()

    def _on_share(self, _btn: Gtk.Button) -> None:
        cur = self._engine.current()
        if cur is None:
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set_text(f"{cur.title} — {cur.artist}")
        self._window.toast.add_toast(Adw.Toast(title="Copied to clipboard"))

    def _on_prev(self, _btn: Gtk.Button) -> None:
        self._window._log_skip()
        self._engine.prev()

    def _on_next(self, _btn: Gtk.Button) -> None:
        self._window._log_skip()
        self._engine.next()

    def _on_queue(self, _btn: Gtk.Button) -> None:
        self._window._open_queue()

    def _on_fullscreen(self, _btn: Gtk.Button) -> None:
        if self._window.is_fullscreen():
            self._window.unfullscreen()
        else:
            self._window.fullscreen()

    def _on_volume_scale(self, scale: Gtk.Scale) -> None:
        self._window._set_volume(scale.get_value() / 100.0)

    def _on_vol_press(self, _gesture, _n: int, x: float, _y: float) -> None:
        self.vol_scale.set_value(self._trough_frac(self.vol_scale, x) * 100.0)

    def _on_seek_press(self, _gesture, _n: int, x: float, _y: float) -> None:
        self._seeking = True
        frac = self._trough_frac(self.seek, x)
        self.seek.set_value(frac * 1000.0)
        self._engine.seek_frac(frac)
        self._window.mpris.seeked()

    def _on_seek(self, scale: Gtk.Scale) -> None:
        if self._seeking:
            self._engine.seek_frac(scale.get_value() / 1000.0)
            self._window.mpris.seeked()

    def _on_shuffle(self, btn: Gtk.ToggleButton) -> None:
        self._engine.shuffle = btn.get_active()
        self._window.store.set_profile("shuffle", "1" if btn.get_active() else "0")
        self._window.mpris.update()

    def _on_repeat(self, btn: Gtk.ToggleButton) -> None:
        mode = self._engine.repeat_mode()
        if btn.get_active() and mode == "off":
            self._engine.toggle_repeat()
        elif not btn.get_active() and mode != "off":
            while self._engine.repeat_mode() != "off":
                self._engine.toggle_repeat()
        mode = self._engine.repeat_mode()
        btn.set_tooltip_text(f"Repeat: {mode}")
        self._window.store.set_profile("repeat", mode)
        self._window.mpris.update()

    def _trough_frac(self, scale: Gtk.Scale, x: float) -> float:
        rect = scale.get_range_rect()
        if rect.width <= 0:
            return 0.0
        return max(0.0, min(1.0, (x - rect.x) / rect.width))

    # ---------- sync from engine ----------
    def sync_transport(self) -> None:
        icon = ("media-playback-pause" if self._engine.playing
                else "media-playback-start")
        self.play_btn.set_icon_name(icon)
        shuffle = self._engine.shuffle
        if self.shuffle_btn.get_active() != shuffle:
            self.shuffle_btn.set_active(shuffle)
        mode = self._engine.repeat_mode()
        active = mode != "off"
        if self.repeat_btn.get_active() != active:
            self.repeat_btn.set_active(active)
        self.repeat_btn.set_tooltip_text(f"Repeat: {mode}")

    def sync_nowplaying(self, track: Track | None, playing: bool) -> None:
        if track is not None and track.path:
            self.bar_title.set_text(track.title)
            self.bar_artist.set_text(f"{track.artist} · {track.album}")
            thumb = thumb_for(track.path, 200)
            if thumb:
                self.bar_art.set_filename(thumb)
            else:
                self.bar_art.set_paintable(None)
        else:
            self.bar_title.set_text("Nothing playing")
            self.bar_artist.set_text("Pick a song to start")
            self.bar_art.set_paintable(None)
        self._window._sync_like_buttons()

    def tick(self) -> None:
        if self._window._closed:
            return
        pos = self._engine.position()
        dur = self._engine.duration()
        self.t_cur.set_text(_fmt(pos))
        self.t_dur.set_text(_fmt(dur))
        if dur > 0 and not self._seeking:
            self.seek.set_value(pos / dur * 1000.0)


def _fmt(sec: float) -> str:
    if sec is None or sec != sec or sec < 0:
        return "0:00"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"