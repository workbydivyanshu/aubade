"""Cover-art pipeline, Tauon-style: embedded tags -> folder files -> subdirs.

Thumbnails are resized with Pillow LANCZOS and cached on disk per size,
so each image decodes exactly once. No network fetch for local files.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os

CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
    "aubade", "thumbs",
)
SIZES = (48, 200, 600)

PRIORITY_NAMES = ("folder", "cover", "front", "album", "artwork")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
ART_SUBDIRS = ("art", "scans", "covers", "cover", "images", "artwork")


def _embedded(path: str) -> bytes | None:
    """Raw image bytes from tags, or None. Mirrors Tauon get_embed()."""
    try:
        from mutagen import File as MFile
        audio = MFile(path)
        if audio is None:
            return None
        ext = os.path.splitext(path)[1].lower()
        if ext == ".mp3" and hasattr(audio, "tags") and audio.tags:
            for key in audio.tags.keys():
                if key.startswith("APIC"):
                    return bytes(audio.tags[key].data)
            return None
        if ext == ".flac" and hasattr(audio, "pictures") and audio.pictures:
            return bytes(audio.pictures[0].data)
        if ext in (".m4a", ".m4b") and "covr" in (audio.tags or {}):
            return bytes(audio.tags["covr"][0])
        if ext in (".ape", ".wv", ".tta") and hasattr(audio, "pictures"):
            pics = audio.pictures
            if pics:
                return bytes(pics[0].data)
        if ext in (".opus", ".ogg", ".oga"):
            pics = (audio.get("metadata_block_picture", [])
                    if hasattr(audio, "get") else [])
            if pics:
                import mutagen.flac
                pic = mutagen.flac.Picture(base64.b64decode(pics[0]))
                return bytes(pic.data)
    except Exception:
        pass
    return None


def _folder_art(path: str) -> str | None:
    """Best loose image file near the track, or None."""
    folder = os.path.dirname(path)
    candidates: list[str] = []

    def scan(d: str) -> None:
        try:
            files = os.listdir(d)
        except OSError:
            return
        ranked = []
        for fn in files:
            base, ext = os.path.splitext(fn)
            if ext.lower() not in IMAGE_EXTS:
                continue
            prio = 0 if base.lower() in PRIORITY_NAMES else 1
            ranked.append((prio, fn))
        ranked.sort()
        candidates.extend(os.path.join(d, fn) for _, fn in ranked)

    scan(folder)
    for sub in ART_SUBDIRS:
        scan(os.path.join(folder, sub))
    return candidates[0] if candidates else None


def get_art_source(path: str) -> tuple[str, str | bytes] | None:
    """('embedded', bytes) | ('file', filepath) | None."""
    data = _embedded(path)
    if data:
        return ("embedded", data)
    f = _folder_art(path)
    if f:
        return ("file", f)
    return None


def thumb_for(track_path: str, size: int = 200) -> str | None:
    """Cached JPEG thumbnail path at `size` px, or None if no art."""
    if size not in SIZES:
        size = min(SIZES, key=lambda s: abs(s - size))
    key = hashlib.md5(f"{track_path}".encode()).hexdigest()
    out = os.path.join(CACHE_DIR, str(size), f"{key}.jpg")
    if os.path.isfile(out):
        return out
    src = get_art_source(track_path)
    if src is None:
        return None
    try:
        from PIL import Image
        kind, payload = src
        if kind == "embedded":
            im = Image.open(io.BytesIO(payload if isinstance(payload, bytes) else payload))
        else:
            im = Image.open(payload)
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im.save(out, "JPEG", quality=90)
        return out
    except Exception:
        return None
