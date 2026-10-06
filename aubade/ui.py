"""Aubade window: 3-pane Apple-Music-concept layout on GTK4 + libadwaita.

All surfaces derive from the local library (SQLite cache + stats).
No mock data: empty states render instead of placeholder rows.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from . import __app_id__
from .art import thumb_for
from .library import Track, default_roots, sync_library
from .mpris import MPRIS
from .player import Engine
from .shell import NowPlayingSheet, PlayerBar, RightRail, Sidebar
from .store import Store

# ---------- nav (MENU = smart/local-powered, LIBRARY = library) ----------
MENU_NAV = [("go-home", "folder-music", "Home"),
            ("compass", "system-search", "Discover"),
            ("view-grid", "folder", "Browse"),
            ("audio-speakers", "network-wireless", "Radio"),
            ("audio-input-microphone", "audio-speakers", "Podcasts")]
LIB_NAV = [("media-optical", "folder-music", "Albums"),
           ("audio-x-generic", "folder-music", "Songs"),
           ("avatar-default", "system-users", "Artists")]
NAV_VIEWS = ["home", "discover", "browse", "radio", "podcasts",
             "albums", "songs", "artists"]
CACHE_VIEWS = ("albums", "songs", "artists", "discover", "browse",
               "radio", "podcasts", "search", "settings", "profile",
               "playlist", "album", "artist")

EMPTY_PLAYED = "Plays will appear here."
EMPTY_TAGS = "Genres from your files will appear here."

SEEK_STEP = 10.0   # seconds per Left/Right press
VOL_STEP = 0.05    # fraction of full scale per Up/Down press


def _ago(ts: float) -> str:
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
ICON_FALLBACK = "audio-x-generic"
SHARE_ICONS = ("document-send", "mail-send", "edit-copy", "emblem-shared")


def _best_icon(*names: str) -> str:
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    if theme is not None:
        for name in names:
            try:
                if theme.has_icon(name):
                    return name
            except Exception:
                continue
    return names[-1]


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _icon(name: str, fallback: str = ICON_FALLBACK) -> Gtk.Image:
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    if theme is not None and theme.has_icon(name):
        return Gtk.Image.new_from_icon_name(name)
    return Gtk.Image.new_from_icon_name(fallback)


def _fmt(sec: float) -> str:
    if sec is None or sec != sec or sec < 0:  # NaN guard
        return "0:00"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _fmt_remain(sec: float) -> str:
    sec = max(0, int(sec or 0))
    return f"-{sec // 60}:{sec % 60:02d}"


class AubadeApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=__app_id__,
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app) -> None:
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(os.path.dirname(__file__), "theme.css"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win = AubadeWindow(self)
        self.win.present()


class AubadeWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Aubade")
        self.set_default_size(1280, 800)
        self.engine = Engine()
        self.engine.on_track = self._on_engine_track
        self.engine.on_error = self._on_engine_error
        self.store = Store()
        self.tracks: list[Track] = []
        self.rows: list[tuple[Track, Gtk.ListBoxRow, Gtk.Label]] = []
        self._row_by_path: dict[str, Gtk.ListBoxRow] = {}
        self._row_items: dict[str, tuple] = {}
        self._playing_row: Gtk.ListBoxRow | None = None
        self._playing_item: tuple[Gtk.ListBoxRow, Gtk.Label, str] | None = None
        self._current_view = "home"
        self.liked: set[str] = self.store.liked_paths()
        self._seeking = False
        self._collapsed = False
        self._closed = False
        self._nav_labels: list[Gtk.Widget] = []
        self._nav_btns: list[Gtk.Button] = []
        self._views: dict[str, Gtk.Widget] = {}
        self._last_played_path: str | None = None
        self._active_genre: str | None = None
        self._roots = self._load_roots()
        self._track_total = 0
        self.display_name = self.store.get_profile("display_name")
        self.pronouns = self.store.get_profile("pronouns")

        self.toast = Adw.ToastOverlay()
        self.toast.set_halign(Gtk.Align.FILL)
        self.toast.set_valign(Gtk.Align.FILL)
        self.toast.set_hexpand(True)
        self.toast.set_vexpand(True)
        self.set_content(self.toast)
        self.appstack = Gtk.Stack()
        self.appstack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.toast.set_child(self.appstack)
        self.sidebar = Sidebar(self)
        self.playerbar = PlayerBar(self.engine, self)
        self.rail = RightRail(self)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row.set_vexpand(True)
        row.append(self.sidebar)
        row.append(self._build_main())
        row.append(self.rail)
        root.append(row)
        root.append(self.playerbar)
        self.appstack.add_named(root, "main")
        self._np_built = False
        self.mpris = MPRIS(self)
        # queue persistence: engine changes (incl. off-thread track advance)
        # are written to the store, restored once after the first sync
        self._queue_sig: str | None = None
        self._queue_hold = True
        self._queue_restored = False
        # read before the cache paint: that set_queue() would overwrite it
        try:
            self._queue_saved = self.store.load_queue()
        except Exception:
            self._queue_saved = ([], -1)
        self._queue_win: Gtk.Window | None = None
        self._queue_box: Gtk.ListBox | None = None
        self._queue_dragging = False
        self.engine.on_queue = self._persist_queue

        self._install_shortcuts()

        GLib.timeout_add(250, self._tick)
        self._restore_state()
        # instant paint from cache, then incremental sync in background
        cached = self.store.all_tracks()
        if cached:
            self._set_tracks(cached)
        else:
            self.toast.add_toast(Adw.Toast(title="Scanning ~/Music …"))
        threading.Thread(target=self._sync_thread, daemon=True).start()
        self.connect("close-request", self._on_close)

    def _load_roots(self) -> list[str]:
        try:
            roots = json.loads(self.store.get_profile("music_roots", ""))
            if isinstance(roots, list) and all(
                    isinstance(r, str) for r in roots) and roots:
                return roots
        except (ValueError, TypeError):
            pass
        return default_roots()

    def _restore_state(self) -> None:
        try:
            vol = float(self.store.get_profile("volume", "0.8"))
        except ValueError:
            vol = 0.8
        self.engine.set_volume(max(0.0, min(1.0, vol)))
        self.playerbar.vol_scale.set_value(
            self.engine.pipe.get_property("volume") * 100.0)
        if self.store.get_profile("shuffle", "0") == "1":
            self.engine.shuffle = True
        mode = self.store.get_profile("repeat", "off")
        if mode not in ("off", "all", "one"):
            mode = "off"
        self.engine.set_repeat_mode(mode)
        self._sync_transport()
        try:
            w = int(self.store.get_profile("win_w", "1280"))
            h = int(self.store.get_profile("win_h", "800"))
            w, h = self._clamp_to_monitor(max(900, w), max(600, h))
            self.set_default_size(w, h)
        except ValueError:
            pass
        if self.store.get_profile("sidebar_collapsed", "0") == "1":
            self._toggle_sidebar(self.sidebar.collapse_btn)

    @staticmethod
    def _clamp_to_monitor(w: int, h: int) -> tuple[int, int]:
        """Keep a windowed size inside the primary monitor workarea."""
        try:
            display = Gdk.Display.get_default()
            monitor = display.get_primary_monitor() if display else None
            if monitor is None:
                return w, h
            geo = monitor.get_geometry()
            return (max(900, min(w, geo.width - 40)),
                    max(600, min(h, geo.height - 80)))
        except Exception:
            return w, h

    # ---------- queue persistence ----------
    def _persist_queue(self) -> None:
        """Write the queue order + current index. Cheap synchronous SQLite;
        skips the write when the queue is byte-identical to the last one."""
        if self._queue_hold:
            return
        paths = [t.path for t in self.engine.queue]
        sig = json.dumps([paths, self.engine.index], separators=(",", ":"))
        if sig == self._queue_sig:
            return
        self._queue_sig = sig
        try:
            self.store.save_queue(paths, self.engine.index)
        except Exception:  # never break playback over a store write
            self._queue_sig = None

    def _restore_queue(self) -> None:
        """Rebuild the queue saved by the previous run. Tracks that vanished
        from the library are dropped silently; playback is not started."""
        if self._queue_restored:
            return
        self._queue_restored = True
        paths, index = self._queue_saved
        if not paths:
            return
        by_path = {t.path: t for t in self.tracks}
        tracks = [by_path[p] for p in paths
                  if p in by_path and os.path.isfile(p)]
        if not tracks:
            return
        self.engine.set_queue(tracks, min(max(index, 0), len(tracks) - 1))
        self._sync_transport()
        self._refresh_nowcard()
        if self._np_built:
            self._refresh_np()
        self.mpris.update()
        if len(tracks) < len(paths):
            self.toast.add_toast(Adw.Toast(
                title=f"Up next restored — {len(paths) - len(tracks)} gone"))

    def _on_close(self, _win) -> bool:
        self._closed = True
        self._queue_hold = False
        self._persist_queue()
        self.engine.shutdown()
        # Never persist a fullscreen/maximized size: restoring it as a
        # windowed size is what pushes the window off-screen.
        if not self.is_fullscreen() and not self.is_maximized():
            self.store.set_profile("win_w", str(self.get_width()))
            self.store.set_profile("win_h", str(self.get_height()))
        self.store.set_profile(
            "sidebar_collapsed", "1" if self._collapsed else "0")
        return False



    def _user_sub_text(self) -> str:
        bits = []
        if self.pronouns.strip():
            bits.append(self.pronouns.strip())
        bits.append(f"Local library · {self._track_total} tracks")
        return " · ".join(bits) if self.pronouns.strip() else bits[-1]

    def _open_profile(self, _btn: Gtk.Button) -> None:
        dlg = Gtk.Dialog(title="Profile", transient_for=self, modal=True)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Save", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        content = dlg.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        name_lbl = Gtk.Label(label="Display name", xalign=0)
        name_lbl.add_css_class("sub")
        self._profile_name = Gtk.Entry()
        self._profile_name.set_text(self.display_name)
        self._profile_name.set_placeholder_text(getpass.getuser().title())

        pro_lbl = Gtk.Label(label="Pronouns", xalign=0)
        pro_lbl.add_css_class("sub")
        self._profile_pro = Gtk.Entry()
        self._profile_pro.set_text(self.pronouns)
        self._profile_pro.set_placeholder_text("e.g. she/her")
        quick = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for option in ("she/her", "he/him", "they/them", "she/they",
                       "he/they", "any"):
            chip = Gtk.Button(label=option)
            chip.add_css_class("chip")
            chip.add_css_class("flat")
            chip.connect("clicked", self._pick_pronouns, option)
            quick.append(chip)

        for w in (name_lbl, self._profile_name, pro_lbl,
                  self._profile_pro, quick):
            content.append(w)
        dlg.connect("response", self._on_profile_response)
        dlg.present()

    def _pick_pronouns(self, _btn: Gtk.Button, option: str) -> None:
        self._profile_pro.set_text(option)

    def _on_profile_response(self, dlg: Gtk.Dialog, resp: int) -> None:
        if resp == Gtk.ResponseType.OK:
            self.display_name = self._profile_name.get_text().strip()
            self.pronouns = self._profile_pro.get_text().strip()
            self.store.set_profile("display_name", self.display_name)
            self.store.set_profile("pronouns", self.pronouns)
            shown = self.display_name or getpass.getuser().title()
            self.sidebar.user_name.set_text(shown)
            self.sidebar.user_avatar.set_text((shown[:1] or "?").upper())
            self.sidebar.user_sub.set_text(self.sidebar._user_sub_text())
            self.toast.add_toast(Adw.Toast(title="Profile saved 🏳️‍🌈"))
        dlg.destroy()

    # ---------- keyboard shortcuts ----------
    def _install_shortcuts(self) -> None:
        """Window-level transport keys.

        The controller hangs off the window, so it is evaluated after the
        focused widget in the bubble phase: buttons still activate on Space
        and entries still own their own text keys.
        """
        ctrl = Gtk.ShortcutController()
        for keyval, action in (
                (Gdk.KEY_space, self._key_toggle),
                (Gdk.KEY_Left, self._key_seek_back),
                (Gdk.KEY_Right, self._key_seek_fwd),
                (Gdk.KEY_Up, self._key_vol_up),
                (Gdk.KEY_Down, self._key_vol_down),
                (Gdk.KEY_n, self._key_next),
                (Gdk.KEY_p, self._key_prev),
                (Gdk.KEY_slash, self._key_search),
                (Gdk.KEY_Escape, self._on_esc)):
            ctrl.add_shortcut(Gtk.Shortcut.new(
                Gtk.KeyvalTrigger.new(keyval, 0),
                Gtk.CallbackAction.new(action)))
        self.add_controller(ctrl)
        self.shortcuts = ctrl

    def _typing_focus(self) -> bool:
        """True while a text-editable owns focus and should keep its keys."""
        return isinstance(self.get_focus(), (Gtk.Text, Gtk.Editable))

    def _key_toggle(self, _action, _param) -> bool:
        if self._typing_focus():
            return False
        if self.engine.current() is None:
            self._play_from(0)
        else:
            self.engine.toggle()
            self._sync_transport()
        return True

    def _seek_by(self, delta: float) -> None:
        if self.engine.current() is None:
            return
        self.engine.seek_sec(max(0.0, self.engine.position() + delta))
        self.mpris.seeked()
        self.mpris.update()

    def _key_seek_back(self, _action, _param) -> bool:
        if self._typing_focus():
            return False
        self._seek_by(-SEEK_STEP)
        return True

    def _key_seek_fwd(self, _action, _param) -> bool:
        if self._typing_focus():
            return False
        self._seek_by(SEEK_STEP)
        return True

    def _nudge_volume(self, delta: float) -> None:
        self.engine.set_volume(max(0.0, min(1.0, self.engine.volume + delta)))
        pct = self.engine.volume * 100.0
        self.playerbar.vol_scale.set_value(pct)
        if self._np_built:
            self.nowplaying.np_vol.set_value(pct)
        self.mpris.update()

    def _key_vol_up(self, _action, _param) -> bool:
        if self._typing_focus():
            return False
        self._nudge_volume(VOL_STEP)
        return True

    def _key_vol_down(self, _action, _param) -> bool:
        if self._typing_focus():
            return False
        self._nudge_volume(-VOL_STEP)
        return True

    def _key_next(self, _action, _param) -> bool:
        if self._typing_focus():
            return False
        self._on_next(None)
        return True

    def _key_prev(self, _action, _param) -> bool:
        if self._typing_focus():
            return False
        self._on_prev(None)
        return True

    def _key_search(self, _action, _param) -> bool:
        if self._typing_focus():
            return False
        if self._collapsed:
            self._toggle_sidebar(self.sidebar.collapse_btn)
        self.sidebar.search.grab_focus()
        return True

    def _on_esc(self, _widget, _args) -> bool:
        if self._np_built and self.appstack.get_visible_child_name() == "np":
            self._close_nowplaying()
            return True
        if self._current_view != "home":
            self._go("home")
            return True
        return False

    def _open_nowplaying(self, _btn: Gtk.Button = None) -> None:
        if not self._np_built:
            self.nowplaying = NowPlayingSheet(self)
            self._np_built = True
            self.appstack.add_named(self.nowplaying, "np")
        self.nowplaying.refresh()
        self.appstack.set_visible_child_name("np")

    def _close_nowplaying(self) -> None:
        self.appstack.set_visible_child_name("main")

    def _lyrics_offset(self) -> float:
        try:
            return float(self.store.get_profile("lyrics_offset", "0.0"))
        except ValueError:
            return 0.0

    def _on_sync_shift(self, _btn: Gtk.Button, delta: float) -> None:
        off = round(self._lyrics_offset() + delta, 1)
        self.store.set_profile("lyrics_offset", str(off))
        # Update settings view sync label if it exists
        if getattr(self, "_settings_sync", None) is not None:
            try:
                self._settings_sync.set_text(f"{off:+.1f}s")
            except Exception:
                pass
        # Update nowplaying sheet if visible
        if self._np_built and self.appstack.get_visible_child_name() == "np":
            self.nowplaying.np_sync_label.set_text(f"Sync {off:+.1f}s")
            self.nowplaying._np_line_idx = -2  # force re-highlight

    def _refresh_np(self) -> None:
        self.nowplaying.refresh()













    def _on_repeat_np(self, btn: Gtk.ToggleButton) -> None:
        self._on_repeat(btn)
        self._sync_transport()

    def _sync_transport(self) -> None:
        icon = ("media-playback-pause" if self.engine.playing
                else "media-playback-start")
        self.playerbar.play_btn.set_icon_name(icon)
        if self._np_built and self.nowplaying is not None:
            self.nowplaying.np_play.set_icon_name(icon)
        shuffle = self.engine.shuffle
        # Playerbar shuffle button
        if self.playerbar.shuffle_btn.get_active() != shuffle:
            self.playerbar.shuffle_btn.set_active(shuffle)
        # Nowplaying sheet shuffle button
        if self._np_built and self.nowplaying is not None:
            np_shuffle = self.nowplaying.np_shuffle
            if np_shuffle.get_active() != shuffle:
                np_shuffle.set_active(shuffle)
        mode = self.engine.repeat_mode()
        # Playerbar repeat button
        if self.playerbar.repeat_btn.get_active() == (mode == "off"):
            self.playerbar.repeat_btn.set_active(mode != "off")
        self.playerbar.repeat_btn.set_tooltip_text(f"Repeat: {mode}")
        # Nowplaying sheet repeat button
        if self._np_built and self.nowplaying is not None:
            np_repeat = self.nowplaying.np_repeat
            if np_repeat.get_active() == (mode == "off"):
                np_repeat.set_active(mode != "off")
            np_repeat.set_tooltip_text(f"Repeat: {mode}")





    def _on_nav(self, btn: Gtk.Button, view: str) -> None:
        self._go(view)

    def _go(self, view: str) -> None:
        self.sidebar.set_active(view)
        self._show_view(view)

    def _on_hist_back(self, _btn: Gtk.Button) -> None:
        if self._hist_pos > 0:
            self._hist_pos -= 1
            self._sync_nav_to_history()

    def _on_hist_fwd(self, _btn: Gtk.Button) -> None:
        if self._hist_pos < len(self._view_history) - 1:
            self._hist_pos += 1
            self._sync_nav_to_history()

    def _sync_nav_to_history(self) -> None:
        view = self._view_history[self._hist_pos]
        self.sidebar.set_active(view)
        self._show_view(view, record=False)
        self._update_hist_buttons()

    def _update_hist_buttons(self) -> None:
        self.back_btn.set_sensitive(self._hist_pos > 0)
        self.fwd_btn.set_sensitive(
            self._hist_pos < len(self._view_history) - 1)

    def _toggle_maximize(self) -> None:
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def _toggle_sidebar(self, btn: Gtk.Button) -> None:
        self._collapsed = not self._collapsed
        self.sidebar.set_size_request(72 if self._collapsed else 236, -1)
        for w in self.sidebar._nav_labels:
            w.set_visible(not self._collapsed)
        self.sidebar.search.set_visible(not self._collapsed)
        self.sidebar.logo_box.set_halign(
            Gtk.Align.CENTER if self._collapsed else Gtk.Align.START)
        btn.set_label("›" if self._collapsed else "‹")
        self.store.set_profile(
            "sidebar_collapsed", "1" if self._collapsed else "0")

    def _show_view(self, view: str, record: bool = True) -> None:
        """Lazy-build and display a center view. Player bar stays put."""
        if view not in self._views:
            if view == "albums":
                page = Gtk.ScrolledWindow()
                page.set_vexpand(True)
                page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
                self.albums_flow = Gtk.FlowBox(
                    homogeneous=True, selection_mode=Gtk.SelectionMode.NONE,
                    min_children_per_line=2, max_children_per_line=5,
                    column_spacing=14, row_spacing=14)
                self.albums_flow.add_css_class("albumgrid")
                page.set_child(self.albums_flow)
                self._views[view] = page
                self.stack.add_child(page)
                threading.Thread(target=self._build_albums_thread,
                                 daemon=True).start()
            elif view == "songs":
                self._views[view] = self._build_songs_view()
                self.stack.add_child(self._views[view])
            elif view == "artists":
                page = self._build_artists_view()
                self._views[view] = page
                self.stack.add_child(page)
            elif view == "discover":
                self._views[view] = self._build_discover_view()
                self.stack.add_child(self._views[view])
            elif view == "browse":
                self._views[view] = self._build_browse_view()
                self.stack.add_child(self._views[view])
            elif view == "radio":
                self._views[view] = self._build_radio_view()
                self.stack.add_child(self._views[view])
            elif view == "podcasts":
                self._views[view] = self._build_podcasts_view()
                self.stack.add_child(self._views[view])
            elif view == "search":
                self._views[view] = self._build_search_view()
                self.stack.add_child(self._views[view])
            elif view == "settings":
                self._views[view] = self._build_settings_view()
                self.stack.add_child(self._views[view])
            elif view == "profile":
                self._views[view] = self._build_profile_view()
                self.stack.add_child(self._views[view])
            elif view == "playlist":
                self._views[view] = self._build_playlists_view()
                self.stack.add_child(self._views[view])
            elif view == "album":
                self._views[view] = self._build_album_view()
                self.stack.add_child(self._views[view])
            elif view == "artist":
                self._views[view] = self._build_artist_view()
                self.stack.add_child(self._views[view])
            else:
                view = "home"
        self._current_view = view
        self.stack.set_visible_child(self._views[view])
        if record:
            # new navigation replaces any forward history
            self._view_history = self._view_history[:self._hist_pos + 1]
            if not self._view_history or self._view_history[-1] != view:
                self._view_history.append(view)
                if len(self._view_history) > 50:
                    self._view_history.pop(0)
            self._hist_pos = len(self._view_history) - 1
            self._update_hist_buttons()

    def _on_artist_row(self, box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        child = row.get_child()
        if child is None:
            return
        name_w = child.get_first_child()
        if name_w is not None:
            self._open_artist(name_w.get_text())

    def _play_artist_name(self, artist: str) -> None:
        tracks = self.store.tracks_for_artist(artist)
        if not tracks:
            return
        self.engine.set_queue(tracks, 0)
        self.engine.play_index(0)
        self.toast.add_toast(Adw.Toast(title=f"Playing {artist}"))

    # ---------- shared view helpers ----------
    def _view_head(self, overline: str, title: str,
                   action: Gtk.Widget | None = None) -> Gtk.Widget:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        cap = Gtk.Label(label=overline, xalign=0)
        cap.add_css_class("overline")
        wrap.append(cap)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lbl = Gtk.Label(label=title, xalign=0)
        lbl.add_css_class("h-pl")
        lbl.set_hexpand(True)
        box.append(lbl)
        if action is not None:
            box.append(action)
        wrap.append(box)
        return wrap

    def _view_page(self) -> tuple[Gtk.Widget, Gtk.Box]:
        page = Gtk.ScrolledWindow()
        page.set_vexpand(True)
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        col.set_hexpand(True)
        col.set_margin_top(4)
        page.set_child(col)
        return page, col

    def _track_row(self, t, i: int) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        idx = Gtk.Label(label=f"{i + 1:02d}")
        idx.set_size_request(34, -1)
        idx.add_css_class("idx")
        title = Gtk.Label(label=t.title, xalign=0)
        title.set_hexpand(True)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("tt")
        artist = Gtk.Label(label=t.artist, xalign=0)
        artist.set_size_request(150, -1)
        artist.set_ellipsize(Pango.EllipsizeMode.END)
        length = Gtk.Label(label=_fmt(t.length), xalign=1)
        length.set_size_request(56, -1)
        album = Gtk.Label(label=t.album, xalign=0)
        album.set_size_request(170, -1)
        album.set_ellipsize(Pango.EllipsizeMode.END)
        for w in (idx, title, artist, length, album):
            h.append(w)

        # Context menu button (⋮)
        menu_btn = Gtk.MenuButton()
        menu_btn.add_css_class("icobtn")
        menu_btn.set_tooltip_text("More options")
        menu_btn.set_icon_name("view-more-symbolic")
        menu_btn.set_halign(Gtk.Align.END)
        h.append(menu_btn)

        # Popover menu
        popover = Gtk.Popover()
        menu_btn.set_popover(popover)
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        menu_box.set_margin_top(8)
        menu_box.set_margin_bottom(8)
        menu_box.set_margin_start(8)
        menu_box.set_margin_end(8)
        popover.set_child(menu_box)

        def add_menu_item(label: str, action: callable, icon: str = None):
            btn = Gtk.Button()
            btn.add_css_class("flat")
            btn.connect("clicked", lambda _b: (popover.popdown(), action()))
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            if icon:
                img = Gtk.Image.new_from_icon_name(icon)
                img.set_pixel_size(16)
                hbox.append(img)
            lbl = Gtk.Label(label=label, xalign=0)
            lbl.set_hexpand(True)
            hbox.append(lbl)
            btn.set_child(hbox)
            menu_box.append(btn)

        # Play
        add_menu_item("Play", lambda: self._play_tracks([t]),
                      "media-playback-start-symbolic")
        # Play Next
        add_menu_item("Play Next", lambda: self.engine.play_next(t),
                      "media-skip-forward-symbolic")
        # Add to Queue
        add_menu_item("Add to Queue", lambda: self.engine.add_to_queue(t),
                      "view-list-symbolic")
        # Play Last
        add_menu_item("Play Last", lambda: self.engine.play_last(t),
                      "media-skip-forward-symbolic")

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        menu_box.append(sep)

        # Show Album / Artist
        add_menu_item("Show Album", lambda: self._open_album(None, t.album, t.album_artist),
                      "media-optical-symbolic")
        add_menu_item("Show Artist", lambda: self._open_artist(t.artist),
                      "avatar-default-symbolic")

        # Separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        menu_box.append(sep2)

        # Like / Unlike
        like_label = "♥ Liked" if t.path in self.liked else "♡ Like"
        add_menu_item(like_label, lambda: self._toggle_like_track(t),
                      "heart-symbolic")

        # Remove from Queue (only if track is in current queue)
        if t.path in [q.path for q in self.engine.queue]:
            add_menu_item("Remove from Queue", lambda: self._remove_from_queue(t),
                          "list-remove-symbolic")

        # Show in Folder
        add_menu_item("Show in Folder", lambda: self._show_in_folder(t),
                      "folder-open-symbolic")

        row.set_child(h)
        row.set_tooltip_text(t.path)
        return row

    def _track_listbox(self, tracks: list) -> Gtk.ListBox:
        box = Gtk.ListBox()
        box.add_css_class("tracks")
        for i, t in enumerate(tracks):
            box.append(self._track_row(t, i))
        box.connect("row-activated",
                    lambda _b, r: self._play_from_tracks(tracks, r.get_index()))
        return box

    def _play_tracks(self, tracks: list, shuffle: bool = False,
                     msg: str | None = None) -> None:
        if not tracks:
            self.toast.add_toast(Adw.Toast(title="Nothing to play here yet"))
            return
        if shuffle:
            import random
            tracks = list(tracks)
            random.shuffle(tracks)
        self.engine.set_queue(tracks, 0)
        self.engine.play_index(0)
        if msg:
            self.toast.add_toast(Adw.Toast(title=msg))

    def _genre_card(self, genre: str, count: int) -> Gtk.Button:
        import hashlib
        btn = Gtk.Button()
        btn.add_css_class("albumcard")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ph = Gtk.Label(label=(genre[:2] or "?").upper())
        ph.add_css_class("albumph")
        ph.add_css_class(f"gd{int(hashlib.md5(genre.encode()).hexdigest(), 16) % 4}")
        ph.set_size_request(160, 120)
        v.append(ph)
        t = Gtk.Label(label=genre)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        t.set_max_width_chars(18)
        s = Gtk.Label(label=_plural(count, "track"))
        s.add_css_class("sub")
        v.append(t)
        v.append(s)
        btn.set_child(v)
        btn.connect("clicked", self._play_genre, genre)
        return btn

    def _play_genre(self, _btn: Gtk.Button, genre: str) -> None:
        self._play_tracks(self.store.tracks_for_genre(genre),
                          msg=f"Playing {genre}")

    def _genre_grid(self, genres) -> Gtk.FlowBox:
        flow = Gtk.FlowBox(homogeneous=True,
                           selection_mode=Gtk.SelectionMode.NONE,
                           min_children_per_line=2, max_children_per_line=5,
                           column_spacing=14, row_spacing=14)
        flow.add_css_class("albumgrid")
        for genre, count in genres:
            flow.append(self._genre_card(genre, count))
        return flow

    def _rebuild_view(self, key: str) -> None:
        page = self._views.pop(key, None)
        if page is not None and page.get_parent() is self.stack:
            self.stack.remove(page)

    def _open_album(self, _btn: Gtk.Button, album: str, album_artist: str) -> None:
        self._detail_album = (album, album_artist)
        self._rebuild_view("album")
        self._go("album")

    def _open_artist(self, artist: str) -> None:
        self._detail_artist = artist
        self._rebuild_view("artist")
        self._go("artist")

    # ---------- songs (sortable) ----------
    def _build_songs_view(self) -> Gtk.Widget:
        page, col = self._view_page()
        head = self._view_head("LIBRARY", "Songs")
        col.append(head)
        # Sort segmented control
        seg = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for key, label in (("title", "Title"), ("artist", "Artist"),
                           ("album", "Album"), ("added", "Date Added")):
            b = Gtk.ToggleButton(label=label)
            b.add_css_class("chip")
            b.set_active(getattr(self, "_songs_sort", "artist") == key)
            b.connect("toggled", self._on_songs_sort, key)
            seg.append(b)
        col.append(seg)
        # Genre filter chips (mirror from right rail)
        col.append(self._view_head("GENRES", "Filter by Genre"))
        self.songs_chips_flow = Gtk.FlowBox(homogeneous=False,
                                            selection_mode=Gtk.SelectionMode.NONE)
        self.songs_chips_flow.set_max_children_per_line(4)
        self.songs_chips_flow.set_min_children_per_line(2)
        col.append(self.songs_chips_flow)
        self._refresh_songs_tags()
        # Search entry
        search_entry = Gtk.SearchEntry(placeholder_text="Search songs, artists, albums…")
        search_entry.connect("search-changed", self._on_songs_search)
        search_entry.set_text(getattr(self, "_search_q", ""))
        col.append(search_entry)
        # Track list
        col.append(self._build_track_page(
            self.store.all_tracks_sorted(
                getattr(self, "_songs_sort", "artist")), "songs"))
        return page

    def _on_songs_sort(self, btn: Gtk.ToggleButton, key: str) -> None:
        if not btn.get_active():
            btn.set_active(True)
            return
        self._songs_sort = key
        self._rebuild_view("songs")
        self._show_view("songs", record=False)

    # ---------- artists (detail drill-down) ----------
    def _build_artists_view(self) -> Gtk.Widget:
        page = Gtk.ScrolledWindow()
        page.set_vexpand(True)
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.ListBox()
        box.add_css_class("tracks")
        for row in self.store.artists():
            r = Gtk.ListBoxRow()
            h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            nm = Gtk.Label(label=row["artist"], xalign=0)
            nm.set_hexpand(True)
            h.append(nm)
            sub = Gtk.Label(
                label=f"{_plural(row['c'], 'track')} · "
                      f"{_plural(row['plays'], 'play')}")
            sub.add_css_class("sub")
            h.append(sub)
            r.set_child(h)
            box.append(r)
        box.connect("row-activated", self._on_artist_row)
        page.set_child(box)
        return page

    # ---------- search ----------
    def _build_search_view(self) -> Gtk.Widget:
        page, col = self._view_page()
        col.append(self._view_head("LIBRARY", "Search"))
        entry = Gtk.SearchEntry(placeholder_text="Songs, artists, albums …")
        entry.connect("search-changed", self._on_view_search)
        entry.connect("activate", self._on_search_activate)
        self._search_entry = entry
        col.append(entry)
        self._search_results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                        spacing=8)
        col.append(self._search_results)
        hint = Gtk.Label(label="Type to search your library")
        hint.add_css_class("sub")
        self._search_results.append(hint)
        return page

    def _on_search_activate(self, entry: Gtk.SearchEntry) -> None:
        """Activate (Enter) in search entry: play the first result."""
        if getattr(self, '_last_search_top_track', None):
            self._play_tracks([self._last_search_top_track])

    def _on_view_search(self, entry: Gtk.SearchEntry) -> None:
        self._last_search_q = q = entry.get_text().strip()
        if not q:
            self._show_search_empty()
            return
        # Parse the query into terms
        terms = []
        for token in q.split():
            if ':' in token:
                key, value = token.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                if key not in ('artist', 'album', 'genre', 'title'):
                    # Unknown prefix, treat as plain term
                    key = None
            else:
                key = None
                value = token
            if value:
                terms.append((key, value))
        if not terms:
            self._show_search_empty()
            return
        # Score each track
        scored_tracks = []
        for t in self.tracks:
            blob = self._search_blobs.get(t.path)
            if blob is None:
                # Should not happen, but fallback
                blob = f"{t.title or ''} {t.artist or ''} {t.album or ''} {t.genre or ''}".lower()
            score = 0
            for key, value in terms:
                term_score = 0
                value_lower = value.lower()
                fields_to_check = [key] if key else ['title', 'artist', 'album', 'genre']
                for field in fields_to_check:
                    field_value = getattr(t, field, '') or ''
                    field_value_lower = field_value.lower()
                    if field_value_lower.startswith(value_lower):
                        if field == 'title':
                            s = 4
                        elif field == 'artist':
                            s = 2
                        else:  # album or genre
                            s = 1
                    elif value_lower in field_value_lower:
                        if field == 'title':
                            s = 3
                        elif field == 'artist':
                            s = 1
                        else:  # album or genre
                            s = 1
                    else:
                        s = 0
                    if s > term_score:
                        term_score = s
                if term_score == 0:
                    score = 0
                    break
                else:
                    score += term_score
            if score > 0:
                scored_tracks.append((t, score))
        if not scored_tracks:
            self._show_search_empty()
            return
        # Sort by score descending, then by title for stability
        scored_tracks.sort(key=lambda x: (-x[1], x[0].title))
        # Prepare sections
        songs = scored_tracks[:50]  # cap songs at 50
        # Albums and artists: deduplicate and cap at ~12
        albums_set = set()
        artists_set = set()
        for t, _ in scored_tracks:
            if t.album and t.artist:
                albums_set.add((t.album, t.artist))
            if t.artist:
                artists_set.add(t.artist)
        albums = list(albums_set)[:12]
        artists = list(artists_set)[:12]
        # Build UI
        while (c := self._search_results.get_first_child()):
            self._search_results.remove(c)
        # Top result (first song)
        if songs:
            top_track, _ = songs[0]
            self._last_search_top_track = top_track
            top_card = self._make_top_result_card(top_track)
            self._search_results.append(top_card)
        else:
            self._last_search_top_track = None
        # Songs section
        if songs:
            songs_head = Gtk.Label(label=f"Songs ({len(songs)})", xalign=0)
            songs_head.add_css_class("sub")
            self._search_results.append(songs_head)
            songs_tracks = [t for t, _ in songs]
            self._search_results.append(self._track_listbox(songs_tracks))
        # Albums section
        if albums:
            albums_head = Gtk.Label(label=f"Albums ({len(albums)})", xalign=0)
            albums_head.add_css_class("sub")
            self._search_results.append(albums_head)
            album_flow = Gtk.FlowBox(homogeneous=True,
                                     selection_mode=Gtk.SelectionMode.NONE,
                                     min_children_per_line=2, max_children_per_line=5,
                                     column_spacing=14, row_spacing=14)
            album_flow.add_css_class("albumgrid")
            for album, artist in albums:
                album_flow.append(self._album_card(album, artist))
            self._search_results.append(album_flow)
        # Artists section
        if artists:
            artists_head = Gtk.Label(label=f"Artists ({len(artists)})", xalign=0)
            artists_head.add_css_class("sub")
            self._search_results.append(artists_head)
            artist_flow = Gtk.FlowBox(homogeneous=True,
                                      selection_mode=Gtk.SelectionMode.NONE,
                                      min_children_per_line=2, max_children_per_line=5,
                                      column_spacing=14, row_spacing=14)
            artist_flow.add_css_class("albumgrid")
            for artist in artists:
                artist_flow.append(self._artist_card(artist))
            self._search_results.append(artist_flow)

    def _show_search_empty(self) -> None:
        """Show empty state in search results."""
        self._last_search_top_track = None
        while (c := self._search_results.get_first_child()):
            self._search_results.remove(c)
        hint = Gtk.Label(label=f'No matches for "{getattr(self, "_last_search_q", "")}"')
        hint.add_css_class("sub")
        self._search_results.append(hint)

    def _make_top_result_card(self, track: Track) -> Gtk.Button:
        """Create a prominent card for the top search result."""
        btn = Gtk.Button()
        btn.add_css_class("albumcard")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        # Use the first letter of the track title as placeholder
        ph = Gtk.Label(label=(track.title[:1] or "?").upper())
        ph.add_css_class("albumph")
        # Use a hash of the track title for color variation
        import hashlib
        ph.add_css_class(f"gd{int(hashlib.md5(track.title.encode()).hexdigest(), 16) % 4}")
        ph.set_size_request(160, 120)
        v.append(ph)
        t = Gtk.Label(label=track.title)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        t.set_max_width_chars(18)
        v.append(t)
        sub = Gtk.Label(label=f"{track.artist} – {track.album}")
        sub.add_css_class("sub")
        v.append(sub)
        btn.set_child(v)
        btn.connect("clicked", lambda _b: self._play_tracks([track]))
        return btn

    def _album_card(self, album: str, artist: str) -> Gtk.Button:
        """Create an album card for search results."""
        btn = Gtk.Button()
        btn.add_css_class("albumcard")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ph = Gtk.Label(label=(album[:1] or "?").upper())
        ph.add_css_class("albumph")
        import hashlib
        ph.add_css_class(f"gd{int(hashlib.md5(album.encode()).hexdigest(), 16) % 4}")
        ph.set_size_request(160, 120)
        v.append(ph)
        t = Gtk.Label(label=album)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        t.set_max_width_chars(18)
        v.append(t)
        sub = Gtk.Label(label=f"{artist} – {_plural(len(self.store.tracks_for_album(album, artist)), 'track')}")
        sub.add_css_class("sub")
        v.append(sub)
        btn.set_child(v)
        btn.connect("clicked", lambda _b, a=album, ar=artist: self._open_album(_b, a, ar))
        return btn

    def _artist_card(self, artist: str) -> Gtk.Button:
        """Create an artist card for search results."""
        btn = Gtk.Button()
        btn.add_css_class("albumcard")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ph = Gtk.Label(label=(artist[:1] or "?").upper())
        ph.add_css_class("albumph")
        import hashlib
        ph.add_css_class(f"gd{int(hashlib.md5(artist.encode()).hexdigest(), 16) % 4}")
        ph.set_size_request(160, 120)
        v.append(ph)
        t = Gtk.Label(label=artist)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        t.set_max_width_chars(18)
        v.append(t)
        sub = Gtk.Label(label=f"{_plural(len(self.store.tracks_for_artist(artist)), 'track')} • {_plural(self.store.get_play_count_for_artist(artist), 'play')}")
        sub.add_css_class("sub")
        v.append(sub)
        btn.set_child(v)
        btn.connect("clicked", lambda _b, a=artist: self._open_artist(a))
        return btn


    # ---------- settings ----------
    def _setting_row(self, title: str, sub: str,
                     action: Gtk.Widget) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        txt.set_hexpand(True)
        txt.append(Gtk.Label(label=title, xalign=0))
        s = Gtk.Label(label=sub, xalign=0)
        s.add_css_class("sub")
        txt.append(s)
        h.append(txt)
        h.append(action)
        row.set_child(h)
        return row

    def _build_settings_view(self) -> Gtk.Widget:
        page, col = self._view_page()
        col.append(self._view_head("LIBRARY", "Settings"))
        box = Gtk.ListBox()
        box.add_css_class("tracks")
        folder_btn = Gtk.Button(label="Choose…")
        folder_btn.connect("clicked", self._pick_folder)
        roots = ", ".join(self._roots) if self._roots else "—"
        box.append(self._setting_row("Music folder", roots, folder_btn))
        sync_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        minus = Gtk.Button(label="−")
        minus.add_css_class("icobtn")
        minus.connect("clicked", self._on_sync_shift, -0.5)
        plus = Gtk.Button(label="+")
        plus.add_css_class("icobtn")
        plus.connect("clicked", self._on_sync_shift, 0.5)
        self._settings_sync = Gtk.Label(label=f"{self._lyrics_offset():+.1f}s")
        self._settings_sync.add_css_class("np-sync")
        sync_box.append(minus)
        sync_box.append(self._settings_sync)
        sync_box.append(plus)
        box.append(self._setting_row("Lyrics sync offset",
                                     "Shifts karaoke highlight", sync_box))
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", self._clear_history_btn)
        box.append(self._setting_row("Play history", "Plays and skips",
                                     clear_btn))
        c = self.store.counts()
        try:
            import aubade as _pkg
            ver = getattr(_pkg, "__version__", "?")
        except Exception:
            ver = "?"
        info = Gtk.Label(
            label=f"{c['tracks']} tracks · {c['plays']} plays · "
                  f"{c['likes']} likes · Aubade {ver}",
            xalign=0)
        info.add_css_class("sub")
        box.append(self._setting_row("About", "Local library stats", info))
        col.append(box)
        return page

    def _clear_history_btn(self, _btn: Gtk.Button) -> None:
        self.store.clear_plays()
        self._last_played_path = None
        self._refresh_played()
        self._refresh_hero()
        self.toast.add_toast(Adw.Toast(title="Play history cleared"))

    # ---------- profile (screen) ----------
    def _build_profile_view(self) -> Gtk.Widget:
        page, col = self._view_page()
        col.append(self._view_head("LIBRARY", "Profile"))
        import getpass
        shown = self.display_name or getpass.getuser().title()
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        av = Gtk.Label(label=(shown[:1] or "?").upper())
        av.add_css_class("avatar")
        av.set_size_request(56, 56)
        card.append(av)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        txt.set_hexpand(True)
        nm = Gtk.Label(label=shown, xalign=0)
        nm.add_css_class("h-pl")
        txt.append(nm)
        pro = self.pronouns.strip() or "No pronouns set"
        sub = Gtk.Label(label=f"{pro} · {self.sidebar._user_sub_text()}", xalign=0)
        sub.add_css_class("sub")
        txt.append(sub)
        card.append(txt)
        edit = Gtk.Button(label="Edit Profile")
        edit.add_css_class("btn-ghost")
        edit.connect("clicked", self._open_profile)
        card.append(edit)
        col.append(card)
        c = self.store.counts()
        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        for label, n in (("Tracks", c["tracks"]), ("Plays", c["plays"]),
                         ("Likes", c["likes"])):
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            num = Gtk.Label(label=str(n))
            num.add_css_class("h-pl")
            cap = Gtk.Label(label=label.upper())
            cap.add_css_class("overline")
            cell.append(num)
            cell.append(cap)
            stats.append(cell)
        col.append(stats)
        return page

    # ---------- auto playlists ----------
    def _auto_playlists(self) -> list[tuple[str, str, list]]:
        recent = [self.store._row_track(r)
                  for r in self.store.db.execute(
                      """SELECT t.path, t.title, t.artist, t.album, t.genre,
                                t.length, t.mtime, t.lyrics, t.synced
                         FROM plays p JOIN tracks t ON t.path = p.path
                         ORDER BY p.ts DESC LIMIT 50""")]
        return [
            ("Liked Songs", "Tracks you hearted",
             self.store.liked_tracks_list()),
            ("Recently Played", "Your latest sessions", recent),
            ("Most Played", "On repeat",
             self.store.most_played_tracks(50)),
            ("Recently Added", "Fresh in your library",
             self.store.recent_added(50)),
        ]

    def _build_playlists_view(self) -> Gtk.Widget:
        page, col = self._view_page()
        col.append(self._view_head("LIBRARY", "Playlists"))
        box = Gtk.ListBox()
        box.add_css_class("tracks")
        pls = self._auto_playlists()
        self._pls_cache = {name: tracks for name, _sub, tracks in pls}
        for name, sub, tracks in pls:
            r = Gtk.ListBoxRow()
            h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            nm = Gtk.Label(label=name, xalign=0)
            nm.set_hexpand(True)
            h.append(nm)
            s = Gtk.Label(label=f"{len(tracks)} · {sub}")
            s.add_css_class("sub")
            h.append(s)
            r.set_child(h)
            box.append(r)
        box.connect("row-activated", self._on_playlist_row)
        col.append(box)
        return page

    def _on_playlist_row(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        names = list(self._pls_cache)
        i = row.get_index()
        if 0 <= i < len(names):
            self._play_tracks(self._pls_cache[names[i]], msg=f"Playing {names[i]}")

    # ---------- album / artist detail ----------
    def _detail_head(self, title: str, sub: str,
                     art_path: str | None) -> Gtk.Box:
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        if art_path:
            pic = Gtk.Picture.new_for_filename(art_path)
            pic.set_size_request(200, 200)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.add_css_class("np-art")
            head.append(pic)
        else:
            ph = Gtk.Label(label=(title[:1] or "?").upper())
            ph.add_css_class("albumph")
            ph.set_size_request(200, 200)
            head.append(ph)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        txt.set_hexpand(True)
        txt.set_valign(Gtk.Align.CENTER)
        t = Gtk.Label(label=title, xalign=0)
        t.add_css_class("h-pl")
        t.set_ellipsize(Pango.EllipsizeMode.END)
        txt.append(t)
        s = Gtk.Label(label=sub, xalign=0)
        s.add_css_class("sub")
        txt.append(s)
        head.append(txt)
        return head

    def _build_album_view(self) -> Gtk.Widget:
        album, album_artist = getattr(self, "_detail_album", ("", ""))
        tracks = self.store.album_tracks(album, album_artist) if album else []
        page, col = self._view_page()
        col.append(self._view_head("LIBRARY", album or "Album"))
        rep = self.store.first_track_path(album, album_artist) if album else None
        col.append(self._detail_head(
            album, f"{album_artist} · {_plural(len(tracks), 'track')}",
            thumb_for(rep, 200) if rep else None))
        cta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        play = Gtk.Button(label="▶  Play")
        play.add_css_class("btn-play")
        play.connect("clicked", lambda _b: self._play_tracks(tracks))
        shuffle = Gtk.Button(label="⇄  Shuffle")
        shuffle.add_css_class("btn-ghost")
        shuffle.connect("clicked",
                        lambda _b: self._play_tracks(tracks, shuffle=True))
        cta.append(play)
        cta.append(shuffle)
        col.append(cta)
        if tracks:
            col.append(self._track_listbox(tracks))
        return page

    def _build_artist_view(self) -> Gtk.Widget:
        artist = getattr(self, "_detail_artist", "")
        tracks = self.store.tracks_for_artist(artist) if artist else []
        albums = {}
        for t in tracks:
            albums.setdefault(t.album, []).append(t)
        page, col = self._view_page()
        col.append(self._view_head("ARTIST", artist or "Artist"))
        rep = tracks[0].path if tracks else None
        col.append(self._detail_head(
            artist, f"{_plural(len(albums), 'album')} · "
                    f"{_plural(len(tracks), 'track')}",
            thumb_for(rep, 200) if rep else None))
        cta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        play = Gtk.Button(label="▶  Play")
        play.add_css_class("btn-play")
        play.connect("clicked", lambda _b: self._play_tracks(tracks))
        shuffle = Gtk.Button(label="⇄  Shuffle")
        shuffle.add_css_class("btn-ghost")
        shuffle.connect("clicked",
                        lambda _b: self._play_tracks(tracks, shuffle=True))
        cta.append(play)
        cta.append(shuffle)
        col.append(cta)
        if tracks:
            col.append(self._track_listbox(tracks[:50]))
        return page

    # ---------- discover / browse / radio / podcasts ----------
    def _build_discover_view(self) -> Gtk.Widget:
        page, col = self._view_page()
        col.append(self._view_head("FEATURED", "Made For You"))
        top = self.store.top_artist()
        if top:
            artist, ntracks, nplays = top
            tracks = self.store.tracks_for_artist(artist)
            rep = tracks[0].path if tracks else None
            col.append(self._detail_head(
                f"{artist} Mix",
                f"{_plural(ntracks, 'track')} · {_plural(nplays, 'play')}",
                thumb_for(rep, 200) if rep else None))
            cta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            play = Gtk.Button(label="▶  Play")
            play.add_css_class("btn-play")
            play.connect("clicked",
                         lambda _b: self._play_tracks(tracks,
                                                     msg=f"Playing {artist}"))
            shuffle = Gtk.Button(label="⇄  Shuffle")
            shuffle.add_css_class("btn-ghost")
            shuffle.connect("clicked",
                            lambda _b: self._play_tracks(tracks, shuffle=True))
            cta.append(play)
            cta.append(shuffle)
            col.append(cta)
        col.append(self._view_head("GENRES", "Browse by Mood"))
        col.append(self._genre_grid(self.store.all_genres(8)))
        recent = self.store.recent_added(10)
        if recent:
            col.append(self._view_head("NEW MUSIC", "Recently Added"))
            col.append(self._track_listbox(recent))
        return page

    def _build_browse_view(self) -> Gtk.Widget:
        page, col = self._view_page()
        col.append(self._view_head("GENRES", "Browse"))
        genres = self.store.all_genres()
        if genres:
            col.append(self._genre_grid(genres))
        else:
            lbl = Gtk.Label(label=EMPTY_TAGS, xalign=0)
            lbl.add_css_class("sub")
            col.append(lbl)
        return page

    def _station_card(self, name: str, blurb: str, tracks: list) -> Gtk.Button:
        import hashlib
        btn = Gtk.Button()
        btn.add_css_class("albumcard")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ph = Gtk.Label(label=(name[:2] or "?").upper())
        ph.add_css_class("albumph")
        ph.add_css_class(
            f"gd{int(hashlib.md5(name.encode()).hexdigest(), 16) % 4}")
        ph.set_size_request(160, 120)
        v.append(ph)
        t = Gtk.Label(label=name)
        t.set_ellipsize(Pango.EllipsizeMode.END)
        t.set_max_width_chars(18)
        s = Gtk.Label(label=f"{blurb} · {len(tracks)}")
        s.add_css_class("sub")
        s.set_ellipsize(Pango.EllipsizeMode.END)
        s.set_max_width_chars(24)
        v.append(t)
        v.append(s)
        btn.set_child(v)
        btn.connect("clicked",
                    lambda _b: self._play_tracks(tracks, shuffle=True,
                                                msg=f"Playing {name}"))
        return btn

    def _build_radio_view(self) -> Gtk.Widget:
        page, col = self._view_page()
        col.append(self._view_head("RADIO", "Stations for You"))
        stations = [
            ("Shuffle All", "Your whole library, shuffled", self.tracks),
            ("Most Played", "Your heaviest rotation",
             self.store.most_played_tracks(50)),
            ("Liked Radio", "Your hearted tracks",
             self.store.liked_tracks_list()),
        ]
        for genre, count in self.store.top_genres(3):
            stations.append(
                (f"{genre} Radio", f"{count} tracks, endless mix",
                 self.store.tracks_for_genre(genre)))
        flow = Gtk.FlowBox(homogeneous=True,
                           selection_mode=Gtk.SelectionMode.NONE,
                           min_children_per_line=2, max_children_per_line=4,
                           column_spacing=14, row_spacing=14)
        flow.add_css_class("albumgrid")
        for name, blurb, tracks in stations:
            if tracks:
                flow.append(self._station_card(name, blurb, tracks))
        col.append(flow)
        return page

    def _build_podcasts_view(self) -> Gtk.Widget:
        page, col = self._view_page()
        col.append(self._view_head("PODCASTS", "Podcasts"))
        lbl = Gtk.Label(label="No podcasts here yet", xalign=0)
        lbl.add_css_class("h-pl")
        col.append(lbl)
        body = Gtk.Label(
            label="Aubade plays local files and has no feed support. "
                  "Spoken-word audio in your library still shows up "
                  "under Songs.",
            xalign=0)
        body.set_wrap(True)
        body.add_css_class("sub")
        col.append(body)
        return page

    def _build_track_page(self, tracks: list[Track],
                          tag: str) -> Gtk.Widget:
        """A standalone full-library table (Songs view), filled in chunks."""
        page = Gtk.ScrolledWindow()
        page.set_vexpand(True)
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.ListBox()
        box.add_css_class("tracks")
        page.set_child(box)
        box.connect("row-activated",
                    lambda _b, r: self._play_from_tracks(tracks, r.get_index()))
        state = {"i": 0, "token": getattr(self, "_songs_token", 0) + 1}
        self._songs_token = state["token"]

        def fill() -> bool:
            if state["token"] != self._songs_token:
                return False
            n = 0
            while state["i"] < len(tracks) and n < 500:
                i = state["i"]
                t = tracks[i]
                row = Gtk.ListBoxRow()
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
                length = Gtk.Label(label=_fmt(t.length), xalign=1)
                length.set_size_request(56, -1)
                album = Gtk.Label(label=t.album, xalign=0)
                album.set_size_request(170, -1)
                album.set_ellipsize(Pango.EllipsizeMode.END)
                for w in (idx, title, artist, length, album):
                    h.append(w)
                row.set_child(h)
                box.append(row)
                state["i"] += 1
                n += 1
            return state["i"] < len(tracks)

        GLib.idle_add(fill)
        setattr(self, f"_{tag}_box", box)
        return page

    def _play_from_tracks(self, tracks: list[Track], i: int) -> None:
        if 0 <= i < len(tracks):
            self.engine.set_queue(tracks, 0)
            self.engine.play_index(i)

    def _build_albums_thread(self) -> None:
        cards = []
        for row in self.store.albums():
            album = row["album"]
            album_artist = row["album_artist"]
            rep = self.store.first_track_path(album, album_artist)
            thumb = thumb_for(rep, 200) if rep else None
            cards.append((album, album_artist, row["c"], thumb))
        GLib.idle_add(self._fill_albums, cards)

    def _fill_albums(self, cards) -> bool:
        while (c := self.albums_flow.get_first_child()):
            self.albums_flow.remove(c)
        self._album_cards = cards
        self._album_i = 0
        self._albums_token = getattr(self, "_albums_token", 0) + 1
        GLib.idle_add(self._fill_albums_chunk, self._albums_token)
        return False

    def _fill_albums_chunk(self, token: int) -> bool:
        if token != getattr(self, "_albums_token", -1):
            return False
        n = 0
        while self._album_i < len(self._album_cards) and n < 100:
            album, album_artist, count, thumb = self._album_cards[self._album_i]
            btn = Gtk.Button()
            btn.add_css_class("albumcard")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            if thumb:
                pic = Gtk.Picture.new_for_filename(thumb)
                pic.set_size_request(160, 160)
                pic.set_content_fit(Gtk.ContentFit.COVER)
                v.append(pic)
            else:
                ph = Gtk.Label(label=(album[:1] or "?").upper())
                ph.add_css_class("albumph")
                ph.set_size_request(160, 160)
                v.append(ph)
            t = Gtk.Label(label=album)
            t.set_ellipsize(Pango.EllipsizeMode.END)
            t.set_max_width_chars(18)
            s = Gtk.Label(label=f"{album_artist} · {count}")
            s.add_css_class("sub")
            s.set_ellipsize(Pango.EllipsizeMode.END)
            s.set_max_width_chars(20)
            v.append(t)
            v.append(s)
            btn = Gtk.Button()
            btn.add_css_class("albumcard")
            btn.set_child(v)
            btn.connect("clicked", self._open_album, album, album_artist)
            self.albums_flow.append(btn)
            self._album_i += 1
            n += 1
        return self._album_i < len(self._album_cards)

    # ================= main =================
    def _build_main(self) -> Gtk.Widget:
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main.add_css_class("main")
        main.set_hexpand(True)

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        main.append(self.stack)

        home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        home.set_hexpand(True)

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.back_btn = Gtk.Button(label="‹")
        self.back_btn.add_css_class("roundbtn")
        self.back_btn.set_tooltip_text("Back")
        self.back_btn.connect("clicked", self._on_hist_back)
        self.fwd_btn = Gtk.Button(label="›")
        self.fwd_btn.add_css_class("roundbtn")
        self.fwd_btn.set_tooltip_text("Forward")
        self.fwd_btn.connect("clicked", self._on_hist_fwd)
        nav.append(self.back_btn)
        nav.append(self.fwd_btn)
        home.append(nav)
        self._view_history: list[str] = ["home"]
        self._hist_pos = 0
        self._update_hist_buttons()

        home.append(Gtk.Label(label="WHAT'S HOT", xalign=0))
        home.get_last_child().add_css_class("overline")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        t = Gtk.Label(label="Trending", xalign=0)
        t.add_css_class("h-trending")
        t.set_hexpand(True)
        head.append(t)
        home.append(head)
        home.append(self._build_hero())

        plhead = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        pl = Gtk.Label(label="Playlist", xalign=0)
        pl.add_css_class("h-pl")
        pl.set_hexpand(True)
        plhead.append(pl)
        showall = Gtk.Button(label="Show all")
        showall.add_css_class("flat")
        showall.add_css_class("more")
        showall.connect("clicked", lambda _b: self._go("songs"))
        plhead.append(showall)
        home.append(plhead)

        cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cols.add_css_class("colhead")
        for txt, w in (("#", 34), ("TITLE", -1), ("ARTIST", 150),
                       ("TIME", 56), ("ALBUM", 170)):
            lbl = Gtk.Label(label=txt, xalign=0)
            if w > 0:
                lbl.set_size_request(w, -1)
            else:
                lbl.set_hexpand(True)
            cols.append(lbl)
        home.append(cols)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.playlist = Gtk.ListBox()
        self.playlist.add_css_class("tracks")
        self.playlist.connect("row-activated", self._on_row)
        scroll.set_child(self.playlist)
        home.append(scroll)

        self._views["home"] = home
        self.stack.add_child(home)
        return main

    def _build_hero(self) -> Gtk.Widget:
        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        hero.add_css_class("hero")
        hero.set_hexpand(True)

        # Left side: glass panel with text content
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left.add_css_class("hero-text")
        left.set_hexpand(True)
        left.set_vexpand(True)
        left.set_valign(Gtk.Align.CENTER)
        left.set_margin_top(24)
        left.set_margin_bottom(24)
        left.set_margin_start(28)
        left.set_margin_end(24)

        kick = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        a = Gtk.Label(label="Top artist", xalign=0)
        a.set_hexpand(True)
        a.add_css_class("overline")
        kick.append(a)
        self.hero_stats = Gtk.Label(label="")
        self.hero_stats.add_css_class("hero-stats")
        kick.append(self.hero_stats)
        left.append(kick)

        self.hero_title = Gtk.Label(label="Your library", xalign=0)
        self.hero_title.add_css_class("hero-title")
        left.append(self.hero_title)

        cta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        play = Gtk.Button(label="▶  Play")
        play.add_css_class("btn-play")
        play.connect("clicked", self._on_hero_play)
        hero_shuffle = Gtk.Button(label="⇄  Shuffle")
        hero_shuffle.add_css_class("btn-ghost")
        hero_shuffle.set_tooltip_text("Play this artist shuffled")
        hero_shuffle.connect("clicked", self._on_hero_shuffle)
        cta.append(play)
        cta.append(hero_shuffle)
        left.append(cta)

        # Right side: artist artwork, framed inside the glass panel
        self.hero_bg = Gtk.Picture()
        self.hero_bg.set_content_fit(Gtk.ContentFit.COVER)
        self.hero_bg.set_hexpand(True)
        self.hero_bg.set_size_request(360, -1)
        self.hero_bg.set_margin_top(24)
        self.hero_bg.set_margin_end(24)
        self.hero_bg.set_margin_bottom(24)
        self.hero_bg.add_css_class("hero-art")

        hero.append(left)
        hero.append(self.hero_bg)

        self._hero_artist: str | None = None
        self._refresh_hero()
        return hero

    def _refresh_hero(self) -> None:
        top = self.store.top_artist()
        if top is None:
            self.hero_title.set_text("Your library")
            self.hero_stats.set_text("scan to begin")
            self._hero_artist = None
            self.hero_bg.set_paintable(None)
            return
        artist, ntracks, nplays = top
        self._hero_artist = artist
        self.hero_title.set_text(artist)
        self.hero_stats.set_text(
            f"{_plural(ntracks, 'track')} · {_plural(nplays, 'play')}")
        rep = self.store.tracks_for_artist(artist)
        thumb = thumb_for(rep[0].path, 600) if rep else None
        if thumb:
            self.hero_bg.set_filename(thumb)
        else:
            self.hero_bg.set_paintable(None)

    def _on_hero_play(self, _btn: Gtk.Button) -> None:
        if self._hero_artist:
            self._play_artist_name(self._hero_artist)
        else:
            self._play_from(0)

    def _on_hero_shuffle(self, _btn: Gtk.Button) -> None:
        if not self._hero_artist:
            self._play_from(0)
            return
        import random
        tracks = self.store.tracks_for_artist(self._hero_artist)
        if not tracks:
            return
        random.shuffle(tracks)
        self.engine.set_queue(tracks, 0)
        self.engine.play_index(0)
        self.toast.add_toast(
            Adw.Toast(title=f"Shuffling {self._hero_artist}"))



    # ================= right rail =================


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

    def _open_history(self, _btn: Gtk.Button) -> None:
        win = Gtk.Window(title="Play history", transient_for=self,
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
        plays = self.store.all_plays(200)
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
        self.store.clear_plays()
        self._last_played_path = None
        self._refresh_played()
        self._refresh_hero()
        win.destroy()
        self.toast.add_toast(Adw.Toast(title="Play history cleared"))

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
        self.rail.played_box.prepend(row)

    def _refresh_played(self) -> None:
        while (row := self.rail.played_box.get_first_child()):
            self.rail.played_box.remove(row)
        plays = self.store.recent_plays(8)
        if not plays:
            lbl = Gtk.Label(label=EMPTY_PLAYED)
            lbl.add_css_class("sub")
            self.rail.played_box.append(lbl)
            return
        for p in plays:
            self._add_played(p["title"], p["artist"], _ago(p["ts"]),
                             thumb_for(p["path"], 48))

    def _refresh_tags(self) -> None:
        while (c := self.rail.chips_flow.get_first_child()):
            self.rail.chips_flow.remove(c)
        genres = self.store.top_genres(4)
        if not genres:
            lbl = Gtk.Label(label=EMPTY_TAGS)
            lbl.add_css_class("sub")
            self.rail.chips_flow.append(lbl)
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
            chip.set_active(self._active_genre == genre)
            chip.connect("toggled", self._on_genre, genre)
            self.rail.chips_flow.append(chip)

    def _on_genre(self, btn: Gtk.ToggleButton, genre: str) -> None:
        if btn.get_active():
            self._active_genre = genre
            for sib in self._iter_flow(self.rail.chips_flow):
                if sib is not btn:
                    sib.set_active(False)
        else:
            self._active_genre = None
        self._apply_filter()

    @staticmethod
    def _iter_flow(flow: Gtk.FlowBox):
        child = flow.get_first_child()
        while child:
            inner = child.get_first_child()
            if isinstance(inner, Gtk.ToggleButton):
                yield inner
            child = child.get_next_sibling()

    def _refresh_songs_tags(self) -> None:
        while (c := self.songs_chips_flow.get_first_child()):
            self.songs_chips_flow.remove(c)
        genres = self.store.top_genres(12)
        if not genres:
            lbl = Gtk.Label(label=EMPTY_TAGS)
            lbl.add_css_class("sub")
            self.songs_chips_flow.append(lbl)
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
            chip.set_active(self._active_genre == genre)
            chip.connect("toggled", self._on_genre, genre)
            self.songs_chips_flow.append(chip)

    def _on_songs_search(self, entry: Gtk.SearchEntry) -> None:
        self._search_q = entry.get_text().strip().lower()
        self._apply_filter()
        # Mirror to main search entry
        if hasattr(self, "search"):
            self.search.set_text(entry.get_text())

    def _apply_filter(self) -> None:
        q = getattr(self, "_search_q", "")
        g = self._active_genre
        # Home view rows
        for track, row, _title in self.rows:
            ok_q = not q or q in (
                f"{track.title} {track.artist} {track.album}".lower())
            ok_g = not g or track.genre == g
            row.set_visible(ok_q and ok_g)
        # Songs view rows
        if hasattr(self, "_songs_box"):
            for child in self._songs_box:
                if isinstance(child, Gtk.ListBoxRow):
                    # Find the track for this row
                    # We need to track this differently - for now skip
                    pass

    def _on_fullscreen(self, _btn: Gtk.Button) -> None:
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    # ---------- queue panel ----------
    def _open_queue(self, _btn: Gtk.Button) -> None:
        # a destroyed window is only torn down once the event loop gets to
        # it, so fall back to the realized state to spot a stale handle
        if self._queue_win is not None:
            if self._queue_win.get_realized():
                self._queue_win.present()
                return
            self._queue_win = None
            self._queue_box = None
            self._queue_dragging = False
        win = Gtk.Window(title="Up next", transient_for=self, modal=True,
                         default_width=460, default_height=520)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        box = Gtk.ListBox()
        box.add_css_class("tracks")
        self._queue_win = win
        self._queue_box = box
        self._rebuild_queue(box)
        win.connect("destroy", self._on_queue_window_destroy)
        box.connect("row-activated", self._on_queue_row_activated)
        scroll.set_child(box)
        outer.append(scroll)
        hint = Gtk.Label(label="Drag to reorder · click to play", xalign=0)
        hint.add_css_class("sub")
        outer.append(hint)
        win.set_child(outer)
        win.present()

    def _on_queue_window_destroy(self, win: Gtk.Window) -> None:
        # covers both close-request and destroy(), so the singleton guard
        # is cleared however the panel goes away
        if self._queue_win is win:
            self._queue_win = None
            self._queue_box = None
            self._queue_dragging = False

    def _rebuild_queue(self, box: Gtk.ListBox) -> None:
        """Rebuild queue rows so row indexes match engine.queue."""
        while (child := box.get_first_child()) is not None:
            box.remove(child)
        queue = self.engine.queue
        cur = self.engine.index
        if not queue:
            box.append(Gtk.Label(label="Queue is empty — play something."))
            return
        for i, t in enumerate(queue):
            row = self._queue_row(t, i, i == cur)
            box.append(row)

    def _queue_row(self, t: Track, i: int, playing: bool) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        if playing:
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
        for wdg in (idx, title, artist):
            h.append(wdg)
        row.set_child(h)

        # DragSource only claims the pointer once the press moves past the
        # gesture threshold, so a plain click still reaches row-activated.
        src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        src.set_content(Gdk.ContentProvider.new_for_value(
            GObject.Value(GObject.TYPE_INT, i)))
        ghost = Gtk.Label(label=t.title)
        ghost.set_size_request(240, -1)
        ghost.set_ellipsize(Pango.EllipsizeMode.END)
        src.set_icon(Gtk.WidgetPaintable.new(ghost), 0.0, 0.0)
        src.connect("drag-begin", self._on_queue_drag_begin)
        src.connect("drag-end", self._on_queue_drag_end)
        src.connect("drag-cancel", self._on_queue_drag_end)
        row.add_controller(src)

        drop = Gtk.DropTarget.new(GObject.TYPE_INT, Gdk.DragAction.MOVE)
        drop.connect("enter", self._on_queue_drag_enter, row)
        drop.connect("leave", self._on_queue_drag_leave)
        drop.connect("drop", self._on_queue_drop, i)
        row.add_controller(drop)
        return row

    def _on_queue_drag_begin(self, _src, _x, _y) -> None:
        self._queue_dragging = True

    def _on_queue_drag_end(self, _src, _drag, _delete) -> None:
        self._queue_dragging = False

    def _on_queue_drag_enter(self, _drop, _val, _x, _y,
                             row: Gtk.ListBoxRow) -> Gdk.DragAction:
        row.add_css_class("q-drop")
        return Gdk.DragAction.MOVE

    def _on_queue_drag_leave(self, _drop) -> None:
        widget = _drop.get_widget()
        if isinstance(widget, Gtk.ListBoxRow):
            widget.remove_css_class("q-drop")

    def _on_queue_drop(self, _drop, value, _x, _y,
                       to_index: int) -> bool:
        box = self._queue_box
        if isinstance(value, GObject.Value):
            from_index = value.get_int()
        else:
            try:
                from_index = int(value)
            except (TypeError, ValueError):
                return False
        if from_index == to_index or not self.engine.move_in_queue(
                from_index, to_index):
            return False
        if box is not None:
            self._rebuild_queue(box)
        self._queue_dragging = False
        return True

    def _on_queue_row_activated(self, _box: Gtk.ListBox,
                                row: Gtk.ListBoxRow) -> None:
        # A completed drag also ends in a button release; ignore that one.
        if self._queue_dragging:
            self._queue_dragging = False
            return
        i = row.get_index()
        if i < 0:
            return
        self.engine.play_index(i)
        win, self._queue_win, self._queue_box = self._queue_win, None, None
        if win is not None:
            win.destroy()

    # ================= data =================
    def _sync_thread(self) -> None:
        try:
            counts = sync_library(self._roots, self.store)
        except Exception as exc:  # never die silently off-thread
            GLib.idle_add(self._on_scan_error, str(exc))
            return
        GLib.idle_add(self._on_sync, counts)

    def _on_scan_error(self, msg: str) -> bool:
        # no _on_sync will run, so don't leave persistence held forever
        self._queue_hold = False
        self.toast.add_toast(Adw.Toast(title=f"Library scan failed: {msg}"))
        return False

    def _on_sync(self, counts: dict) -> bool:
        tracks = self.store.all_tracks()
        # set_queue resets to the whole library; the saved queue replaces it
        self._queue_hold = True
        try:
            self._set_tracks(tracks)
            self._restore_queue()
        finally:
            self._queue_hold = False
        self._persist_queue()
        n = len(tracks)
        self._track_total = n
        self.sidebar.user_sub.set_text(self.sidebar._user_sub_text())
        if counts.get("added") or counts.get("removed"):
            bits = []
            if counts.get("added"):
                bits.append(f"{counts['added']} new")
            if counts.get("removed"):
                bits.append(f"{counts['removed']} gone")
            self.toast.add_toast(Adw.Toast(
                title=f"Library updated: {', '.join(bits)}"))
        if n == 0:
            self.toast.add_toast(Adw.Toast(
                title="No audio found — Load Music folder to start."))
        self._refresh_tags()
        self._refresh_played()
        self._refresh_hero()
        # drop cached secondary views AND their stack pages, or they leak
        # as orphans; rebuild the current one if the user is on it
        current = self._current_view
        for key in CACHE_VIEWS:
            page = self._views.pop(key, None)
            if page is not None and page.get_parent() is self.stack:
                self.stack.remove(page)
        if current in CACHE_VIEWS:
            self._show_view(current)
        if self._queue_win is not None and self._queue_box is not None:
            self._rebuild_queue(self._queue_box)  # queue panel stays in sync
        return False

    def _set_tracks(self, tracks: list[Track]) -> None:
        # Remember the currently playing track to preserve playback position
        current_track_path = None
        if self._playing_row is not None and self._playing_item is not None:
            _row, _title_label, _plain_text = self._playing_item
            # Find the track path from the _plain_text or we need to get it differently
            # Actually, let's get it from the engine's current queue
            pass
        
        # Get current track from engine if available
        try:
            current_queue = self.engine.queue()
            current_index = self.engine.play_index()
            if 0 <= current_index < len(current_queue):
                current_track = current_queue[current_index]
                current_track_path = current_track.path
        except Exception:
            current_track_path = None
        
        while (row := self.playlist.get_first_child()):
            self.playlist.remove(row)
        self.rows.clear()
        self._row_by_path.clear()
        self._row_items.clear()
        self._playing_row = None
        self._playing_item = None
        self.tracks = tracks
        for t in tracks:
            self._add_row(t)
        
        # Set queue and try to preserve current track
        self.engine.set_queue(tracks, 0)
        if current_track_path is not None and tracks:
            # Try to find the current track in the new queue
            for i, t in enumerate(tracks):
                if t.path == current_track_path:
                    self.engine.play_index(i)
                    break
        
        # Build search blobs for fuzzy search
        self._build_search_blobs(tracks)

    def _build_search_blobs(self, tracks: list[Track]) -> None:
        """Build a lowercase search blob for each track for fast searching."""
        self._search_blobs = {}
        for t in tracks:
            # Blob: title artist album genre, all lowercase
            blob = f"{t.title or ''} {t.artist or ''} {t.album or ''} {t.genre or ''}".lower()
            self._search_blobs[t.path] = blob

    def _add_row(self, track: Track, num: str | None = None,
                 time_str: str | None = None) -> None:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        idx = Gtk.Label(label=num or "")
        idx.set_size_request(34, -1)
        idx.add_css_class("idx")
        title = Gtk.Label(label=track.title, xalign=0)
        title.set_hexpand(True)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("tt")
        artist = Gtk.Label(label=track.artist, xalign=0)
        artist.set_size_request(150, -1)
        artist.set_ellipsize(Pango.EllipsizeMode.END)
        length = Gtk.Label(label=time_str or _fmt(track.length), xalign=1)
        length.set_size_request(56, -1)
        album = Gtk.Label(label=track.album, xalign=0)
        album.set_size_request(170, -1)
        album.set_ellipsize(Pango.EllipsizeMode.END)
        for w in (idx, title, artist, length, album):
            box.append(w)
        row.set_child(box)
        row.set_tooltip_text(track.path)
        self.playlist.append(row)
        self.rows.append((track, row, title))
        if track.path:
            self._row_by_path[track.path] = row
            self._row_items[track.path] = (row, title, track.title, length)
        if num is None:
            idx.set_text(f"{len(self.rows):02d}")

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        self._search_q = entry.get_text().strip().lower()
        self._apply_filter()
        # Navigate to search view and mirror the query
        self._go("search")
        if hasattr(self, '_search_entry'):
            self._search_entry.set_text(self._search_q)

    def _apply_filter(self) -> None:
        q = getattr(self, "_search_q", "")
        g = self._active_genre
        for track, row, _title in self.rows:
            ok_q = not q or q in (
                f"{track.title} {track.artist} {track.album}".lower())
            ok_g = not g or track.genre == g
            row.set_visible(ok_q and ok_g)

    def _pick_folder(self, _btn: Gtk.Button) -> None:
        dlg = Gtk.FileDialog(title="Choose music folder")
        dlg.select_folder(self, None, self._on_folder)

    def _on_folder(self, dlg: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
        try:
            folder = dlg.select_folder_finish(res)
        except GLib.Error:
            return
        path = folder.get_path()
        self._roots = [path]
        self.store.set_profile("music_roots", json.dumps([path]))
        self.toast.add_toast(Adw.Toast(title=f"Scanning {path} …"))
        threading.Thread(target=self._sync_thread, daemon=True).start()

    # ================= playback UI =================
    def _play_from(self, i: int) -> None:
        if not self.engine.queue:
            self.toast.add_toast(Adw.Toast(
                title="No local tracks — load a Music folder first"))
            return
        self.engine.play_index(i)

    def _on_row(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        i = row.get_index()
        if i < 0 or i >= len(self.tracks):
            self.toast.add_toast(Adw.Toast(
                title="Preview row — load a Music folder to play"))
            return
        self.engine.set_queue(self.tracks, 0)
        self.engine.play_index(i)

    def _on_engine_track(self, track: Track | None, playing: bool) -> None:
        self._sync_transport()
        # Update window title to show current track
        if track is not None and track.path:
            title = f"{track.title} - {track.artist}"
            if len(title) > 50:  # Truncate if too long
                title = title[:47] + "..."
            self.set_title(title)
        else:
            self.set_title("Aubade")
        
        new_row = (self._row_by_path.get(track.path)
                    if track is not None and track.path else None)
        if new_row is not self._playing_row:
            if self._playing_row is not None:
                self._playing_row.remove_css_class("playing")
            if self._playing_item is not None:
                _orow, _otitle, _oplain, *_orest = self._playing_item
                _otitle.set_text(_oplain)
                _otitle.remove_css_class("playing-title")
            self._playing_row = new_row
            self._playing_item = None
            if new_row is not None:
                new_row.add_css_class("playing")
            if track is not None and track.path:
                item = self._row_items.get(track.path)
                if item is not None:
                    self._playing_item = item
                    _irow, _ititle, _iplain, *_irest = item
                    _ititle.set_text(f"♪  {_iplain}")
                    _ititle.add_css_class("playing-title")
        if track is not None and track.path:
            self._sync_like_buttons()
            self.playerbar.bar_title.set_text(track.title)
            self.playerbar.bar_artist.set_text(f"{track.artist} · {track.album}")
            thumb = thumb_for(track.path, 200)
            if thumb:
                self.playerbar.bar_art.set_filename(thumb)
            else:
                self.playerbar.bar_art.set_paintable(None)
            self._refresh_nowcard()
            if playing:
                self._last_played_path = track.path
                self.store.record_play(track.path)
                self._refresh_played()
                self._refresh_hero()
                self.mpris.seeked()
                if self._np_built:
                    self._refresh_np()
        self.mpris.update()

    def _on_engine_error(self, msg: str) -> None:
        GLib.idle_add(self.toast.add_toast,
                      Adw.Toast(title=f"Playback error: {msg}"))

    def _on_like(self, btn: Gtk.ToggleButton) -> None:
        if getattr(self, "_in_like_sync", False):
            return
        cur = self.engine.current()
        if cur is None or not cur.path:
            btn.set_active(False)
            return
        self.store.set_like(cur.path, btn.get_active())
        if btn.get_active():
            self.liked.add(cur.path)
        else:
            self.liked.discard(cur.path)
        self._sync_like_buttons()

    def _sync_like_buttons(self) -> None:
        self._in_like_sync = True
        try:
            cur = self.engine.current()
            liked = bool(cur and cur.path and cur.path in self.liked)
            # Playerbar like button
            pb_like = getattr(self.playerbar, "like_btn", None)
            if pb_like is not None:
                pb_like.set_active(liked)
                pb_like.set_label("♥" if liked else "♡")
            # Nowplaying like button (if sheet is built)
            nowplaying = getattr(self, "nowplaying", None)
            if nowplaying is not None:
                np_like = getattr(nowplaying, "np_like", None)
                if np_like is not None:
                    np_like.set_active(liked)
                    np_like.set_label("♥" if liked else "♡")
            # Rail save button
            rail_save = getattr(self.rail, "nc_save", None)
            if rail_save is not None:
                rail_save.set_active(liked)
                rail_save.set_label("Saved  ♥" if liked else "Save  ♥")
        finally:
            self._in_like_sync = False

    def _play_from_nc(self) -> None:
        if self.engine.current() is None:
            self._play_from(0)
        else:
            self.engine.toggle()

    def _refresh_nowcard(self) -> None:
        track = self.engine.current()
        if track is None or not track.path:
            self.rail.nc_title.set_text("Nothing playing")
            self.rail.nc_artist.set_text("—")
            self.rail.nc_art.set_paintable(None)
            return
        self.rail.nc_title.set_text(track.title)
        self.rail.nc_artist.set_text(track.artist)
        thumb = thumb_for(track.path, 200)
        if thumb:
            self.rail.nc_art.set_filename(thumb)
        else:
            self.rail.nc_art.set_paintable(None)
        self._sync_like_buttons()

    def _on_share(self, _btn: Gtk.Button) -> None:
        cur = self.engine.current()
        if cur is None:
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set_text(f"{cur.title} — {cur.artist}")
        self.toast.add_toast(Adw.Toast(title="Copied to clipboard"))

    def _toggle_like_track(self, track) -> None:
        """Toggle like status for a specific track (not necessarily current)."""
        liked = track.path in self.liked
        self.store.set_like(track.path, not liked)
        if not liked:
            self.liked.add(track.path)
        else:
            self.liked.discard(track.path)
        # Sync all like buttons if it's the current track
        cur = self.engine.current()
        if cur and cur.path == track.path:
            self._sync_like_buttons()

    def _show_in_folder(self, track) -> None:
        """Open the containing folder in the file manager."""
        import os
        from urllib.parse import quote
        folder = os.path.dirname(track.path)
        try:
            Gio.AppInfo.launch_default_for_uri(
                "file://" + quote(folder), None)
        except Exception as exc:
            self.toast.add_toast(Adw.Toast(title=f"Can't open folder: {exc}"))

    def _remove_from_queue(self, track) -> None:
        """Remove a specific track from the queue."""
        for i, q in enumerate(self.engine.queue):
            if q.path == track.path:
                self.engine.remove_from_queue(i)
                self.toast.add_toast(Adw.Toast(title=f"Removed from queue"))
                break

    def _on_prev(self, _btn: Gtk.Button) -> None:
        self._log_skip()
        self.engine.prev()

    def _on_next(self, _btn: Gtk.Button) -> None:
        self._log_skip()
        self.engine.next()

    def _log_skip(self) -> None:
        cur = self.engine.current()
        if cur is not None and cur.path and self.engine.playing:
            if self.engine.position() < max(30.0,
                                           0.5 * (cur.length or 0.0)):
                self.store.record_skip(cur.path)








    def _set_volume(self, v: float) -> None:
        self.engine.set_volume(v)

    def _on_shuffle(self, btn: Gtk.ToggleButton) -> None:
        self.engine.shuffle = btn.get_active()
        self.store.set_profile(
            "shuffle", "1" if btn.get_active() else "0")
        self.mpris.update()

    def _on_repeat(self, btn: Gtk.ToggleButton) -> None:
        mode = self.engine.repeat_mode()
        # toggle button state maps: active => at least repeat-all
        if btn.get_active() and mode == "off":
            self.engine.toggle_repeat()
        elif not btn.get_active() and mode != "off":
            while self.engine.repeat_mode() != "off":
                self.engine.toggle_repeat()
        mode = self.engine.repeat_mode()
        btn.set_tooltip_text(f"Repeat: {mode}")
        self.store.set_profile("repeat", mode)
        self.mpris.update()







    def _tick(self) -> bool:
        if getattr(self, "_closed", False):
            return False
        # Safety net: backfill durations the tag scanner missed (e.g. old
        # '9/12'-style track numbers aborted the read before length).
        cur = self.engine.current()
        if cur is not None and cur.path and (cur.length or 0) <= 0:
            dur = self.engine.duration()
            if dur > 0:
                cur.length = dur
                try:
                    self.store.update_length(cur.path, dur)
                except Exception:
                    pass
                for t in self.tracks:
                    if t.path == cur.path:
                        t.length = dur
                        break
                item = self._row_items.get(cur.path)
                if item is not None and len(item) == 4:
                    item[3].set_text(_fmt(dur))
        # Update playerbar
        self.playerbar.tick()
        # Update nowplaying sheet if visible
        if self._np_built and self.appstack.get_visible_child_name() == "np":
            self.nowplaying.tick()
        return True
