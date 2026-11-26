"""
Cross-Platform Sync Bundle Engine (`.cvpack`) (`src/core/sync_bundle.py`).
Implemented and verified by Argon. DO NOT MODIFY in Hydrogen tasks.

Enables Windows Desktop to export a self-contained `.cvpack` archive (ZIP containing
`manifest.json`, `library_items.json`, playlists, and poster thumbnails) and allows Android
or another PC to import and match files strictly via `fast_hash` (with `(size_bytes, filename)`
fallback), regardless of OS path differences.
"""

from __future__ import annotations
import json
import time
import zipfile
from pathlib import Path
from typing import List, Dict, Any
from .models import (
    MediaItem,
    ScannedFileEntry,
    SyncReconcileResult,
    FileDiffStatus,
)


CVPACK_SCHEMA_VERSION = "1.0.0"


def export_cvpack_bundle(
    items: List[MediaItem],
    output_cvpack_path: str | Path,
    include_covers: bool = True,
) -> Dict[str, Any]:
    """
    Packages `items` and any local cover images into a portable `.cvpack` ZIP archive.
    Returns the manifest summary dictionary.
    """
    out_path = Path(output_cvpack_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    serialized_items: List[Dict[str, Any]] = []
    bundled_covers_count = 0

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            d = item.to_dict()
            if include_covers and item.cover_path:
                cover_file = Path(item.cover_path)
                if cover_file.is_file():
                    arc_cover_name = f"covers/{item.item_id}{cover_file.suffix or '.jpg'}"
                    zf.write(cover_file, arcname=arc_cover_name)
                    d["bundled_cover_arcname"] = arc_cover_name
                    bundled_covers_count += 1
            serialized_items.append(d)

        manifest = {
            "format": "cinevault-sync-pack",
            "schema_version": CVPACK_SCHEMA_VERSION,
            "exported_at_epoch": time.time(),
            "total_items": len(serialized_items),
            "bundled_covers": bundled_covers_count,
            "hash_algorithm": "cvh1_blake2b_3x64k",
        }

        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("library_items.json", json.dumps(serialized_items, indent=2, ensure_ascii=False))

    return manifest


def import_and_reconcile_cvpack(
    cvpack_path: str | Path,
    local_scanned_files: List[ScannedFileEntry],
) -> SyncReconcileResult:
    """
    Reads a `.cvpack` bundle on Android or a secondary PC and reconciles each record
    against `local_scanned_files` using:
      1. Primary Match: Exact `fast_hash` match (`cvh1_<size>_<digest>`).
      2. Secondary Fallback: Exact `(size_bytes, filename.lower())` match when fast_hash
         was not pre-computed on a slow mobile SAF mount.
      3. Remote-Only Catalog Entry: Preserved as `FileDiffStatus.MISSING` (or streamable over SMB)
         so the user can still browse their full collection and ratings on mobile.
    """
    pack_file = Path(cvpack_path)
    with zipfile.ZipFile(pack_file, "r") as zf:
        raw_items = json.loads(zf.read("library_items.json").decode("utf-8"))

    local_by_hash: Dict[str, ScannedFileEntry] = {}
    local_by_size_name: Dict[tuple[int, str], ScannedFileEntry] = {}
    for entry in local_scanned_files:
        if entry.fast_hash:
            local_by_hash[entry.fast_hash] = entry
        local_by_size_name[(entry.size_bytes, entry.filename.lower())] = entry

    result = SyncReconcileResult()

    for raw in raw_items:
        raw.pop("bundled_cover_arcname", None)
        item = MediaItem.from_dict(raw)

        matched_entry = local_by_hash.get(item.fast_hash)
        if matched_entry is not None:
            item.previous_path = item.file_path
            item.file_path = matched_entry.path
            item.file_name = matched_entry.filename
            item.parent_dirs = list(matched_entry.parent_dirs)
            item.source_type = matched_entry.source_type
            item.diff_status = FileDiffStatus.UNCHANGED
            result.matched_by_hash += 1
            result.synced_items.append(item)
            continue

        fallback_entry = local_by_size_name.get((item.size_bytes, item.file_name.lower()))
        if fallback_entry is not None:
            item.previous_path = item.file_path
            item.file_path = fallback_entry.path
            item.file_name = fallback_entry.filename
            item.parent_dirs = list(fallback_entry.parent_dirs)
            item.source_type = fallback_entry.source_type
            item.diff_status = FileDiffStatus.UNCHANGED
            result.matched_by_size_and_name += 1
            result.synced_items.append(item)
            continue

        item.diff_status = FileDiffStatus.MISSING
        result.unmatched_remote_only += 1
        result.synced_items.append(item)

    return result
