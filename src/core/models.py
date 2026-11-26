"""
Strict Data Models & Invariants for CineVault Studio (`src/core/models.py`).
Implemented and verified by Argon. DO NOT MODIFY in Hydrogen tasks.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Optional, Any


VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts", ".mpg", ".mpeg", ".iso", ".strm"
}


class MediaCategory(str, Enum):
    WESTERN_ADULT = "western_adult"        # 欧美成人电影 / 厂牌场景 (Vixen, Blacked, Tushy, Brazzers, MetArt, etc.)
    JAPANESE_JAV = "japanese_jav"          # 日本成人电影 / 番号作品 (SSIS-001, IPX-888, STARS-707, FC2-PPV-1234567, etc.)
    MAINSTREAM_MOVIE = "mainstream_movie"  # 常规院线电影 (Dune, Oppenheimer, Interstellar, etc.)
    MAINSTREAM_TV = "mainstream_tv"        # 常规剧集 / 纪录片 (S01E01, Season 1, etc.)


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
    path: str
    filename: str
    parent_dirs: List[str]
    size_bytes: int
    mtime_epoch: float
    source_type: StorageSourceType = StorageSourceType.LOCAL_DISK
    fast_hash: str = ""
    full_sha256: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["source_type"] = self.source_type.value
        return d


@dataclass
class ParsedMediaTokens:
    raw_path: str
    media_category: MediaCategory = MediaCategory.WESTERN_ADULT
    jav_code: Optional[str] = None       # Standardized JAV ID e.g. "SSIS-001", "FC2-PPV-3109221"
    studio: Optional[str] = None
    is_unknown_studio: bool = False      # True when a studio/prefix is not yet in the known registry (triggers AI studio completion)
    raw_studio_token: Optional[str] = None
    title: Optional[str] = None
    performers: List[str] = field(default_factory=list)
    director: Optional[str] = None
    release_date: Optional[str] = None   # YYYY-MM-DD or YYYY
    resolution: Optional[str] = None     # 4K, 1080p, 720p, etc.
    season: Optional[int] = None         # Populated when media_category == MAINSTREAM_TV
    episode: Optional[int] = None        # Populated when media_category == MAINSTREAM_TV
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["media_category"] = self.media_category.value
        return d


@dataclass
class OnlineMetadataCandidate:
    provider: str                        # "ThePornDB", "StashDB", "JavDB", "FANZA", "TMDB", "OMDb"
    external_id: str
    title: str
    studio: str
    media_category: MediaCategory = MediaCategory.WESTERN_ADULT
    jav_code: str = ""
    performers: List[str] = field(default_factory=list)
    director: str = ""
    release_date: str = ""
    tags: List[str] = field(default_factory=list)
    cover_url: str = ""
    duration_sec: float = 0.0
    synopsis: str = ""
    imdb_id: str = ""
    tmdb_id: str = ""
    match_score: float = 0.0


@dataclass
class MediaItem:
    item_id: str
    file_path: str
    file_name: str
    parent_dirs: List[str]
    size_bytes: int
    mtime_epoch: float
    fast_hash: str
    media_category: MediaCategory = MediaCategory.WESTERN_ADULT
    source_type: StorageSourceType = StorageSourceType.LOCAL_DISK
    jav_code: str = ""                   # e.g. "SSIS-001", "IPZZ-102", "FC2-PPV-3109221"
    title: str = ""
    studio: str = ""
    is_unknown_studio: bool = False      # Flagged when studio/label is unrecorded and needs AI completion
    performers: List[str] = field(default_factory=list)
    director: str = ""
    release_date: str = ""
    resolution: str = ""
    season: Optional[int] = None
    episode: Optional[int] = None
    imdb_id: str = ""
    tmdb_id: str = ""
    tags: List[str] = field(default_factory=list)
    user_keywords: List[str] = field(default_factory=list)
    rating: float = 0.0                  # 0.0 to 5.0 in 0.5 increments
    rating_half_steps: int = 0           # 0 to 10 integer steps
    cover_path: str = ""
    cover_source: CoverSourceType = CoverSourceType.PLACEHOLDER
    duration_sec: float = 0.0
    play_count: int = 0
    last_played_pos_sec: float = 0.0
    playlists: List[str] = field(default_factory=list)
    is_incomplete: bool = True
    diff_status: FileDiffStatus = FileDiffStatus.UNCHANGED
    previous_path: Optional[str] = None
    synopsis: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.media_category, str):
            self.media_category = MediaCategory(self.media_category)
        if isinstance(self.source_type, str):
            self.source_type = StorageSourceType(self.source_type)
        if isinstance(self.cover_source, str):
            self.cover_source = CoverSourceType(self.cover_source)
        if isinstance(self.diff_status, str):
            self.diff_status = FileDiffStatus(self.diff_status)
        if self.rating > 0 and self.rating_half_steps == 0:
            self.set_rating(self.rating)
        elif self.rating_half_steps > 0 and self.rating == 0.0:
            self.rating = round(self.rating_half_steps * 0.5, 1)
        self.refresh_completeness()

    def set_rating(self, stars: float) -> None:
        """
        Enforces the 0.0 to 5.0 rating constraint with 0.5-star granularity (10 steps).
        Raises ValueError if out of range or not a multiple of 0.5.
        """
        if stars < 0.0 or stars > 5.0:
            raise ValueError(f"Rating must be between 0.0 and 5.0, got {stars}")
        half_steps = round(stars * 2.0)
        if abs(stars * 2.0 - half_steps) > 1e-6:
            raise ValueError(f"Rating must be in 0.5 star increments, got {stars}")
        self.rating_half_steps = int(half_steps)
        self.rating = round(self.rating_half_steps * 0.5, 1)

    def refresh_completeness(self) -> bool:
        """
        Evaluates completeness according to category:
        - WESTERN_ADULT: Requires known Studio (not `is_unknown_studio`), Title, Release Date, and >= 1 Performer.
        - JAPANESE_JAV: Requires `jav_code`, known Studio, Title, Release Date, and >= 1 Performer.
        - MAINSTREAM_MOVIE / MAINSTREAM_TV: Requires Title, Release Date (or Year), and (Studio/Director or >= 1 Cast).
        """
        if self.is_unknown_studio:
            self.is_incomplete = True
            return False

        if self.media_category in (MediaCategory.MAINSTREAM_MOVIE, MediaCategory.MAINSTREAM_TV):
            has_core = bool(
                self.title and self.title.strip()
                and self.release_date and self.release_date.strip()
                and (
                    (self.studio and self.studio.strip())
                    or (self.director and self.director.strip())
                    or len(self.performers) > 0
                )
            )
        elif self.media_category == MediaCategory.JAPANESE_JAV:
            has_core = bool(
                self.jav_code and self.jav_code.strip()
                and self.studio and self.studio.strip()
                and self.title and self.title.strip()
                and self.release_date and self.release_date.strip()
                and len(self.performers) > 0
            )
        else:
            has_core = bool(
                self.studio and self.studio.strip()
                and self.title and self.title.strip()
                and self.release_date and self.release_date.strip()
                and len(self.performers) > 0
            )
        self.is_incomplete = not has_core
        return not self.is_incomplete

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["media_category"] = self.media_category.value
        d["source_type"] = self.source_type.value
        d["cover_source"] = self.cover_source.value
        d["diff_status"] = self.diff_status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaItem":
        copied = dict(data)
        return cls(**copied)


@dataclass
class LibraryFilterCriteria:
    """
    Multi-dimensional filter & sort criteria supporting simultaneous filtering by:
    - `media_category`: "all", "western_adult", "japanese_jav", "mainstream"
    - `studio`: exact studio/maker filter
    - `performer`: exact actress/actor/cast filter
    - `tag`: genre or technical tag filter ("4K Ultra HD", "中文字幕", "Glamour", etc.)
    - `title_or_keyword`: substring search across title, JAV code, studio, performer, director, and user_keywords
    - `min_rating` / `max_rating` / `exact_rating`: half-star rating filters (0.0 to 5.0 in 0.5 steps)
    - `only_incomplete`: filter items missing metadata or with unrecorded new studios
    """
    media_category: str = "all"
    source_type: str = "all"
    studio: str = "all"
    performer: str = "all"
    tag: str = "all"
    title_or_keyword: str = ""
    min_rating: float = 0.0
    max_rating: float = 5.0
    exact_rating: Optional[float] = None
    only_incomplete: bool = False
    only_unknown_studio: bool = False
    sort_by: str = "release_date_desc"   # "release_date_desc", "rating_desc", "title_asc", "studio_asc"


@dataclass
class ReconciliationReport:
    unchanged: List[MediaItem] = field(default_factory=list)
    added: List[MediaItem] = field(default_factory=list)
    moved_or_renamed: List[MediaItem] = field(default_factory=list)
    modified: List[MediaItem] = field(default_factory=list)
    missing: List[MediaItem] = field(default_factory=list)
    duplicates: List[ScannedFileEntry] = field(default_factory=list)
    active_library: List[MediaItem] = field(default_factory=list)

    def summary_counts(self) -> Dict[str, int]:
        return {
            "unchanged": len(self.unchanged),
            "added": len(self.added),
            "moved_or_renamed": len(self.moved_or_renamed),
            "modified": len(self.modified),
            "missing": len(self.missing),
            "duplicates": len(self.duplicates),
            "active_total": len(self.active_library),
        }


@dataclass
class SyncReconcileResult:
    matched_by_hash: int = 0
    matched_by_size_and_name: int = 0
    unmatched_remote_only: int = 0
    synced_items: List[MediaItem] = field(default_factory=list)


@dataclass
class PlayerExecutable:
    name: str
    executable_path: str
    player_type: str = "vlc"             # "vlc", "potplayer", "mpv", "custom"
    supports_timestamp_arg: bool = True
