"""Save uploads, preserve folder structure, and extract archive files in-place."""

import io
import os
import pathlib
import shutil
import tarfile
import zipfile
from typing import BinaryIO, Iterable, Optional
from urllib.parse import quote

from werkzeug.utils import secure_filename

ARCHIVE_EXTENSIONS = frozenset(
    {
        ".zip",
        ".tar",
        ".tgz",
        ".tar.gz",
        ".tbz2",
        ".tar.bz2",
        ".txz",
        ".tar.xz",
    }
)


def _archive_suffix(name: str) -> Optional[str]:
    lower = name.lower().replace("\\", "/")
    for ext in sorted(ARCHIVE_EXTENSIONS, key=len, reverse=True):
        if lower.endswith(ext):
            return ext
    return None


def is_archive_filename(filename: str) -> bool:
    return _archive_suffix(filename) is not None


def normalize_upload_relative_path(filename: str) -> Optional[str]:
    """Return a safe relative path under the uploader folder, or None if invalid."""
    if not filename:
        return None
    raw = filename.replace("\\", "/").strip("/")
    if not raw or raw in (".", ".."):
        return None
    parts = []
    for part in raw.split("/"):
        part = part.strip()
        if not part or part in (".", ".."):
            return None
        safe = secure_filename(part)
        if not safe or safe in (".", ".."):
            return None
        parts.append(safe)
    return "/".join(parts) if parts else None


def _path_under_base(base: pathlib.Path, target: pathlib.Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _write_bytes(path: pathlib.Path, content: bytes, fernet) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fernet:
        path.write_bytes(fernet.encrypt(content))
    else:
        path.write_bytes(content)


def _extract_zip(stream: BinaryIO, dest_dir: pathlib.Path, fernet) -> None:
    with zipfile.ZipFile(stream) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = normalize_upload_relative_path(info.filename)
            if not rel:
                continue
            out = dest_dir / rel
            if not _path_under_base(dest_dir, out):
                continue
            _write_bytes(out, zf.read(info), fernet)


def _extract_tar(stream: BinaryIO, dest_dir: pathlib.Path, fernet) -> None:
    with tarfile.open(fileobj=stream, mode="r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            rel = normalize_upload_relative_path(member.name)
            if not rel:
                continue
            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            out = dest_dir / rel
            if not _path_under_base(dest_dir, out):
                continue
            _write_bytes(out, extracted.read(), fernet)


def extract_archive_bytes(content: bytes, filename: str, dest_dir: pathlib.Path, fernet) -> bool:
    """Extract archive bytes into dest_dir. Returns True if extraction ran."""
    suffix = _archive_suffix(filename)
    if not suffix:
        return False
    stream = io.BytesIO(content)
    try:
        if suffix == ".zip":
            _extract_zip(stream, dest_dir, fernet)
            return True
        stream.seek(0)
        _extract_tar(stream, dest_dir, fernet)
        return True
    except (zipfile.BadZipFile, tarfile.TarError, OSError):
        return False


def save_uploaded_file(
    upload_dir: pathlib.Path,
    relative_path: str,
    content: bytes,
    fernet,
) -> pathlib.Path:
    """Write a single file under upload_dir, preserving relative subfolders."""
    out = upload_dir / relative_path
    if not _path_under_base(upload_dir, out):
        raise ValueError("Invalid upload path")
    _write_bytes(out, content, fernet)
    return out


def archive_storage_name(filename: str) -> Optional[str]:
    """Archives are stored as a single file at the uploader folder root."""
    rel = normalize_upload_relative_path(filename)
    if not rel or not is_archive_filename(rel):
        return None
    return pathlib.Path(rel).name


def read_stored_file_bytes(path: pathlib.Path, fernet) -> bytes:
    data = path.read_bytes()
    if fernet:
        return fernet.decrypt(data)
    return data


def remove_bundle_artifacts(upload_dir: pathlib.Path, archive_name: str) -> None:
    """Remove a stored archive and any leftover extracted folder from older uploads."""
    zip_path = upload_dir / archive_name
    if zip_path.is_file():
        zip_path.unlink()
    stem = pathlib.Path(archive_name).stem
    dir_path = upload_dir / stem
    if dir_path.is_dir():
        shutil.rmtree(dir_path, ignore_errors=True)


def process_upload_item(
    upload_dir: pathlib.Path,
    filename: str,
    content: bytes,
    fernet,
) -> list[str]:
    """Save uploads. Folder archives stay as one zip file (not extracted on disk)."""
    rel = normalize_upload_relative_path(filename)
    if not rel:
        return []

    archive_name = archive_storage_name(filename)
    if archive_name:
        remove_bundle_artifacts(upload_dir, archive_name)
        out = save_uploaded_file(upload_dir, archive_name, content, fernet)
        return [archive_name]

    out = save_uploaded_file(upload_dir, rel, content, fernet)
    return [str(out.relative_to(upload_dir)).replace("\\", "/")]


def process_upload_batch(
    upload_dir: pathlib.Path,
    items: Iterable[tuple[str, bytes]],
    fernet,
) -> list[str]:
    """Process multiple (filename, content) uploads."""
    saved: list[str] = []
    for filename, content in items:
        saved.extend(process_upload_item(upload_dir, filename, content, fernet))
    return saved


def quote_rel_path(rel: str) -> str:
    return "/".join(quote(part) for part in rel.replace("\\", "/").split("/") if part)


def _directory_tree_stats(dir_path: pathlib.Path) -> tuple[int, int]:
    total_size = 0
    latest_mtime = 0
    try:
        st = dir_path.stat()
        latest_mtime = int(st.st_mtime)
    except OSError:
        pass
    for root, _dirs, names in os.walk(dir_path):
        for name in names:
            try:
                file_st = os.stat(os.path.join(root, name))
                total_size += int(file_st.st_size)
                latest_mtime = max(latest_mtime, int(file_st.st_mtime))
            except OSError:
                continue
    return total_size, latest_mtime


def build_directory_listing_items(
    disk_dir: pathlib.Path,
    folder: str,
    rel_prefix: str,
    can_delete: bool,
) -> list[dict]:
    """List files at this level. Archives (.zip, .tar, …) show as downloadable bundles."""
    items: list[dict] = []
    try:
        names = sorted(os.listdir(disk_dir), key=lambda n: n.lower())
    except OSError:
        return items

    for name in names:
        full = disk_dir / name
        if full.is_dir():
            continue
        if not full.is_file():
            continue

        rel = f"{rel_prefix}/{name}" if rel_prefix else name
        url_path = quote_rel_path(rel)
        try:
            stat = full.stat()
            size = int(stat.st_size)
            mtime = int(stat.st_mtime)
        except OSError:
            size = 0
            mtime = 0

        is_bundle = is_archive_filename(name)
        item = {
            "url": f"/uploads/{folder}/{url_path}",
            "download_url": f"/uploads/{folder}/{url_path}/download",
            "label": name,
            "size": size,
            "mtime": mtime,
        }
        if is_bundle:
            item["is_bundle"] = True
        if can_delete:
            item["delete_url"] = f"/uploads/{folder}/{url_path}/delete"
            item["delete_message"] = (
                "Delete this upload?"
                if is_bundle
                else "Delete this file?"
            )
        items.append(item)
    return items


def _read_file_for_zip(full: pathlib.Path, fernet) -> Optional[bytes]:
    try:
        data = full.read_bytes()
    except OSError:
        return None
    if not fernet:
        return data
    try:
        return fernet.decrypt(data)
    except Exception:
        # Extracted tree may contain plaintext files (e.g. nested paths).
        return data


def directory_to_zip_bytes(dir_path: pathlib.Path, fernet=None) -> bytes:
    """Build a zip archive from an on-disk directory (decrypting files when needed)."""
    buf = io.BytesIO()
    file_count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, names in os.walk(dir_path):
            for name in names:
                full = pathlib.Path(root) / name
                rel_arc = full.relative_to(dir_path).as_posix()
                data = _read_file_for_zip(full, fernet)
                if data is None:
                    continue
                zf.writestr(rel_arc, data)
                file_count += 1
    if file_count == 0:
        raise ValueError("No files available to include in archive")
    return buf.getvalue()


def build_uploads_breadcrumb(folder: str, rel_parts: list[str]) -> str:
    crumbs = [
        '<a href="/">Home</a>',
        '<a href="/uploads">Uploads</a>',
        f'<a href="/uploads/{quote(folder)}">{folder}</a>',
    ]
    acc: list[str] = []
    for part in rel_parts:
        acc.append(part)
        rel = "/".join(acc)
        crumbs.append(f'<a href="/uploads/{folder}/{quote_rel_path(rel)}">{part}</a>')
    return " / ".join(crumbs)
