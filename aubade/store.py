"""Aubade library store: SQLite cache + play/like/skip stats.

Instant startup from cache; background incremental sync fills it in.
No mock data lives here — empty DB means genuinely empty library.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

STATE_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "aubade",
)
DB_PATH = os.path.join(STATE_DIR, "library.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks(
  path TEXT PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL,
  album TEXT NOT NULL, album_artist TEXT NOT NULL DEFAULT '',
  genre TEXT NOT NULL DEFAULT '',
  length REAL NOT NULL DEFAULT 0, mtime REAL NOT NULL DEFAULT 0,
  added_ts REAL NOT NULL DEFAULT 0,
  disc_number INTEGER NOT NULL DEFAULT 0,
  track_number INTEGER NOT NULL DEFAULT 0,
  lyrics TEXT NOT NULL DEFAULT '', synced TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS plays(
  id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS skips(
  id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS likes(path TEXT PRIMARY KEY, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS profile(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS lyrics_cache(
  path TEXT PRIMARY KEY, static_text TEXT NOT NULL DEFAULT '',
  synced_text TEXT NOT NULL DEFAULT '', ts REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_plays_path_ts ON plays(path, ts);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album, artist);
"""


class Store:
    def __init__(self, path: str = DB_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # autocommit (isolation_level=None): the scan thread and the main thread
        # share one connection, and implicit transactions left open by one
        # thread made the other's write fail with "cannot start a
        # transaction within a transaction".
        self.db = sqlite3.connect(path, check_same_thread=False,
                                  isolation_level=None)
        self.db.row_factory = sqlite3.Row
        # serialise writes so scan + main thread cannot interleave
        # serialise writes so the scan thread and the main thread cannot interleave
        self._wlock = threading.Lock()
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        cols = {r["name"] for r in
                self.db.execute("PRAGMA table_info(tracks)")}
        if "lyrics" not in cols:
            self.db.execute("ALTER TABLE tracks ADD COLUMN lyrics TEXT NOT NULL DEFAULT ''")
        if "synced" not in cols:
            self.db.execute("ALTER TABLE tracks ADD COLUMN synced TEXT NOT NULL DEFAULT ''")

    # ---------- tracks ----------
    def upsert_track(self, path: str, title: str, artist: str, album: str,
                     album_artist: str, genre: str, length: float, mtime: float,
                     disc_number: int, track_number: int,
                     lyrics: str = "", synced: str = "") -> None:
        # one transaction per sync run: the scan can insert thousands of rows
        with self._txn():
            cur = self.db.execute("SELECT path, added_ts FROM tracks WHERE path=?",
                                  (path,))
            row = cur.fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO tracks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (path, title, artist, album, album_artist, genre, length, mtime,
                     time.time(), disc_number, track_number, lyrics, synced))
            else:
                self.db.execute(
                    """UPDATE tracks SET title=?, artist=?, album=?, album_artist=?, genre=?,
                       length=?, mtime=?, disc_number=?, track_number=?, lyrics=?, synced=? WHERE path=?""",
                    (title, artist, album, album_artist, genre, length, mtime,
                     disc_number, track_number, lyrics, synced, path))

    @contextmanager
    def _txn(self):
        """Explicit transaction held under the write lock, so a main-thread
        write never lands inside the scan's half-open one."""
        with self._wlock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")

    def commit(self) -> None:
        with self._wlock:
            if self.db.in_transaction:
                self.db.execute("COMMIT")

    def known_mtime(self, path: str) -> float | None:
        cur = self.db.execute("SELECT mtime FROM tracks WHERE path=?", (path,))
        row = cur.fetchone()
        return row["mtime"] if row else None

    def zero_length_paths(self) -> list[str]:
        """Paths whose duration was never read (repair pass for old bug)."""
        return [r["path"] for r in self.db.execute(
            "SELECT path FROM tracks WHERE length <= 0")]

    def update_length(self, path: str, length: float) -> None:
        self.db.execute("UPDATE tracks SET length=? WHERE path=?",
                        (length, path))
        self.db.commit()

    def all_paths(self) -> set[str]:
        return {r["path"] for r in
                self.db.execute("SELECT path FROM tracks")}

    def remove_paths(self, paths: set[str]) -> int:
        if not paths:
            return 0
        n = 0
        with self._txn():
            for p in paths:
                cur = self.db.execute("DELETE FROM tracks WHERE path=?", (p,))
                n += cur.rowcount
            self.db.execute(
                f"DELETE FROM plays WHERE path IN ({','.join('?' * len(paths))})",
                tuple(paths))
            self.db.execute(
                f"DELETE FROM likes WHERE path IN ({','.join('?' * len(paths))})",
                tuple(paths))
        return n

    def track_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"]

    def all_tracks(self):
        """Return Track-compatible rows ordered artist/album/title."""
        from .library import Track
        rows = self.db.execute(
            """SELECT path, title, artist, album, album_artist, genre, length, mtime,
                      lyrics, synced
               FROM tracks ORDER BY artist, album, title""")
        return [Track(path=r["path"], title=r["title"], artist=r["artist"],
                      album=r["album"], album_artist=r["album_artist"] or "",
                      genre=r["genre"], length=r["length"],
                      mtime=r["mtime"], lyrics=r["lyrics"] or "",
                      synced=r["synced"] or "") for r in rows]

    # ---------- events ----------
    def record_play(self, path: str) -> None:
        with self._txn():
            self.db.execute("INSERT INTO plays(path, ts) VALUES(?,?)",
                            (path, time.time()))

    def record_skip(self, path: str) -> None:
        with self._txn():
            self.db.execute("INSERT INTO skips(path, ts) VALUES(?,?)",
                            (path, time.time()))

    def toggle_like(self, path: str) -> bool:
        return self.set_like(path, not self.is_liked(path))

    def is_liked(self, path: str) -> bool:
        cur = self.db.execute("SELECT path FROM likes WHERE path=?", (path,))
        return cur.fetchone() is not None

    def set_like(self, path: str, liked: bool) -> None:
        if liked == self.is_liked(path):
            return
        with self._txn():
            if liked:
                self.db.execute("INSERT INTO likes VALUES(?,?)",
                                (path, time.time()))
            else:
                self.db.execute("DELETE FROM likes WHERE path=?", (path,))

    def liked_paths(self) -> set[str]:
        return {r["path"] for r in self.db.execute("SELECT path FROM likes")}

    def clear_plays(self) -> None:
        with self._txn():
            self.db.execute("DELETE FROM plays")
            self.db.execute("DELETE FROM skips")

    def all_plays(self, limit: int = 200):
        return self.db.execute(
            """SELECT t.title, t.artist, t.path, MAX(p.ts) ts,
                      COUNT(p.id) times
               FROM plays p JOIN tracks t ON t.path = p.path
               GROUP BY p.path ORDER BY ts DESC LIMIT ?""",
            (limit,)).fetchall()

    # ---------- lyrics ----------
    def embedded_lyrics(self, path: str) -> tuple[str, str]:
        cur = self.db.execute(
            "SELECT lyrics, synced FROM tracks WHERE path=?", (path,))
        row = cur.fetchone()
        if row:
            return row["lyrics"] or "", row["synced"] or ""
        return "", ""

    def cached_lyrics(self, path: str) -> tuple:
        cur = self.db.execute(
            "SELECT static_text, synced_text FROM lyrics_cache WHERE path=?",
            (path,))
        row = cur.fetchone()
        if row is None:
            return (None, None)
        return row["static_text"] or "", row["synced_text"] or ""

    def save_lyrics(self, path: str, static: str, synced: str) -> None:
        with self._txn():
            self.db.execute(
                "INSERT INTO lyrics_cache(path, static_text, synced_text, ts)"
                " VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET"
                " static_text=excluded.static_text,"
                " synced_text=excluded.synced_text, ts=excluded.ts",
                (path, static, synced, time.time()))

    # ---------- profile ----------
    def get_profile(self, key: str, default: str = "") -> str:
        cur = self.db.execute("SELECT value FROM profile WHERE key=?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

    def set_profile(self, key: str, value: str) -> None:
        with self._txn():
            self.db.execute(
                "INSERT INTO profile(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))

    # ---------- queue (ordered paths + current index, one transaction) ----------
    def save_queue(self, paths: list[str], index: int) -> None:
        with self._txn():
            self.db.executemany(
                "INSERT INTO profile(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [("queue_paths",
                  json.dumps(list(paths), separators=(",", ":"))),
                 ("queue_index", str(int(index)))])

    def load_queue(self) -> tuple[list[str], int]:
        """Saved queue paths + current index; unusable values come back empty."""
        rows = {r["key"]: r["value"] for r in self.db.execute(
            "SELECT key, value FROM profile"
            " WHERE key IN ('queue_paths', 'queue_index')")}
        try:
            paths = json.loads(rows.get("queue_paths") or "[]")
        except ValueError:
            paths = []
        if not isinstance(paths, list):
            paths = []
        paths = [p for p in paths if isinstance(p, str)]
        try:
            index = int(rows.get("queue_index") or -1)
        except ValueError:
            index = -1
        return paths, index

    # ---------- derived stats (all real, may be empty) ----------
    def recent_plays(self, limit: int = 8):
        return self.db.execute(
            """SELECT t.title, t.artist, t.path, MAX(p.ts) ts
               FROM plays p JOIN tracks t ON t.path = p.path
               GROUP BY p.path ORDER BY ts DESC LIMIT ?""",
            (limit,)).fetchall()

    def top_artist(self):
        """(artist, track_count, play_count) by plays, fallback most tracks."""
        row = self.db.execute(
            """SELECT t.artist, COUNT(DISTINCT t.path) tracks,
                      COUNT(p.id) plays
               FROM tracks t LEFT JOIN plays p ON p.path = t.path
               GROUP BY t.artist ORDER BY plays DESC, tracks DESC LIMIT 1"""
        ).fetchone()
        if row and (row["plays"] or row["tracks"]):
            return row["artist"], row["tracks"], row["plays"]
        return None

    def top_album(self, days: float = 7):
        """Most-played album in window; fallback: most recently added."""
        row = self.db.execute(
            """SELECT t.album, t.artist, COUNT(p.id) plays
               FROM tracks t JOIN plays p ON p.path = t.path
               WHERE p.ts > ? AND t.album != 'Unknown album'
               GROUP BY t.album, t.artist ORDER BY plays DESC LIMIT 1""",
            (time.time() - days * 86400,)).fetchone()
        if row:
            return row["album"], row["artist"]
        row = self.db.execute(
            """SELECT album, artist FROM tracks WHERE album != 'Unknown album'
               ORDER BY added_ts DESC LIMIT 1""").fetchone()
        if row:
            return row["album"], row["artist"]
        return None

    def top_genres(self, limit: int = 4):
        return [(r["genre"], r["c"]) for r in self.db.execute(
            """SELECT genre, COUNT(*) c FROM tracks
               WHERE genre != '' GROUP BY genre ORDER BY c DESC LIMIT ?""",
            (limit,))]

    def all_genres(self, limit: int = 60):
        return self.top_genres(limit)

    def tracks_for_genre(self, genre: str):
        from .library import Track
        rows = self.db.execute(
            """SELECT path, title, artist, album, genre, length, mtime,
                      lyrics, synced FROM tracks WHERE genre=?
               ORDER BY artist, album, title""", (genre,))
        return [self._row_track(r) for r in rows]

    def all_tracks_sorted(self, key: str = "artist"):
        from .library import Track
        order = {
            "title": "title, artist",
            "artist": "artist, album, title",
            "album": "album, artist, title",
            "added": "added_ts DESC",
        }.get(key, "artist, album, title")
        rows = self.db.execute(
            f"""SELECT path, title, artist, album, genre, length, mtime,
                       lyrics, synced FROM tracks ORDER BY {order}""")
        return [Track(path=r["path"], title=r["title"], artist=r["artist"],
                      album=r["album"], genre=r["genre"], length=r["length"],
                      mtime=r["mtime"], lyrics=r["lyrics"] or "",
                      synced=r["synced"] or "") for r in rows]

    def recent_added(self, limit: int = 20):
        from .library import Track
        rows = self.db.execute(
            """SELECT path, title, artist, album, genre, length, mtime,
                      lyrics, synced FROM tracks
               ORDER BY added_ts DESC LIMIT ?""", (limit,))
        return [self._row_track(r) for r in rows]

    def most_played_tracks(self, limit: int = 20):
        from .library import Track
        rows = self.db.execute(
            """SELECT t.path, t.title, t.artist, t.album, t.genre,
                      t.length, t.mtime, t.lyrics, t.synced, COUNT(p.id) n
               FROM tracks t JOIN plays p ON p.path = t.path
               GROUP BY t.path ORDER BY n DESC LIMIT ?""", (limit,))
        return [self._row_track(r) for r in rows]

    def liked_tracks_list(self):
        from .library import Track
        rows = self.db.execute(
            """SELECT t.path, t.title, t.artist, t.album, t.genre,
                      t.length, t.mtime, t.lyrics, t.synced
               FROM tracks t JOIN likes l ON l.path = t.path
               ORDER BY l.ts DESC""")
        return [self._row_track(r) for r in rows]

    def counts(self) -> dict:
        plays = self.db.execute("SELECT COUNT(*) c FROM plays").fetchone()["c"]
        likes = self.db.execute("SELECT COUNT(*) c FROM likes").fetchone()["c"]
        return {"tracks": self.track_count(), "plays": plays,
                "likes": likes}

    def albums(self):
        """Albums grouped by album name, using album artist when available.
        Filters out 'Unknown album' and groups compilation albums properly."""
        return self.db.execute(
            """SELECT album, COALESCE(NULLIF(album_artist, ''), artist) AS album_artist,
                      COUNT(*) c, MAX(added_ts) added
               FROM tracks WHERE album != 'Unknown album' AND album != ''
               GROUP BY album, album_artist
               ORDER BY album_artist, album""").fetchall()

    def artists(self):
        return self.db.execute(
            """SELECT artist, COUNT(*) c, COUNT(p.id) plays
               FROM tracks t LEFT JOIN plays p ON p.path = t.path
               GROUP BY artist ORDER BY plays DESC, c DESC""").fetchall()

    def tracks_for_artist(self, artist: str):
        from .library import Track
        rows = self.db.execute(
            "SELECT * FROM tracks WHERE artist=? ORDER BY album, title",
            (artist,))
        return [self._row_track(r) for r in rows]

    def album_tracks(self, album: str, album_artist: str):
        """All tracks for a specific album (by album name + album artist)."""
        from .library import Track
        rows = self.db.execute(
            """SELECT path, title, artist, album, album_artist, genre, length, mtime,
                      lyrics, synced FROM tracks
               WHERE album=? AND COALESCE(NULLIF(album_artist, ''), artist)=?
               ORDER BY disc_number, track_number, title""",
            (album, album_artist))
        return [self._row_track(r) for r in rows]

    def first_track_path(self, album: str, album_artist: str) -> str | None:
        cur = self.db.execute(
            "SELECT path FROM tracks WHERE album=? AND COALESCE(NULLIF(album_artist, ''), artist)=? LIMIT 1",
            (album, album_artist))
        row = cur.fetchone()
        return row["path"] if row else None

    @staticmethod
    def _row_track(r):
        from .library import Track
        keys = r.keys()
        return Track(path=r["path"], title=r["title"], artist=r["artist"],
                     album=r["album"], album_artist=r["album_artist"] if "album_artist" in keys else "",
                     genre=r["genre"], length=r["length"],
                     mtime=r["mtime"],
                     lyrics=r["lyrics"] if "lyrics" in keys else "",
                     synced=r["synced"] if "synced" in keys else "")
