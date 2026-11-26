# Module Interface Contracts (`INTERFACE_CONTRACTS.md`)

All modules implemented by Hydrogen (`src/adapters/`) must strictly adhere to the following data structures, function signatures, and error conventions exported by `src/core/`.

---

## 1. Core Data Structures (`src/core/models.py`)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Any

class StorageSourceType(str, Enum):
    LOCAL_DISK = "local_disk"          # Local NTFS/exFAT/APFS/ext4 directory
    SAMBA_SMB = "samba_smb"            # UNC path (\\server\share) or smb:// mount
    CLOUD_MOUNT = "cloud_mount"        # Rclone / WebDAV / CloudDrive2 / Alist mount

class FileDiffStatus(str, Enum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    MOVED_OR_RENAMED = "moved_or_renamed"
    MODIFIED = "modified"
    MISSING = "missing"
    DUPLICATE = "duplicate"

class CoverSourceType(str, Enum):
    ONLINE_POSTER = "online_poster"
    LOCAL_SIDECAR = "local_sidecar"
    VIDEO_FRAME = "video_frame"
    PLACEHOLDER = "placeholder"

@dataclass
class ScannedFileEntry:
    path: str                          # Normalized absolute path or SMB URI
    filename: str                      # File basename with extension
    parent_dirs: List[str]             # Ordered ancestor folder names (root -> immediate parent)
    size_bytes: int                    # Exact byte size
    mtime_epoch: float                 # Last modified timestamp (seconds)
    source_type: StorageSourceType = StorageSourceType.LOCAL_DISK
    fast_hash: str = ""                # Populated by compute_fast_fingerprint()
    full_sha256: Optional[str] = None  # Optional full hash for archival verification

@dataclass
class ParsedMediaTokens:
    raw_path: str
    studio: Optional[str] = None
    title: Optional[str] = None
    performers: List[str] = field(default_factory=list)
    release_date: Optional[str] = None # ISO YYYY-MM-DD or YYYY
    resolution: Optional[str] = None   # e.g., "4K", "1080p", "720p"
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.0            # 0.0 to 1.0

@dataclass
class MediaItem:
    item_id: str                       # Deterministic ID derived from initial fast_hash
    file_path: str
    file_name: str
    parent_dirs: List[str]
    size_bytes: int
    mtime_epoch: float
    fast_hash: str
    source_type: StorageSourceType = StorageSourceType.LOCAL_DISK
    title: str = ""
    studio: str = ""
    performers: List[str] = field(default_factory=list)
    release_date: str = ""
    tags: List[str] = field(default_factory=list)
    user_keywords: List[str] = field(default_factory=list)
    rating: float = 0.0                # 0.0 to 5.0 in 0.5 increments
    rating_half_steps: int = 0         # 0 to 10 integer representation
    cover_path: str = ""
    cover_source: CoverSourceType = CoverSourceType.PLACEHOLDER
    duration_sec: float = 0.0
    play_count: int = 0
    last_played_pos_sec: float = 0.0
    playlists: List[str] = field(default_factory=list)
    is_incomplete: bool = True
    diff_status: FileDiffStatus = FileDiffStatus.UNCHANGED
    previous_path: Optional[str] = None
```

---

## 2. Core API Provided by Argon (Ready to Call)

### 2.1 `src/core/hasher.py`
- `compute_fast_fingerprint(file_path: str | Path, chunk_size: int = 65536) -> str`
  - Computes deterministic `cvh1_<size_hex>_<blake2b_32hex>` fingerprint in O(1) time (`<= 3 * 64KB` reads).
- `reconcile_library_state(existing_items: List[MediaItem], scanned_entries: List[ScannedFileEntry]) -> ReconciliationReport`
  - Matches scanned files against existing items by `fast_hash` and `file_path`, detecting `ADDED`, `MOVED_OR_RENAMED`, `MODIFIED`, `MISSING`, `DUPLICATE`, and `UNCHANGED` items while preserving user ratings and playback positions.

### 2.2 `src/core/parser.py`
- `parse_western_media_path(file_path: str, parent_dirs: Optional[List[str]] = None) -> ParsedMediaTokens`
  - Extracts Western Studio, Release Date, Performers, Scene Title, Resolution, and Genre Tags from both filename and ancestor directory names.

### 2.3 `src/core/metadata_engine.py`
- `enrich_media_item(item: MediaItem, provider_results: List[OnlineMetadataCandidate], local_sidecar_cover: Optional[str] = None) -> MediaItem`
- `compute_smart_frame_timestamp(duration_sec: float) -> List[float]`
- `generate_kodi_nfo_xml(item: MediaItem) -> str`

### 2.4 `src/core/ai_bridge.py`
- `export_root_markdown_keyword_db(items: List[MediaItem], output_md_path: str | Path) -> str`
- `import_root_markdown_completions(md_content: str, items_by_id: Dict[str, MediaItem]) -> int`
- `MCPServerEngine.handle_jsonrpc(request_dict: Dict[str, Any]) -> Dict[str, Any]`
- `build_interactive_ai_prompt(incomplete_items: List[MediaItem], language: str = "zh") -> str`

### 2.5 `src/core/sync_bundle.py`
- `export_cvpack_bundle(items: List[MediaItem], output_cvpack_path: str | Path, include_covers: bool = True) -> Dict[str, Any]`
- `import_and_reconcile_cvpack(cvpack_path: str | Path, local_scanned_files: List[ScannedFileEntry]) -> SyncReconcileResult`

### 2.6 `src/core/player_bridge.py`
- `detect_local_players(custom_vlc_path: Optional[str] = None) -> List[PlayerExecutable]`
- `build_vlc_launch_command(vlc_exe: str, video_path: str, start_time_sec: float = 0.0, fullscreen: bool = False) -> List[str]`
- `build_android_intent_uri(video_url_or_path: str, player_package: str = "org.videolan.vlc") -> str`
- `export_m3u8_playlist(items: List[MediaItem], output_path: str | Path) -> str`

---

## 3. Stub Interfaces Required from Hydrogen (`src/adapters/`)

### `[HYDROGEN-TASK-01]` `src/adapters/storage_smb_cloud.py`
- **Function**: `scan_storage_roots(roots: List[Dict[str, str]], compute_hashes: bool = True) -> List[ScannedFileEntry]`
- **Behavior**: Walk local paths, UNC/Samba paths (`\\server\share`), and Rclone/WebDAV mounted directories, filter video extensions (`VIDEO_EXTENSIONS`), and call `compute_fast_fingerprint()` on each file.

### `[HYDROGEN-TASK-02]` `src/adapters/sqlite_repo.py`
- **Class**: `SQLiteLibraryRepository(db_path: str)`
- **Methods**: `init_schema()`, `upsert_items(items: List[MediaItem]) -> int`, `load_all_items() -> List[MediaItem]`, `update_rating(item_id: str, rating: float) -> bool`, `update_user_keywords(item_id: str, keywords: List[str]) -> bool`.

### `[HYDROGEN-TASK-03]` `src/adapters/online_scrapers.py`
- **Class**: `OnlineMetadataScraper(api_token: Optional[str] = None, timeout_sec: float = 8.0)`
- **Method**: `search_candidates(tokens: ParsedMediaTokens, extra_keywords: List[str]) -> List[OnlineMetadataCandidate]`

### `[HYDROGEN-TASK-04]` `src/adapters/ffmpeg_runner.py`
- **Function**: `extract_fallback_cover_frame(video_path: str, output_jpg_path: str, duration_sec: float = 0.0, ffmpeg_bin: str = "ffmpeg") -> bool`
- **Behavior**: Call `compute_smart_frame_timestamp(duration_sec)` from `src/core/metadata_engine.py` and invoke `ffmpeg -ss <ts> -i <video_path> -frames:v 1 -q:v 2 <output_jpg_path>`.

### `[HYDROGEN-TASK-05]` `src/adapters/mcp_stdio_server.py`
- **Function**: `run_mcp_stdio_loop(engine: MCPServerEngine, input_stream, output_stream) -> int`
- **Behavior**: Read line-delimited JSON-RPC 2.0 messages from `input_stream`, pass each to `engine.handle_jsonrpc(req)`, and write JSON responses to `output_stream`.

### `[HYDROGEN-TASK-06]` `src/adapters/http_server.py`
- **Class**: `CineVaultLocalAPIHandler` / helper `handle_api_request(method: str, path: str, body: Optional[Dict[str, Any]], repo: SQLiteLibraryRepository) -> Tuple[int, Dict[str, Any]]`
- **Behavior**: Wire REST endpoints (`/api/library`, `/api/refresh`, `/api/rate`, `/api/keywords`, `/api/play/vlc`, `/api/ai/prompt`, `/api/sync/export`) to the Argon core modules.
