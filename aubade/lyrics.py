"""Lyrics: embedded tags -> .lrc sidecar -> DB cache -> network fallback.

Mirrors Tauon's chain (t_lyrics.py providers, t_tagscan.py detection,
t_main.py find_synced_lyric_data order): synced LRC preferred everywhere,
static text otherwise. Network hits LRCLIB (synced) then lyrics.ovh
(static); results land in SQLite, never written back to files.
"""
from __future__ import annotations

import os
import re
import time
from html import unescape

LRC_TIMESTAMP_RE = re.compile(r"\[\d+:\d{1,2}\.\d{2,3}\]")
LRCLIB_UA = "Aubade/0.1.0"


def is_synced(text: str) -> bool:
    return bool(text) and LRC_TIMESTAMP_RE.search(text) is not None


def read_embedded(path: str) -> tuple[str, str]:
    """(static_lyrics, synced_lrc) from tags, else ("", "")."""
    try:
        from mutagen import File as MFile
        audio = MFile(path)
        if audio is None:
            return "", ""
        ext = os.path.splitext(path)[1].lower()
        texts: list[str] = []
        if ext == ".mp3" and getattr(audio, "tags", None):
            for key in audio.tags.keys():
                if key.startswith("USLT"):
                    texts.append(str(audio.tags[key].text or ""))
        elif ext == ".flac":
            texts.extend(audio.get("LYRICS", []) or [])
            texts.extend(audio.get("UNSYNCED LYRICS", []) or [])
        elif ext in (".m4a", ".m4b") and getattr(audio, "tags", None):
            texts.extend(str(v) for v in (audio.tags.get("©lyr", []) or []))
        elif ext in (".opus", ".ogg", ".oga") and hasattr(audio, "get"):
            texts.extend(audio.get("LYRICS", []) or [])
            texts.extend(audio.get("UNSYNCEDLYRICS", []) or [])
        elif ext in (".ape", ".wv", ".tta") and hasattr(audio, "get"):
            texts.extend(audio.get("Lyrics", []) or [])
        static, synced = "", ""
        for t in texts:
            t = (t or "").strip()
            if not t:
                continue
            if is_synced(t) and not synced:
                synced = t
            elif not static:
                static = t
        return static, synced
    except Exception:
        return "", ""


def read_sidecar(path: str) -> str:
    """LRC text from a same-stem .lrc file next to the track, else ""."""
    base, _ = os.path.splitext(path)
    for cand in (base + ".lrc", base + ".LRC"):
        try:
            with open(cand, encoding="utf-8") as f:
                data = f.read()
            if is_synced(data):
                return data
        except (OSError, UnicodeError):
            continue
    return ""


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """[(seconds, line)] sorted, Tauon-style manual split (2/3-digit ms)."""
    out: list[tuple[float, str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "[" not in line:
            continue
        stamps = re.findall(r"\[(\d+):(\d{1,2})\.(\d{2,3})\]", line)
        if not stamps:
            continue
        words = re.sub(r"\[\d+:\d{1,2}\.\d{2,3}\]", "", line).strip()
        if not words:
            continue
        for mm, ss, ms in stamps:
            sec = int(mm) * 60 + int(ss)
            sec += int(ms) / 100 if len(ms) == 2 else int(ms) / 1000
            out.append((sec, words))
    out.sort(key=lambda e: e[0])
    return out


def _lrclib(artist: str, title: str) -> tuple[str, str]:
    try:
        import urllib.parse
        import urllib.request
        import json as _json
        q = urllib.parse.urlencode(
            {"track_name": title, "artist_name": artist})
        req = urllib.request.Request(
            f"https://lrclib.net/api/get?{q}",
            headers={"User-Agent": LRCLIB_UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status != 200:
                return "", ""
            j = _json.loads(r.read().decode("utf-8", "replace"))
        return j.get("plainLyrics") or "", j.get("syncedLyrics") or ""
    except Exception:
        return "", ""


def _ovh(artist: str, title: str) -> tuple[str, str]:
    try:
        import urllib.parse
        import urllib.request
        import json as _json
        q = urllib.parse.quote(f"{artist}/{title}")
        req = urllib.request.Request(
            f"https://api.lyrics.ovh/v1/{q}",
            headers={"User-Agent": LRCLIB_UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status != 200:
                return "", ""
            j = _json.loads(r.read().decode("utf-8", "replace"))
        return unescape(j.get("lyrics") or "").strip(), ""
    except Exception:
        return "", ""


def fetch_network(artist: str, title: str) -> tuple[str, str]:
    """LRCLIB first (synced), lyrics.ovh second (static)."""
    for fn in (_lrclib, _ovh):
        try:
            static, synced = fn(artist, title)
        except Exception:
            continue
        if static or synced:
            return static.strip(), synced.strip()
    return "", ""


def resolve_local(path: str, store) -> tuple[str, str, bool]:
    """Embedded -> sidecar -> DB cache. All local, safe on UI thread."""
    emb_static, emb_synced = store.embedded_lyrics(path)
    if emb_synced:
        return "", emb_synced, True
    sidecar = read_sidecar(path)
    if sidecar:
        return "", sidecar, True
    cached = store.cached_lyrics(path)
    if cached != (None, None):
        return cached[0], cached[1], True
    if emb_static:
        return emb_static, "", True
    return "", "", False


def resolve(path: str, artist: str, title: str, store) -> tuple[str, str]:
    """Full chain. `store` supplies cache + embedded fields (duck-typed)."""
    static, synced, found = resolve_local(path, store)
    if found:
        return static, synced
    static, synced = fetch_network(artist, title)
    if static or synced:
        store.save_lyrics(path, static, synced)
        return static, synced
    store.save_lyrics(path, "", "")
    return "", ""


def current_line(lines: list[tuple[float, str]], pos: float,
                 offset: float = 0.0) -> int:
    """Index of the last line with stamp <= pos + offset, else -1."""
    idx = -1
    target = pos + offset
    for i, (stamp, _words) in enumerate(lines):
        if stamp <= target:
            idx = i
        else:
            break
    return idx
