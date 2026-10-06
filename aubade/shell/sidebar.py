"""Aubade — shell components (sidebar, main, rail, playerbar, nowplaying)."""
from __future__ import annotations

import getpass




import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Gdk, Gtk

from .. import __app_id__



# ---------- nav ----------
MENU_NAV = [
    ("go-home", "folder-music", "Home"),
    ("compass", "system-search", "Discover"),
    ("view-grid", "folder", "Browse"),
    ("audio-speakers", "network-wireless", "Radio"),
    ("audio-input-microphone", "audio-speakers", "Podcasts"),
]
LIB_NAV = [
    ("media-optical", "folder-music", "Albums"),
    ("audio-x-generic", "folder-music", "Songs"),
    ("avatar-default", "system-users", "Artists"),
]
NAV_VIEWS = ["home", "discover", "browse", "radio", "podcasts",
             "albums", "songs", "artists"]
CACHE_VIEWS = ("albums", "songs", "artists", "discover", "browse",
               "radio", "podcasts", "search", "settings", "profile",
               "playlist", "album", "artist")

EMPTY_PLAYED = "Plays will appear here."
EMPTY_TAGS = "Genres from your files will appear here."
ICON_FALLBACK = "audio-x-generic"
SHARE_ICONS = ("document-send", "mail-send", "edit-copy", "emblem-shared")


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
    if sec is None or sec != sec or sec < 0:
        return "0:00"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _fmt_remain(sec: float) -> str:
    sec = max(0, int(sec or 0))
    return f"-{sec // 60}:{sec % 60:02d}"


# ============================================================================
# Sidebar
# ============================================================================

class Sidebar(Gtk.Box):
    """Left sidebar with navigation, search, and user profile."""

    def __init__(self, window: "AubadeWindow") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("sidebar")
        self.set_size_request(236, -1)
        self._window = window
        self._collapsed = False
        self._nav_labels: list[Gtk.Widget] = []
        self._nav_btns: list[Gtk.Button] = []
        self._build()

    def _build(self) -> None:
        # Traffic lights
        dots = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        dots.add_css_class("traffic")
        for cls, tip, action in (
            ("t-red", "Close", self._window.close),
            ("t-yellow", "Minimize", self._window.minimize),
            ("t-green", "Maximize", self._window._toggle_maximize)
        ):
            d = Gtk.Button()
            d.add_css_class("dot")
            d.add_css_class(cls)
            d.set_tooltip_text(tip)
            d.connect("clicked", lambda _b, fn=action: fn())
            dots.append(d)
        self.append(dots)

        # Logo
        logo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        logo.add_css_class("logo")
        self.logo_label = Gtk.Label()
        self.logo_label.set_markup('Aubade <span foreground="#ff6b8a">Music</span>')
        self.logo_label.add_css_class("wordmark")
        logo.append(self.logo_label)
        self.logo_box = logo
        self._nav_labels.append(self.logo_label)
        self.append(logo)

        # Search
        self.search = Gtk.SearchEntry(placeholder_text="Search ...")
        self.search.connect("search-changed", self._on_search)
        self.append(self.search)

        # Menu nav
        self.append(self._section_head("Menu"))
        self.menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.append(self.menu_box)
        for i, item in enumerate(MENU_NAV):
            self.menu_box.append(self._nav_btn(*item, active=(i == 0)))

        # Library nav
        self.append(self._section_head("Library"))
        lib_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.append(lib_box)
        for item in LIB_NAV:
            lib_box.append(self._nav_btn(*item))

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        self.append(spacer)

        # User profile
        user = Gtk.Button()
        user.add_css_class("usercard")
        user.add_css_class("flat")
        user.set_tooltip_text("Profile")
        user.connect("clicked", lambda _b: self._window._go("profile"))
        ubox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        username = self._window.display_name or getpass.getuser().title()
        self.user_avatar = Gtk.Label(label=(username[:1] or "?").upper())
        self.user_avatar.add_css_class("avatar")
        who = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.user_name = Gtk.Label(label=username, xalign=0)
        self.user_name.add_css_class("nm")
        self.user_sub = Gtk.Label(label="Local library", xalign=0)
        self.user_sub.add_css_class("sub")
        who.append(self.user_name)
        who.append(self.user_sub)
        self._nav_labels.append(who)
        ubox.append(self.user_avatar)
        ubox.append(who)
        user.set_child(ubox)
        self.append(user)

        # Collapse button
        collapse = Gtk.Button(label="‹")
        collapse.add_css_class("flat")
        collapse.set_tooltip_text("Collapse sidebar")
        collapse.connect("clicked", self._on_toggle)
        self.collapse_btn = collapse
        self.append(collapse)

    def _section_head(self, text: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.add_css_class("nav-h")
        lbl = Gtk.Label(label=text.upper(), xalign=0)
        lbl.add_css_class("overline")
        lbl.set_hexpand(True)
        box.append(lbl)
        self._nav_labels.append(box)
        return box

    def _nav_btn(self, icon: str, fallback: str, label: str, active: bool = False) -> Gtk.Widget:
        btn = Gtk.Button()
        btn.add_css_class("nav-item")
        if active:
            btn.add_css_class("active")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        img = _icon(icon, fallback)
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_hexpand(True)
        box.append(img)
        box.append(lbl)
        self._nav_labels.append(lbl)
        btn.set_child(box)
        btn.connect("clicked", self._on_nav, label.lower())
        self._nav_btns.append(btn)
        return btn

    def _on_nav(self, _btn: Gtk.Button, view: str) -> None:
        self._window._go(view)

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        self._window._search_q = entry.get_text().strip().lower()
        self._window._apply_filter()

    def _on_toggle(self, _btn: Gtk.Button) -> None:
        self._collapsed = not self._collapsed
        self.set_size_request(72 if self._collapsed else 236, -1)
        for w in self._nav_labels:
            w.set_visible(not self._collapsed)
        self.search.set_visible(not self._collapsed)
        self.logo_box.set_halign(Gtk.Align.CENTER if self._collapsed else Gtk.Align.START)
        self.collapse_btn.set_label("›" if self._collapsed else "‹")
        self._window.store.set_profile("sidebar_collapsed", "1" if self._collapsed else "0")

    def set_active(self, view: str) -> None:
        for nav, name in zip(self._nav_btns, NAV_VIEWS):
            if name == view:
                nav.add_css_class("active")
            else:
                nav.remove_css_class("active")

    def update_user(self, display_name: str, pronouns: str) -> None:
        self.display_name = display_name
        self.pronouns = pronouns
        shown = display_name or getpass.getuser().title()
        self.user_name.set_text(shown)
        self.user_avatar.set_text((shown[:1] or "?").upper())
        self.user_sub.set_text(self._user_sub_text())

    def _user_sub_text(self) -> str:
        bits = []
        if self._window.pronouns.strip():
            bits.append(self._window.pronouns.strip())
        bits.append(f"Local library · {self._window._track_total} tracks")
        return " · ".join(bits) if self._window.pronouns.strip() else bits[-1]