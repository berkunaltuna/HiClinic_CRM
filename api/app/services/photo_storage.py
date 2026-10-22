"""Private storage for patient photos.

Uploads are written chunk by chunk to a temp file and atomically moved into place,
so a large photo never sits in application memory. Files are only ever read back
through authorised API endpoints; nothing here is served statically.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol

from app.core.config import settings

READ_CHUNK_BYTES = 64 * 1024

# --- Format detection ---------------------------------------------------------

FORMATS: dict[str, dict] = {
    "jpeg": {"ext": "jpg", "content_type": "image/jpeg", "extensions": {"jpg", "jpeg"}, "mimes": {"image/jpeg", "image/jpg", "image/pjpeg"}},
    "png": {"ext": "png", "content_type": "image/png", "extensions": {"png"}, "mimes": {"image/png"}},
    "webp": {"ext": "webp", "content_type": "image/webp", "extensions": {"webp"}, "mimes": {"image/webp"}},
    "heic": {"ext": "heic", "content_type": "image/heic", "extensions": {"heic", "heif"}, "mimes": {"image/heic", "image/heif", "image/heic-sequence", "image/heif-sequence"}},
}

_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}

# Bytes needed before the signature can be judged.
SNIFF_BYTES = 16


def detect_format(head: bytes) -> str | None:
    """Identify an image from its leading bytes (magic numbers), ignoring names and MIME types."""
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return "heic"
    return None


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def format_for_upload(filename: str, declared_mime: str) -> str | None:
    """The allowed format matching both the filename extension and the declared MIME type."""
    ext = extension_of(filename)
    mime = (declared_mime or "").split(";", 1)[0].strip().lower()
    for name in settings.photo_allowed_formats:
        spec = FORMATS.get(name)
        if spec and ext in spec["extensions"] and mime in spec["mimes"]:
            return name
    return None


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(filename: str) -> str:
    """Display-only copy of the patient's filename (never used as a path)."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return (_SAFE_NAME.sub("_", base).strip(" .") or "photo")[:120]


# --- Storage backends ---------------------------------------------------------


class PhotoWriter(Protocol):
    bytes_written: int

    def write(self, chunk: bytes) -> None: ...
    def commit(self, key: str) -> None: ...
    def abort(self) -> None: ...


class PhotoStorage(Protocol):
    def new_key(self, fmt: str) -> str: ...
    def open_writer(self) -> PhotoWriter: ...
    def iter_bytes(self, key: str) -> Iterator[bytes]: ...
    def size(self, key: str) -> int: ...
    def delete(self, key: str) -> None: ...


_KEY_RE = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{32}\.(jpg|png|webp|heic)$")


@dataclass
class _LocalWriter:
    root: Path
    tmp_path: Path
    fd: int
    bytes_written: int = 0
    sha256: "hashlib._Hash" = field(default_factory=hashlib.sha256)
    _closed: bool = False

    def write(self, chunk: bytes) -> None:
        view = memoryview(chunk)
        while view:
            n = os.write(self.fd, view)
            view = view[n:]
        self.bytes_written += len(chunk)
        self.sha256.update(chunk)

    def _close(self) -> None:
        if not self._closed:
            os.close(self.fd)
            self._closed = True

    def commit(self, key: str) -> None:
        os.fsync(self.fd)
        self._close()
        dest = LocalPhotoStorage.path_for(self.root, key)
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.replace(self.tmp_path, dest)

    def abort(self) -> None:
        self._close()
        try:
            self.tmp_path.unlink()
        except FileNotFoundError:
            pass


class LocalPhotoStorage:
    """Private directory storage (e.g. a docker volume). Directories 0700, files 0600."""

    def __init__(self, root: str):
        self.root = Path(root).resolve()

    @staticmethod
    def path_for(root: Path, key: str) -> Path:
        if not _KEY_RE.match(key):
            raise ValueError("Invalid storage key")
        return root / key

    def _ensure_dirs(self) -> Path:
        tmp = self.root / ".incoming"
        tmp.mkdir(mode=0o700, parents=True, exist_ok=True)
        return tmp

    def new_key(self, fmt: str) -> str:
        name = secrets.token_hex(16)
        return f"{name[:2]}/{name}.{FORMATS[fmt]['ext']}"

    def open_writer(self) -> _LocalWriter:
        tmp_path = self._ensure_dirs() / f"{secrets.token_hex(16)}.part"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        return _LocalWriter(root=self.root, tmp_path=tmp_path, fd=fd)

    def iter_bytes(self, key: str) -> Iterator[bytes]:
        with open(self.path_for(self.root, key), "rb") as fh:
            while chunk := fh.read(READ_CHUNK_BYTES):
                yield chunk

    def size(self, key: str) -> int:
        return self.path_for(self.root, key).stat().st_size

    def delete(self, key: str) -> None:
        try:
            self.path_for(self.root, key).unlink()
        except FileNotFoundError:
            pass


_storage: PhotoStorage | None = None


def get_photo_storage() -> PhotoStorage:
    global _storage
    if _storage is None:
        if settings.photo_storage_backend != "local":
            raise RuntimeError(f"Unsupported PHOTO_STORAGE_BACKEND: {settings.photo_storage_backend}")
        _storage = LocalPhotoStorage(settings.photo_storage_dir)
    return _storage


def set_photo_storage(storage: PhotoStorage | None) -> None:
    """Swap the backend (tests)."""
    global _storage
    _storage = storage
