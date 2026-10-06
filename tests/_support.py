"""Shared fixtures for the Aubade smoke tests.

Import this module BEFORE any `aubade.*` import. It pins sys.path so the
package resolves regardless of cwd, and redirects XDG_DATA_HOME into a
throwaway sandbox so a stray default-path Store()/load_state() can never
touch the real ~/.local/share/aubade/library.db or ~/Music.

Everything here is stdlib only — no GTK, no network, no mutagen.
"""
from __future__ import annotations

import atexit
import os
import shutil
import struct
import sys
import tempfile
import unittest
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def bootstrap_path() -> None:
    """Make `aubade.*` and this helper importable no matter where we run from."""
    for entry in (ROOT, HERE):
        if entry not in sys.path:
            sys.path.insert(0, entry)


bootstrap_path()

# --- home isolation (must happen before importing aubade modules) -----------
SANDBOX = tempfile.mkdtemp(prefix="aubade-tests-xdg-")
atexit.register(shutil.rmtree, SANDBOX, ignore_errors=True)
PREV_XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME")
os.environ["XDG_DATA_HOME"] = SANDBOX


def _close_db(store) -> None:
    """Store has no close(); close the connection so GC emits no warning."""
    try:
        store.db.close()
    except Exception:
        pass


class TempDirTestCase(unittest.TestCase):
    """Base class: every test gets a private temp dir, removed afterwards."""

    def tmpdir(self, name: str = "work") -> str:
        path = tempfile.mkdtemp(prefix=f"aubade-tests-{name}-")
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def new_store(self, name: str = "library.db"):
        """Store() on a throwaway DB inside a temp dir. Never the real DB."""
        from aubade.store import Store
        store = Store(os.path.join(self.tmpdir("db"), name))
        self.addCleanup(_close_db, store)
        return store


# --- track helpers ---------------------------------------------------------

def add_track(store, path: str, title: str, artist: str = "Unknown artist",
              album: str = "Unknown album", album_artist: str = "",
              genre: str = "", length: float = 0.0, mtime: float = 0.0,
              disc_number: int = 0, track_number: int = 0,
              lyrics: str = "", synced: str = "") -> None:
    """upsert_track with defaults + commit (store.py never commits itself)."""
    store.upsert_track(path, title, artist, album, album_artist, genre,
                       length, mtime, disc_number, track_number,
                       lyrics, synced)
    store.commit()


def fake_track(title: str, playable: bool = True):
    """Track with a non-existent path — enough for queue logic, no audio."""
    from aubade.library import Track
    return Track(path=f"/nonexistent/aubade-tests/{title}.mp3",
                 title=title, playable=playable)


# --- media helpers ---------------------------------------------------------

def silent_wav(path: str, seconds: float = 1.0, rate: int = 8000) -> str:
    """Write a mono 16-bit silent WAV. mutagen can read its duration."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    frames = int(rate * seconds)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(struct.pack("<" + "h" * frames, *([0] * frames)))
    return path


def touch(path: str, text: str = "") -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path