"""
Reference Implementation: Local Directory Scanner (`src/adapters/reference_local_scanner.py`).
Completed by Argon as the canonical coding pattern for Hydrogen (`[HYDROGEN-TASK-01]`).
"""

from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import List
from ..core.models import VIDEO_EXTENSIONS, StorageSourceType, ScannedFileEntry
from ..core.hasher import compute_fast_fingerprint

logger = logging.getLogger("cinevault.scanner")


def scan_single_local_directory(
    root_dir: str | Path,
    source_type: StorageSourceType = StorageSourceType.LOCAL_DISK,
    compute_hashes: bool = True,
) -> List[ScannedFileEntry]:
    """
    Recursively walks a single directory root, filters video extensions, extracts relative
    parent directory hierarchy, and computes `fast_hash` via Argon's `compute_fast_fingerprint`.
    """
    root_path = Path(root_dir)
    if not root_path.exists() or not root_path.is_dir():
        logger.warning("Storage root does not exist or is inaccessible: %s", root_dir)
        return []

    entries: List[ScannedFileEntry] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Skip hidden directories (.git, .Trash, $RECYCLE.BIN, System Volume Information)
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
            ext = Path(fname).suffix.lower()
            if ext not in VIDEO_EXTENSIONS:
                continue
            full_file = curr_dir / fname
            try:
                st = full_file.stat()
                fhash = compute_fast_fingerprint(full_file) if compute_hashes else ""
                entries.append(
                    ScannedFileEntry(
                        path=str(full_file.resolve()),
                        filename=fname,
                        parent_dirs=parent_dirs,
                        size_bytes=st.st_size,
                        mtime_epoch=st.st_mtime,
                        source_type=source_type,
                        fast_hash=fhash,
                    )
                )
            except OSError as exc:
                logger.warning("Skipped unreadable video file %s: %s", full_file, exc)

    return entries
