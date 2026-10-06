"""Local music library: scan + tag read (mutagen). Engine-agnostic.

Extension set mirrors Tauon's DA list (t_main.py Formats.DA), trimmed to
what GStreamer decodes out of the box on Fedora.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

AUDIO_EXTS = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus",
    ".m4a", ".m4b", ".aac", ".wav", ".aiff", ".aif",
    ".wv", ".ape", ".tta", ".wma",
}

STATE_PATH = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "aubade", "state.json",
)


@dataclass
class Track:
    path: str
    title: str
    artist: str = "Unknown artist"
    album: str = "Unknown album"
    album_artist: str = ""
    genre: str = ""
    length: float = 0.0
    mtime: float = 0.0
    disc_number: int = 0
    track_number: int = 0
    lyrics: str = ""
    synced: str = ""
    playable: bool = True

    @property
    def uri(self) -> str:
        from gi.repository import Gst
        return Gst.filename_to_uri(self.path)


def _safe_int(value) -> int:
    """Parse track/disc numbers tolerantly: '9', '9/12', None -> int."""
    if value is None:
        return 0
    text = str(value).strip().split("/")[0].strip()
    try:
        return int(text)
    except (ValueError, TypeError):
        return 0


def _read_tags(path: str) -> Track:
    name = os.path.splitext(os.path.basename(path))[0]
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    track = Track(path=path, title=name, mtime=mtime)
    try:
        from mutagen import File as MFile
        audio = MFile(path, easy=True)
        if audio is None:
            return track
        get = lambda k: (audio.get(k, [None])[0] or "").strip() or None
        track.title = get("title") or name
        track.artist = get("artist") or track.artist
        track.album = get("album") or track.album
        track.album_artist = get("albumartist") or get("album artist") or ""
        track.genre = (get("genre") or "").split(",")[0].strip()
        track.disc_number = _safe_int(get("discnumber") or get("disc"))
        track.track_number = _safe_int(get("tracknumber") or get("track"))
        if getattr(audio, "info", None) and getattr(audio.info, "length", None):
            track.length = float(audio.info.length)
    except Exception:
        pass
    try:
        from .lyrics import read_embedded
        static, synced = read_embedded(path)
        track.lyrics, track.synced = static, synced
    except Exception:
        pass
    return track


def sync_library(roots: list[str], store) -> dict:
    """Incremental sync: tag-read only new/changed files, drop missing.

    Returns {"added": n, "updated": n, "removed": n}. Slow I/O — call
    off the UI thread. `store` is a Store (duck-typed to avoid a cycle).
    """
    seen: set[str] = set()
    added = updated = 0
    # One-time repair: rows whose duration was never read (old int()
    # crash on '9/12'-style track numbers) get re-tagged even when the
    # mtime matches.
    try:
        retag_paths = set(store.zero_length_paths())
    except Exception:
        retag_paths = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() not in AUDIO_EXTS:
                    continue
                path = os.path.join(dirpath, fn)
                seen.add(path)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                known = store.known_mtime(path)
                if known is not None and abs(known - mtime) < 0.5:
                    if path not in retag_paths:
                        continue
                t = _read_tags(path)
                store.upsert_track(t.path, t.title, t.artist, t.album,
                                   t.album_artist, t.genre, t.length, t.mtime,
                                   t.disc_number, t.track_number,
                                   t.lyrics, t.synced)
                if known is None:
                    added += 1
                else:
                    updated += 1
    removed = store.remove_paths(store.all_paths() - seen)
    store.commit()
    return {"added": added, "updated": updated, "removed": removed}


def default_roots() -> list[str]:
    return [os.path.expanduser("~/Music")]


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        pass
