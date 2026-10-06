"""MPRIS2 D-Bus interface (org.mpris.MediaPlayer2) via Gio.

Lets GNOME/media keys see Aubade: play/pause/next/prev, track metadata
with cover art, volume/shuffle/repeat. Silently disables itself when no
session bus exists. All calls run on the GLib main thread.
"""
from __future__ import annotations

import os

from gi.repository import Gio, GLib

BUS_NAME = os.environ.get(
    "AUBADE_MPRIS_NAME", "org.mpris.MediaPlayer2.aubade")
OBJ_PATH = "/org/mpris/MediaPlayer2"

INTROSPECTION = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg name="Offset" type="x" direction="in"/></method>
    <method name="SetPosition">
      <arg name="TrackId" type="o" direction="in"/>
      <arg name="Position" type="x" direction="in"/>
    </method>
    <method name="OpenUri"><arg name="Uri" type="s" direction="in"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="read"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>"""


class MPRIS:
    def __init__(self, win) -> None:
        self.win = win
        self.enabled = False
        try:
            self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
            self._root = node.interfaces[0]
            self._player = node.interfaces[1]
            self.conn.register_object(
                OBJ_PATH, self._root, self._method,
                self._get_prop, self._set_prop)
            self.conn.register_object(
                OBJ_PATH, self._player, self._method,
                self._get_prop, self._set_prop)
            Gio.bus_own_name(
                Gio.BusType.SESSION, BUS_NAME,
                Gio.BusNameOwnerFlags.NONE, None,
                lambda *_a: setattr(self, "enabled", True),
                lambda *_a: setattr(self, "enabled", False))
            self.enabled = True
        except GLib.Error:
            self.enabled = False

    # ---------- D-Bus plumbing ----------
    def _method(self, _conn, _sender, _path, iface, method, params,
                invocation):
        try:
            eng = self.win.engine
            if iface == "org.mpris.MediaPlayer2":
                if method == "Raise":
                    self.win.present()
                elif method == "Quit":
                    app = self.win.get_application()
                    if app:
                        app.quit()
                invocation.return_value(None)
                return
            if method == "Next":
                eng.next()
            elif method == "Previous":
                eng.prev()
            elif method == "Pause":
                eng.pause()
            elif method == "Play":
                eng.play()
            elif method == "PlayPause":
                eng.toggle()
            elif method == "Stop":
                eng.stop()
            elif method == "Seek":
                eng.seek_sec(eng.position() + params[0] / 1e6)
                self.seeked()
            elif method == "SetPosition":
                eng.seek_sec(params[1] / 1e6)
                self.seeked()
            elif method == "OpenUri":
                self._open_uri(params[0])
            invocation.return_value(None)
        except Exception as exc:  # never break the bus
            invocation.return_dbus_error("dev.aubade.Error", str(exc))

    def _open_uri(self, uri: str) -> None:
        from urllib.parse import unquote, urlparse
        from .library import Track
        path = unquote(urlparse(uri).path) if "://" in uri else uri
        for i, t in enumerate(self.win.engine.queue):
            if t.path == path:
                self.win.engine.play_index(i)
                return
        track = None
        for t in self.win.tracks:
            if t.path == path:
                track = t
                break
        if track is None:
            from .library import _read_tags
            import os
            if os.path.isfile(path):
                track = _read_tags(path)
        if track is not None:
            self.win.engine.set_queue([track], 0)
            self.win.engine.play_index(0)

    def _get_prop(self, _conn, _sender, _path, iface, name):
        value = self._props(iface).get(name)
        if value is None:
            return None
        return GLib.Variant("(v)", (value,))

    def _set_prop(self, _conn, _sender, _path, iface, name, value):
        eng = self.win.engine
        if iface != "org.mpris.MediaPlayer2.Player":
            return False
        try:
            pyval = value.unpack()
        except Exception:
            return False
        if name == "Volume":
            eng.set_volume(float(pyval))
            self.win.vol_scale.set_value(
                eng.pipe.get_property("volume") * 100.0)
        elif name == "LoopStatus":
            eng.set_repeat_mode(
                {"None": "off", "Track": "one",
                 "Playlist": "all"}.get(str(pyval), "off"))
        elif name == "Shuffle":
            eng.shuffle = bool(pyval)
        else:
            return False
        self.update()
        try:
            self.win._sync_transport()
        except AttributeError:
            pass
        return True

    # ---------- state ----------
    def _props(self, iface: str) -> dict:
        eng = self.win.engine
        if iface == "org.mpris.MediaPlayer2":
            return {
                "CanQuit": GLib.Variant("b", True),
                "CanRaise": GLib.Variant("b", True),
                "HasTrackList": GLib.Variant("b", False),
                "Identity": GLib.Variant("s", "Aubade"),
                "DesktopEntry": GLib.Variant("s", "dev.aubade.Aubade"),
                "SupportedUriSchemes": GLib.Variant("as", ["file"]),
                "SupportedMimeTypes": GLib.Variant("as", [
                    "audio/mpeg", "audio/flac", "audio/ogg",
                    "audio/opus", "audio/mp4", "audio/x-wav",
                    "audio/x-aiff", "audio/x-wavpack", "audio/x-ape"]),
            }
        status = "Playing" if eng.playing else (
            "Paused" if eng.current() else "Stopped")
        return {
            "PlaybackStatus": GLib.Variant("s", status),
            "LoopStatus": GLib.Variant("s", {
                "off": "None", "one": "Track", "all": "Playlist"}[
                    eng.repeat_mode()]),
            "Rate": GLib.Variant("d", 1.0),
            "Shuffle": GLib.Variant("b", eng.shuffle),
            "Metadata": GLib.Variant("a{sv}", self._metadata()),
            "Volume": GLib.Variant(
                "d", float(eng.pipe.get_property("volume"))),
            "Position": GLib.Variant("x", int(eng.position() * 1e6)),
            "MinimumRate": GLib.Variant("d", 1.0),
            "MaximumRate": GLib.Variant("d", 1.0),
            "CanGoNext": GLib.Variant("b", bool(eng.queue)),
            "CanGoPrevious": GLib.Variant("b", bool(eng.queue)),
            "CanPlay": GLib.Variant("b", bool(eng.queue)),
            "CanPause": GLib.Variant("b", bool(eng.queue)),
            "CanSeek": GLib.Variant("b", True),
            "CanControl": GLib.Variant("b", True),
        }

    def _metadata(self) -> dict:
        from urllib.parse import quote
        eng = self.win.engine
        track = eng.current()
        if track is None or not track.path:
            return {"mpris:trackid": GLib.Variant(
                "o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")}
        from .art import thumb_for
        meta = {
            "mpris:trackid": GLib.Variant(
                "o", f"/dev/aubade/track/{max(0, eng.index)}"),
            "mpris:length": GLib.Variant(
                "x", int(max(0.0, eng.duration()) * 1e6)),
            "xesam:title": GLib.Variant("s", track.title),
            "xesam:artist": GLib.Variant("as", [track.artist]),
            "xesam:album": GLib.Variant("s", track.album),
            "xesam:url": GLib.Variant("s", track.uri),
        }
        try:
            thumb = thumb_for(track.path, 200)
        except Exception:
            thumb = None
        if thumb:
            meta["mpris:artUrl"] = GLib.Variant(
                "s", "file://" + quote(thumb))
        return meta

    # ---------- outward signals ----------
    def update(self) -> None:
        if not self.enabled:
            return
        try:
            props = {k: v for k, v in
                     self._props("org.mpris.MediaPlayer2.Player").items()
                     if k in ("PlaybackStatus", "Metadata", "Volume",
                              "Shuffle", "LoopStatus", "CanGoNext",
                              "CanGoPrevious", "CanPlay", "CanPause")}
            self.conn.emit_signal(
                None, OBJ_PATH, "org.freedesktop.DBus.Properties",
                "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", (
                    "org.mpris.MediaPlayer2.Player", props, [])))
        except GLib.Error:
            pass

    def seeked(self) -> None:
        if not self.enabled:
            return
        try:
            self.conn.emit_signal(
                None, OBJ_PATH, "org.mpris.MediaPlayer2.Player", "Seeked",
                GLib.Variant("(x)",
                             (int(self.win.engine.position() * 1e6),)))
        except GLib.Error:
            pass
