"""
Multi-Source Storage Scanner Adapter (`src/adapters/storage_smb_cloud.py`).
Assigned to Hydrogen: `[HYDROGEN-TASK-01]`.
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from ..core.hasher import compute_fast_fingerprint
from ..core.models import ScannedFileEntry, StorageSourceType, VIDEO_EXTENSIONS

logger = logging.getLogger("cinevault.storage_smb_cloud")


def _walk_root_metadata(
    root_dir: str | Path,
    source_type: StorageSourceType,
) -> List[ScannedFileEntry]:
    """Walks a storage root and collects file stat metadata without hashing yet."""
    root_path = Path(root_dir)
    if not root_path.exists() or not root_path.is_dir():
        logger.warning("Storage root does not exist or is inaccessible: %s", root_dir)
        return []

    entries: List[ScannedFileEntry] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and d.upper() not in ("$RECYCLE.BIN", "SYSTEM VOLUME INFORMATION")
        )
        curr_dir = Path(dirpath)
        try:
            rel_parts = list(curr_dir.relative_to(root_path).parts)
        except ValueError:
            rel_parts = []
        parent_dirs = [root_path.name] + rel_parts if root_path.name else rel_parts

        for fname in sorted(filenames):
            if fname.startswith("."):
                continue
            if Path(fname).suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            full_file = curr_dir / fname
            try:
                st = full_file.stat()
                entries.append(
                    ScannedFileEntry(
                        path=str(full_file.resolve()),
                        filename=fname,
                        parent_dirs=parent_dirs,
                        size_bytes=st.st_size,
                        mtime_epoch=st.st_mtime,
                        source_type=source_type,
                        fast_hash="",
                    )
                )
            except OSError as exc:
                logger.warning("Skipped unreadable video file %s: %s", full_file, exc)
    return entries


# [HYDROGEN-TASK-01]
def scan_storage_roots(
    roots: List[Dict[str, str]],
    compute_hashes: bool = True,
    known_files: Optional[Dict[str, Tuple[int, float, str]]] = None,
    max_workers: int = 8,
) -> List[ScannedFileEntry]:
    """
    Scans multiple configured storage roots (Local Disks, Samba/SMB UNC shares, and Cloud Drive mounts).

    When `known_files` (`{resolved_path: (size_bytes, mtime_epoch, fast_hash)}`) is provided,
    unchanged files reuse their cached `fast_hash` without re-reading disk/NAS bytes.
    Remaining files are hashed concurrently using a thread pool.
    """
    all_entries: List[ScannedFileEntry] = []
    seen_paths: set[str] = set()

    for root_cfg in roots:
        raw_path = root_cfg.get("path", "").strip()
        if not raw_path:
            continue
        raw_type = root_cfg.get("source_type", StorageSourceType.LOCAL_DISK.value)
        try:
            stype = StorageSourceType(raw_type)
        except ValueError:
            stype = StorageSourceType.LOCAL_DISK

        scanned = _walk_root_metadata(raw_path, source_type=stype)
        for entry in scanned:
            if entry.path not in seen_paths:
                seen_paths.add(entry.path)
                all_entries.append(entry)

    if not compute_hashes or not all_entries:
        return all_entries

    to_hash: List[ScannedFileEntry] = []
    cache = known_files or {}
    for entry in all_entries:
        cached = cache.get(entry.path)
        if cached and cached[0] == entry.size_bytes and abs(cached[1] - entry.mtime_epoch) < 1e-3 and cached[2]:
            entry.fast_hash = cached[2]
        else:
            to_hash.append(entry)

    if to_hash:
        def _hash_one(ent: ScannedFileEntry) -> None:
            try:
                ent.fast_hash = compute_fast_fingerprint(ent.path)
            except OSError as exc:
                logger.warning("Failed to hash %s: %s", ent.path, exc)

        workers = min(max_workers, len(to_hash))
        if workers <= 1:
            for ent in to_hash:
                _hash_one(ent)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(_hash_one, to_hash))

    return all_entries
