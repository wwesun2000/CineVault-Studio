"""
Local REST API Dispatcher & HTTP Range Video Server (`src/adapters/http_server.py`).
Assigned to Hydrogen: `[HYDROGEN-TASK-06]`.
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

from ..core.ai_bridge import (
    build_interactive_ai_prompt,
    export_root_markdown_keyword_db,
    import_root_markdown_completions,
)
from ..core.hasher import reconcile_library_state
from ..core.metadata_engine import enrich_media_item, filter_and_search_library
from ..core.models import CoverSourceType, FileDiffStatus, LibraryFilterCriteria, MediaItem
from ..core.parser import (
    apply_parsed_tokens_to_item,
    normalize_studio_name,
    parse_western_media_path,
    register_custom_studio,
)
from ..core.player_bridge import (
    build_android_intent_uri,
    build_vlc_launch_command,
    detect_local_players,
)
from ..core.sync_bundle import export_cvpack_bundle, import_and_reconcile_cvpack
from .ffmpeg_runner import extract_fallback_cover_frame, find_ffmpeg_binary, probe_video_duration_sec
from .online_scrapers import OnlineMetadataScraper
from .sqlite_repo import SQLiteLibraryRepository
from .storage_smb_cloud import scan_storage_roots


DEFAULT_CONFIG: Dict[str, Any] = {
    "storage_roots": [],
    "vlc_executable": "",
    "theporndb_token": "",
    "tmdb_api_key": "",
    "auto_extract_frames": False,
}

_REFRESH_LOCK = threading.Lock()
REFRESH_STATUS: Dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "total": 0,
    "processed": 0,
    "message": "",
    "elapsed_sec": 0.0,
    "summary": {},
}


def _set_refresh_status(**kwargs: Any) -> None:
    with _REFRESH_LOCK:
        REFRESH_STATUS.update(kwargs)


def get_refresh_status() -> Dict[str, Any]:
    with _REFRESH_LOCK:
        return dict(REFRESH_STATUS)


def resolve_app_root() -> Path:
    """Returns the writable runtime root (executable dir when frozen, repo root in dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def resolve_bundle_root() -> Path:
    """Returns the read-only bundled resource root (`sys._MEIPASS` when frozen)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent.parent


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = config_path or (resolve_app_root() / "config.json")
    cfg = dict(DEFAULT_CONFIG)
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    if not isinstance(cfg.get("storage_roots"), list):
        cfg["storage_roots"] = []
    return cfg


def save_config(config: Dict[str, Any], config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = config_path or (resolve_app_root() / "config.json")
    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    roots = []
    for r in merged.get("storage_roots") or []:
        if isinstance(r, dict) and str(r.get("path", "")).strip():
            roots.append(
                {
                    "path": str(r["path"]).strip(),
                    "source_type": str(r.get("source_type") or "local_disk").strip(),
                }
            )
    merged["storage_roots"] = roots
    merged["vlc_executable"] = str(merged.get("vlc_executable") or "").strip()
    merged["theporndb_token"] = str(merged.get("theporndb_token") or "").strip()
    merged["tmdb_api_key"] = str(merged.get("tmdb_api_key") or "").strip()
    merged["auto_extract_frames"] = bool(merged.get("auto_extract_frames", False))
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return merged


def _download_cover_to_local(url: str, dest_file: Path, timeout_sec: float = 10.0) -> bool:
    """Downloads an online poster URL to `dest_file` inside `.cinevault_covers/`."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    if dest_file.is_file() and dest_file.stat().st_size > 0:
        return True
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CineVaultStudio/1.2", "Accept": "image/*,*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = resp.read()
            if data and len(data) > 256:
                dest_file.write_bytes(data)
                return True
    except Exception:
        return False
    return False


def _find_local_sidecar_cover_file(video_path: str) -> Optional[Path]:
    p = Path(video_path)
    parent = p.parent
    if not parent.is_dir():
        return None
    stem = p.stem
    candidates = [
        f"{stem}.jpg", f"{stem}.jpeg", f"{stem}.png", f"{stem}.webp",
        f"{stem}-poster.jpg", f"{stem}-poster.png",
        "poster.jpg", "poster.png", "cover.jpg", "cover.png", "fanart.jpg",
    ]
    for name in candidates:
        cand = parent / name
        if cand.is_file() and cand.stat().st_size > 0:
            return cand
    return None


CANONICAL_GENRE_TAGS: Dict[str, str] = {
    "oil": "Oil",
    "oiled": "Oil",
    "lubed": "Oil",
    "bdsm": "BDSM",
    "bondage": "Bondage",
    "hogtied": "Bondage",
    "submission": "BDSM",
    "sex and submission": "BDSM",
    "femdom": "Femdom",
    "latex": "Latex",
    "leather": "Latex",
    "anal": "Anal",
    "double penetration": "DP",
    "dp": "DP",
    "fisting": "Fisting",
    "gape": "Gape",
    "ass to mouth": "Ass To Mouth",
    "atm": "Ass To Mouth",
    "rimming": "Rimming",
    "interracial": "Interracial",
    "bbc": "BBC",
    "lesbian": "Lesbian",
    "threesome": "Threesome",
    "foursome": "Foursome",
    "orgy": "Orgy",
    "group": "Group",
    "gangbang": "Gangbang",
    "milf": "MILF",
    "mature": "Mature",
    "teen": "Teen",
    "blonde": "Blonde",
    "brunette": "Brunette",
    "redhead": "Redhead",
    "asian": "Asian",
    "latina": "Latina",
    "ebony": "Ebony",
    "busty": "Busty",
    "big tits": "Big Tits",
    "natural tits": "Natural Tits",
    "big ass": "Big Ass",
    "petite": "Petite",
    "curvy": "Curvy",
    "tattoo": "Tattoo",
    "piercing": "Piercing",
    "pov": "POV",
    "massage": "Massage",
    "office": "Office",
    "public": "Public",
    "outdoor": "Outdoor",
    "pool": "Pool",
    "shower": "Shower",
    "gym": "Gym",
    "casting": "Casting",
    "amateur": "Amateur",
    "parody": "Parody",
    "lingerie": "Lingerie",
    "stockings": "Stockings",
    "pantyhose": "Pantyhose",
    "fishnet": "Fishnet",
    "high heels": "High Heels",
    "uniform": "Uniform",
    "maid": "Maid",
    "nurse": "Nurse",
    "secretary": "Secretary",
    "teacher": "Teacher",
    "cosplay": "Cosplay",
    "toys": "Toys",
    "dildo": "Dildo",
    "vibrator": "Vibrator",
    "machine": "Machine",
    "glamour": "Glamour",
    "artistic": "Artistic",
    "creampie": "Creampie",
    "cumshot": "Cumshot",
    "facial": "Facial",
    "swallow": "Swallow",
    "swallowed": "Swallow",
    "deepthroat": "Deepthroat",
    "throated": "Deepthroat",
    "blowjob": "Blowjob",
    "handjob": "Handjob",
    "titfuck": "Titfuck",
    "oral": "Oral",
    "feet": "Feet",
    "foot": "Feet",
    "fetish": "Fetish",
    "rough": "Rough",
    "hardcore": "Hardcore",
    "softcore": "Softcore",
    "romantic": "Romantic",
    "cuckold": "Cuckold",
    "cheating": "Cheating",
    "solo": "Solo",
    "masturbation": "Masturbation",
    "striptease": "Striptease",
    "squirt": "Squirt",
    "vr": "VR",
    "4k ultra hd": "4K Ultra HD",
    "60fps": "60FPS",
    "中文字幕": "中文字幕",
    "无码 (uncensored)": "无码 (Uncensored)",
    "无码破解": "无码破解",
    "无码流出": "无码流出",
    "fc2 素人": "FC2 素人",
    "sci-fi": "Sci-Fi",
    "action": "Action",
    "drama": "Drama",
    "thriller": "Thriller",
    "imax": "IMAX",
    "dolby atmos": "Dolby Atmos",
    "dolby vision": "Dolby Vision",
    "hdr": "HDR",
}


# Explicit Series / Studio -> Mandatory Tags Table (Rule 1)
SERIES_MANDATORY_TAGS: List[Tuple[Tuple[str, ...], List[str]]] = [
    (("lubed",), ["Oil"]),
    (("tushy", "tushy raw", "tushyraw", "all anal", "allanal", "true anal", "trueanal", "analvids"), ["Anal"]),
    (("blacked", "blacked raw", "blackedraw", "bbc pie", "bbcpie", "monsters of cock", "monstersofcock", "dogfart", "dogfart network"), ["Interracial"]),
    (("hogtied",), ["Bondage"]),
    (("sex and submission", "sexandsubmission", "dungeon sex", "dungeonsex"), ["BDSM"]),
    (("anal oil latex", "anal.oil.latex"), ["Anal", "Oil", "Latex"]),
    (("oil overload", "oil.overload"), ["Oil"]),
    (("squirt explosion", "squirt.explosion"), ["Squirt"]),
    (("swallowed", "throated", "blowpass"), ["Blowjob", "Deepthroat"]),
    (("love her feet", "loveherfeet"), ["Feet"]),
    (("fantasy massage", "fantasymassage"), ["Massage"]),
    (("lesbea",), ["Lesbian"]),
]


def _compute_required_series_tags(item: MediaItem) -> List[str]:
    """Deterministically derives mandatory tags from series/studio/folder names per Rule 1."""
    haystack = " | ".join([item.studio or "", *item.parent_dirs, item.file_name]).lower()
    required: List[str] = []
    for triggers, mtags in SERIES_MANDATORY_TAGS:
        for trig in triggers:
            if re.search(rf"(?:^|[\s.|_\-\[\]]){re.escape(trig)}(?:$|[\s.|_\-\[\]\d])", haystack):
                for mt in mtags:
                    if mt not in required:
                        required.append(mt)
                break
    # Also check explicit whole-word genre tokens in folder/filename (e.g. `-FETiSH`, `Anal.Oil.Latex`)
    for tok in ("anal", "oil", "latex", "bdsm", "bondage", "fetish", "lesbian", "interracial", "threesome", "gangbang", "squirt", "creampie", "deepthroat", "facial", "fisting", "femdom", "cosplay", "massage"):
        if re.search(rf"(?:^|[\s._\-\[\]]){tok}(?:$|[\s._\-\[\]])", haystack):
            canon = CANONICAL_GENRE_TAGS.get(tok)
            if canon and canon not in required:
                required.append(canon)
    return required


def _clean_genre_tags(tags: List[str]) -> List[str]:
    """Filters out noisy directory/sub-series/resolution strings and keeps canonical genre tags."""
    cleaned: List[str] = []
    for raw in tags:
        t = str(raw).strip()
        if not t or len(t) > 28:
            continue
        low = t.lower()
        if low in CANONICAL_GENRE_TAGS:
            canon = CANONICAL_GENRE_TAGS[low]
            if canon not in cleaned:
                cleaned.append(canon)
            continue
        # Whole-word match for multi-tag strings like "Anal, Oil"
        for kw, canon in CANONICAL_GENRE_TAGS.items():
            if len(kw) >= 3 and re.search(rf"\b{re.escape(kw)}\b", low) and not (".com" in low or ":" in low):
                if canon not in cleaned:
                    cleaned.append(canon)
    return cleaned


EXTENDED_WESTERN_STUDIOS: Dict[str, str] = {
    "legalporno": "LegalPorno",
    "analvids": "LegalPorno",
    "dungeonsex": "Dungeon Sex",
    "immorallive": "Immoral Live",
    "il": "Immoral Live",
    "hogtied": "Hogtied",
    "sexandsubmission": "Sex and Submission",
    "elegantangel": "Elegant Angel",
    "hentaied": "Hentaied",
    "cheatingsis": "Cheating Sis",
    "mixedx": "Mixed X",
    "johnlegendaryvip": "LegendaryX",
    "legendaryx": "LegendaryX",
    "jaxslayher": "JaxSlayher",
    "ztod": "Zero Tolerance",
    "zerotolerance": "Zero Tolerance",
    "loveherfeet": "Love Her Feet",
    "tonightsgirlfriend": "Tonight's Girlfriend",
    "ultrafilms": "Ultra Films",
    "spizoo": "Spizoo",
    "manyvids": "ManyVids",
    "hollyrandall": "Holly Randall",
    "throated": "Throated",
    "wildoncam": "Wild On Cam",
    "hardx": "Hard X",
    "darkx": "Dark X",
    "ihaveawife": "I Have A Wife",
    "allanal": "All Anal",
    "trueanal": "True Anal",
    "swallowed": "Swallowed",
    "bangsurprise": "BANG! Surprise",
    "bangrammed": "BANG! Rammed",
    "bang": "BANG!",
    "bangbus": "Bang Bus",
    "monstersofcock": "Monsters Of Cock",
    "nympho": "Nympho",
    "dogfartnetwork": "Dogfart Network",
    "dogfart": "Dogfart Network",
    "vogov": "VogoV",
    "fantasymassage": "Fantasy Massage",
    "playboyplus": "Playboy Plus",
    "blowpass": "Blowpass",
    "faphouse": "FapHouse",
    "penthousegold": "Penthouse Gold",
    "penthouse": "Penthouse",
    "bbcpie": "BBC Pie",
    "vixenplus": "Vixen Plus",
    "cherrypimps": "Cherry Pimps",
    "vivthomas": "Viv Thomas",
    "digitalplayground": "Digital Playground",
    "sweetsinner": "Sweet Sinner",
    "bangbros18": "BangBros 18",
    "vixenintimates": "Vixen Intimates",
    "vixencompilations": "Vixen Compilations",
}


def _ensure_extended_studios_registered() -> None:
    for _alias, _canon in EXTENDED_WESTERN_STUDIOS.items():
        register_custom_studio(_alias, _canon)


_ensure_extended_studios_registered()


NON_STUDIO_DIR_NAMES = {
    "欧美", "日本", "日韩", "国产", "动漫", "电影", "剧集", "女优", "演员", "合集",
    "others", "other", "misc", "unsorted", "new", "downloads", "video", "videos",
    "media", "movies", "adult", "western", "jav", "18", "19", "20", "21", "22", "23", "24", "25", "26",
    "pornhub", "pron hub", "pronhub", "xvideos", "xnxx", "onlyfans", "spankbang",
    "anal oil latex", "oil overload", "squirt explosion", "club vxn",
}


def _is_invalid_studio_label(s: str) -> bool:
    if not s:
        return True
    low = s.strip().lower()
    if low in NON_STUDIO_DIR_NAMES or low.isdigit():
        return True
    if low.startswith(("ph-", "pornhub", "pron hub", "pronhub", "onlyfans", "xvideos")):
        return True
    if re.search(r"\b(?:1080[pр]|720p|2160p|4k|overload|explosion|anal[\s.]*oil[\s.]*latex|club[\s.]*vxn)\b", low, re.IGNORECASE) or "#" in low:
        return True
    return False


def _resolve_studio_candidate(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip(" []()@._-")
    for ext in (".com", ".tv", ".net", ".org"):
        if s.lower().endswith(ext):
            s = s[: -len(ext)].strip()
    if _is_invalid_studio_label(s):
        return None
    canon = normalize_studio_name(s)
    if canon:
        return canon
    compact = re.sub(r"[\s._\-]+", "", s.lower())
    return EXTENDED_WESTERN_STUDIOS.get(compact)


def _clean_studio_classification(item: MediaItem) -> None:
    """Ensures unverified directory/compilation names are not shown as studios; normalizes valid ones."""
    if item.is_unknown_studio:
        item.studio = ""
        return
    if item.studio:
        s = item.studio.strip()
        for ext in (".com", ".tv", ".net", ".org"):
            if s.lower().endswith(ext):
                s = s[: -len(ext)].strip()
        if _is_invalid_studio_label(s):
            item.studio = ""
            item.is_unknown_studio = True
            return
        resolved = _resolve_studio_candidate(s)
        item.studio = resolved if resolved else s


def _extract_actress_from_parent_dirs(parent_dirs: List[str]) -> Optional[str]:
    """If parent_dirs has ['...', '女优', '<ActressFolder>', ...], extracts the clean actress name."""
    for idx, folder in enumerate(parent_dirs):
        if folder.strip().lower() in ("女优", "actress", "actresses", "performers", "models", "stars"):
            if idx + 1 < len(parent_dirs):
                raw_act = parent_dirs[idx + 1].strip()
                raw_act = re.sub(r"[-_]?collection$", "", raw_act, flags=re.IGNORECASE)
                raw_act = raw_act.replace(".", " ").strip()
                if raw_act and raw_act.lower() not in NON_STUDIO_DIR_NAMES and not raw_act.isdigit():
                    return raw_act
    return None


def _refine_item_from_path_clues(item: MediaItem) -> None:
    """
    Deep multi-clue refinement combining `file_name` and `parent_dirs` to fix:
    1. `[19]Studio.Title.YYYY-MM-DD.mp4` year-bracketed files
    2. `Actress - [Studio.com] - [YYYY] - Title - CoStar.mp4`
    3. `Actress -- @Studio -- Title -- YYYY-MM-DD.mp4`
    4. `Studio.YY.MM.DD.FirstName.LastName(.SceneCode).XXX.mp4` (merging split first/last names)
    5. Parent folder full scene release names when filename uses abbreviated studio (`il.26.06.27...`)
    6. Actress folder inheritance (`parent_dirs` under `女优/<Actress>`)
    """
    _ensure_extended_studios_registered()
    stem = Path(item.file_name).stem
    clean_stem = re.sub(r"^[A-Za-z0-9._\-]+@", "", stem)  # Strip watermark prefix like `T66Y.COM@`

    # Clue A: Actress from `女优/<Actress>` parent folder
    folder_actress = _extract_actress_from_parent_dirs(item.parent_dirs)

    # Clue B: Check parent folders for known studio or full scene release name
    parent_studio: Optional[str] = None
    for folder in reversed(item.parent_dirs):
        f_clean = folder.strip()
        st = _resolve_studio_candidate(f_clean)
        if st:
            parent_studio = st
            break
        m_parent_scene = re.match(
            r"^(?P<studio>[A-Za-z0-9_-]+)\.(?P<yy>\d{2})\.(?P<mm>0[1-9]|1[0-2])\.(?P<dd>0[1-9]|[12]\d|3[01])\.(?P<rest>.+)$",
            f_clean,
        )
        if m_parent_scene:
            st_scene = _resolve_studio_candidate(m_parent_scene.group("studio"))
            if st_scene:
                parent_studio = st_scene
                break

    # Pattern 1: `[19]DigitalPlayground.The Audition. Scene 4.2019-11-27`
    m_yr_prefix = re.match(r"^\[\d{2,4}\]\.?(?P<studio_and_rest>.+)$", clean_stem)
    if m_yr_prefix:
        rem = m_yr_prefix.group("studio_and_rest").strip(".")
        m_date_end = re.search(r"\.(?P<date>(?:19|20)\d{2}-\d{2}-\d{2})$", rem)
        if m_date_end:
            item.release_date = m_date_end.group("date")
            rem = rem[: m_date_end.start()]
        parts = [p.strip() for p in rem.split(".") if p.strip()]
        if parts:
            st = _resolve_studio_candidate(parts[0])
            if st:
                item.studio = st
                item.is_unknown_studio = False
                title_part = ". ".join(parts[1:]).strip()
                if title_part:
                    item.title = title_part
            elif parts[0] and not parts[0].isdigit():
                item.studio = parts[0]
                item.is_unknown_studio = False
                title_part = ". ".join(parts[1:]).strip()
                if title_part:
                    item.title = title_part

    # Pattern 2: `Kelly Collins - [Vixen.com] - [2022] - Perfect Arrangement - Alecia Fox`
    m_bracket_dash = re.match(
        r"^(?P<perf1>[^\[\-]+?)\s*-\s*\[(?P<studio>[^\]]+)\]\s*-\s*\[(?P<year>\d{4}(?:-\d{2}-\d{2})?)\]\s*-\s*(?P<rest>.+)$",
        clean_stem,
    )
    if m_bracket_dash:
        p1 = m_bracket_dash.group("perf1").strip()
        raw_st = m_bracket_dash.group("studio").strip()
        yr = m_bracket_dash.group("year").strip()
        rest = m_bracket_dash.group("rest").strip()
        st = _resolve_studio_candidate(raw_st) or re.sub(r"\.(?:com|tv|net|org)$", "", raw_st, flags=re.IGNORECASE)
        item.studio = st
        item.is_unknown_studio = False
        item.release_date = yr
        rest = re.sub(r"\s*-\s*(?:4K|2160p|1080p|720p)\s*$", "", rest, flags=re.IGNORECASE)
        rest = re.sub(r"\s*\[[^\]]+\]\s*", " ", rest).strip()
        sub_parts = [sp.strip() for sp in rest.split(" - ") if sp.strip()]
        perfs = [p1] if p1 else []
        if len(sub_parts) >= 2:
            item.title = sub_parts[0]
            for extra_p in sub_parts[1].split(","):
                ep = extra_p.strip()
                if ep and ep not in perfs:
                    perfs.append(ep)
        else:
            item.title = rest
        item.performers = perfs

    # Pattern 3: `Kelly Collins, Sia Siberia -- @Tushy -- Birthday Gift -- 2023-04-09`
    if " -- " in clean_stem:
        dparts = [dp.strip() for dp in clean_stem.split(" -- ") if dp.strip()]
        if len(dparts) >= 3:
            perfs = [p.strip() for p in dparts[0].split(",") if p.strip()]
            st_cand = _resolve_studio_candidate(dparts[1])
            if st_cand:
                item.studio = st_cand
                item.is_unknown_studio = False
            if perfs:
                item.performers = perfs
            item.title = dparts[2]
            if len(dparts) >= 4:
                m_dt = re.search(r"((?:19|20)\d{2}-\d{2}-\d{2})", dparts[3])
                if m_dt:
                    item.release_date = m_dt.group(1)

    # Pattern 4: Standard Scene Dot Notation `Studio.YY.MM.DD.Rest...` (fix split first/last names)
    m_scene = re.match(
        r"^(?P<studio>[A-Za-z0-9_-]+)\.(?P<yy>\d{2})\.(?P<mm>0[1-9]|1[0-2])\.(?P<dd>0[1-9]|[12]\d|3[01])\.(?P<rest>.+)$",
        clean_stem,
    )
    if m_scene:
        raw_st = m_scene.group("studio")
        st = _resolve_studio_candidate(raw_st) or parent_studio
        if st:
            item.studio = st
            item.is_unknown_studio = False
        rest = re.split(r"\.(?:XXX|2160p|1080p|720p|480p|4K|MP4|HEVC|x265|x264)\b", m_scene.group("rest"), flags=re.IGNORECASE)[0]
        tokens = [t for t in rest.split(".") if t]
        and_indices = [i for i, t in enumerate(tokens) if t.lower() == "and"]
        if and_indices:
            # e.g. `Candie.Luciani.And.Reina.Ohara` -> extract all performers separated by `And`
            perf_groups: List[List[str]] = [[]]
            for tok in tokens:
                if tok.lower() == "and":
                    perf_groups.append([])
                else:
                    perf_groups[-1].append(tok)
            perfs = []
            leftover_title: List[str] = []
            for idx_g, grp in enumerate(perf_groups):
                if idx_g < len(perf_groups) - 1 or len(grp) <= 2:
                    name = " ".join(w.capitalize() if w.islower() else w for w in grp)
                    if name:
                        perfs.append(name)
                else:
                    name = " ".join(w.capitalize() if w.islower() else w for w in grp[:2])
                    if name:
                        perfs.append(name)
                    leftover_title = grp[2:]
            if perfs:
                item.performers = perfs
            if leftover_title:
                item.title = " ".join(leftover_title)
            else:
                item.title = f"{item.studio or raw_st} - {', '.join(perfs)}"
        elif len(tokens) == 2:
            # Two tokens after date (`Mia.Walker` or `octavia.red`): this is First + Last name of performer!
            full_name = " ".join(w.capitalize() if w.islower() else w for w in tokens)
            if not item.performers or (len(item.performers) == 1 and " " not in item.performers[0]):
                item.performers = [full_name]
            if not item.title or item.title.lower() in (tokens[1].lower(), item.file_name.lower(), stem.lower()):
                item.title = f"{item.studio or raw_st} - {full_name} ({item.release_date})" if item.release_date else f"{item.studio or raw_st} - {full_name}"
        elif len(tokens) == 3 and re.match(r"^[A-Z]{1,4}\d{2,5}$", tokens[2], re.IGNORECASE):
            # e.g. `Areta.Ridera.AH218` (First.Last.SceneCode)
            full_name = " ".join(w.capitalize() if w.islower() else w for w in tokens[:2])
            scene_code = tokens[2].upper()
            if not item.performers or (len(item.performers) == 1 and " " not in item.performers[0]):
                item.performers = [full_name]
            if not item.title or item.title.lower() in (tokens[2].lower(), f"{tokens[1]} {tokens[2]}".lower(), item.file_name.lower(), stem.lower()):
                item.title = f"{scene_code} - {full_name}"
        elif len(tokens) == 3:
            # e.g. `India.Do.Sul` or `Mary.Mery.Jane` or `Emy.Rouse.Cineplexinternational`
            full_name = " ".join(w.capitalize() if w.islower() else w for w in tokens[:2])
            if not item.performers or (len(item.performers) == 1 and " " not in item.performers[0]):
                item.performers = [full_name]
            if not item.title or item.title.lower() in (tokens[2].lower(), f"{tokens[1]} {tokens[2]}".lower(), item.file_name.lower(), stem.lower()):
                item.title = f"{full_name} - {tokens[2]}"

    # Pattern 5: `NEW.Nympho.Octavia.Red...`
    if clean_stem.upper().startswith("NEW."):
        parts = clean_stem.split(".")
        if len(parts) >= 3:
            st = _resolve_studio_candidate(parts[1])
            if st:
                item.studio = st
                item.is_unknown_studio = False

    # Inherit known studio from parent folder if still unknown
    if (item.is_unknown_studio or not item.studio) and parent_studio:
        item.studio = parent_studio
        item.is_unknown_studio = False

    # Inherit or fix actress from `女优/<Actress>` parent folder
    if folder_actress:
        if not item.performers:
            item.performers = [folder_actress]
        else:
            # Replace partial 1-word match (e.g. "octavia" -> "Octavia Red")
            updated_perfs = []
            for p in item.performers:
                if p.lower() in folder_actress.lower() and len(p) < len(folder_actress):
                    if folder_actress not in updated_perfs:
                        updated_perfs.append(folder_actress)
                else:
                    updated_perfs.append(p)
            if folder_actress.lower() not in [up.lower() for up in updated_perfs]:
                updated_perfs.insert(0, folder_actress)
            item.performers = updated_perfs

    # Probe video duration if not yet recorded (fast pure-Python MP4 mvhd box parser + ffmpeg fallback)
    if item.duration_sec <= 0.0:
        probed_sec = probe_video_duration_sec(item.file_path)
        if probed_sec > 0.0:
            item.duration_sec = probed_sec

    # Merge existing canonical tags + deterministic series/folder mandatory tags (Rule 1)
    series_tags = _compute_required_series_tags(item)
    merged_tags = _clean_genre_tags(item.tags + series_tags)
    item.tags = merged_tags
    item.refresh_completeness()


def _format_duration_display(duration_sec: float) -> str:
    if duration_sec <= 0.0:
        return "未知 (0s)"
    total_sec = int(round(duration_sec))
    mins, secs = divmod(total_sec, 60)
    kind = "单场 Scene" if total_sec < 4800 else "合集/长片 Compilation"
    return f"{mins}m{secs:02d}s ({total_sec}s, {kind})"


def _select_items_for_ai_export(
    all_items: List[MediaItem],
    export_mode: str = "incomplete",
) -> Tuple[str, List[MediaItem]]:
    """
    Selects records for AI enrichment based on `export_mode`:
    - `"incomplete"`: records where `is_incomplete` or `is_unknown_studio` or `user_keywords`.
      If 0 records match, automatically switches to `"tags_only"` so empty-tag records can still be curated!
    - `"tags_only"`: records where `tags` is empty (`[]`), or missing mandatory series tags, or has `user_keywords`
      (even when `is_incomplete == False`).
    """
    mode = export_mode.strip().lower() if export_mode else "incomplete"
    if mode == "tags_only":
        tag_targets = [
            i for i in all_items
            if not i.tags
            or any(rt not in i.tags for rt in _compute_required_series_tags(i))
            or i.user_keywords
        ]
        return "tags_only", (tag_targets if tag_targets else list(all_items))

    inc_targets = [i for i in all_items if i.is_incomplete or i.is_unknown_studio or i.user_keywords]
    if inc_targets:
        return "incomplete", inc_targets

    # Fallback to tags_only when all basic metadata (`is_incomplete=False`) is already complete
    tag_targets = [
        i for i in all_items
        if not i.tags or any(rt not in i.tags for rt in _compute_required_series_tags(i))
    ]
    if tag_targets:
        return "tags_only", tag_targets
    return "incomplete", list(all_items)


AI_RULES_MARKDOWN_BLOCK = (
    "### 核心规则与四条铁律（必读）：\n"
    "1. **证据匹配顺序与警惕错误合集标题**：\n"
    "   - **匹配顺序**：`文件名日期 (file_name date) > 系列目录 (parent_dirs) > 女优目录 (parent_dirs) > user_keywords (用户备注) > 时长 (duration_sec) > 已有标题 (title)`。\n"
    "   - **已有标题可能是合集名**（如 `Club VXN` 多支文件被存成合集名）或本地正则切分残片。请对比 `duration_sec`（单场通常 1200~3600 秒，合集通常 >5400 秒）：**时长对不上合集就绝不要沿用合集标题！**\n"
    "2. **系列 → 必有标签对照表（Series → Mandatory Tags）**：\n"
    "   - `Lubed` = `Oil`\n"
    "   - `Tushy` / `Tushy Raw` / `All Anal` / `True Anal` = `Anal`\n"
    "   - `Blacked` / `Blacked Raw` / `BBC Pie` / `Monsters Of Cock` / `Dogfart Network` = `Interracial`\n"
    "   - `Hogtied` = `Bondage`\n"
    "   - `Sex and Submission` / `Dungeon Sex` = `BDSM`\n"
    "   - `Anal Oil Latex`（系列目录/合集） = `Anal` + `Oil` + `Latex`\n"
    "   - `Oil Overload` = `Oil`；`Squirt Explosion` = `Squirt`\n"
    "   - `Swallowed` / `Throated` / `Blowpass` = `Blowjob` + `Deepthroat`\n"
    "   - `Love Her Feet` = `Feet`；`Fantasy Massage` = `Massage`；`Lesbea` = `Lesbian`\n"
    "3. **标签词表限制与“对不上就留空”原则**：\n"
    "   - **标签只用下方词表里已有的词**。用「日期 + 系列 + 演员 + 时长」去对场次；确切对上场次才写具体行为标签。\n"
    "   - **对不上场次则 `tags` 保持 `[]`（或仅保留系列必有标签），并写 `tag_note` 说明原因，不要猜，不要向用户逐条确认！**\n"
    "   - **严禁把 `Hardcore` 或 `Blowjob` 默认贴到每一支硬戏上！**\n"
    "   - **本轮若任务是校对标签（`export_mode: \"tags_only\"`），只改 `tags` 和 `tag_note`。空 `tags` (`[]`) 绝不会覆盖库里已有标签。**\n"
    "4. **厂牌别名登记红线**：\n"
    "   - **`Anal Oil Latex`、`Oil Overload`、`Squirt Explosion`、`Club VXN` 是系列/合集不是厂牌；`Pornhub`、`Pron Hub`、`PH-*`、`OnlyFans` 是平台不是厂牌**，严禁登记进 `studio` 或 `new_studio_alias_to_register`。\n"
    "5. **年龄合规政策（18+ 唯一基准）**：\n"
    "   - 本库收录的商业成人作品均以法定 **18 周岁（18+）** 为唯一成年合规基准（符合 18 U.S.C. § 2257 商业厂牌存档规范）。凡年满 18 周岁的商业厂牌演员，请正常标注完整标签，**严禁按未满 21 岁（under-21）标准拦截或清空标签**；未满约定年龄（18 岁）的记录不写性行为标签。\n"
)


def _build_record_dict_for_ai(item: MediaItem, export_mode: str = "incomplete") -> Dict[str, Any]:
    alias_hint = ""
    if item.is_unknown_studio:
        if item.jav_code and "-" in item.jav_code:
            alias_hint = item.jav_code.split("-")[0]
        elif item.studio and not _is_invalid_studio_label(item.studio):
            alias_hint = item.studio
    return {
        "item_id": item.item_id,
        "fast_hash": item.fast_hash,
        "export_mode": export_mode,
        "media_category": item.media_category.value,
        "jav_code": item.jav_code,
        "file_name": item.file_name,
        "parent_dirs": item.parent_dirs,
        "file_path": item.file_path,
        "duration_sec": round(item.duration_sec, 1),
        "duration_display": _format_duration_display(item.duration_sec),
        "user_keywords": list(item.user_keywords),
        "studio": item.studio,
        "is_unknown_studio": item.is_unknown_studio,
        "new_studio_alias_to_register": alias_hint,
        "director": item.director,
        "title": item.title,
        "performers": list(item.performers),
        "release_date": item.release_date,
        "tags": list(item.tags),
        "tag_note": "",
    }


def _export_enhanced_keyword_db_md(
    all_items: List[MediaItem],
    output_md_path: Optional[Path] = None,
    export_mode: str = "incomplete",
    batch_index: int = 0,
    batch_size: int = 25,
) -> Tuple[str, Dict[str, Any]]:
    """
    Writes `AI_KEYWORD_DB.md` (and `AI_ENRICHMENT_GUIDE.md` alongside it) with:
    - All 4 rules + Series->Tag table + Allowed 85+ Genre Tags vocabulary + Age Policy (18+)
    - `duration_sec`, `duration_display`, `user_keywords`, `export_mode`, and `tag_note`
    - Paginated batches of `batch_size` (default 25) for reliable in-place CLI editing (Mode B)
    """
    resolved_mode, target_items = _select_items_for_ai_export(all_items, export_mode)
    total_target = len(target_items)
    total_batches = max(1, (total_target + batch_size - 1) // batch_size)
    clamped_idx = max(0, min(batch_index, total_batches - 1))
    start_i = clamped_idx * batch_size
    batch_slice = target_items[start_i : start_i + batch_size]

    records_payload = [_build_record_dict_for_ai(it, export_mode=resolved_mode) for it in batch_slice]
    allowed_tags = sorted(set(CANONICAL_GENRE_TAGS.values()))
    mode_label = (
        "🏷 标签专项校对模式 (export_mode: tags_only — 本轮只许改 tags 和 tag_note，严禁修改 studio/title/performers/release_date)"
        if resolved_mode == "tags_only"
        else "📋 待补全元数据与标签模式 (export_mode: incomplete — 补全厂牌、演员、片名、日期与标签)"
    )

    md_lines = [
        "# CineVault Studio — AI CLI Keyword & Tag Database (`AI_KEYWORD_DB.md`)",
        "",
        f"> **当前导出模式**: {mode_label}",
        f"> **当前批次**: 第 {clamped_idx + 1} / {total_batches} 批（本批 {len(batch_slice)} 条，共 {total_target} 条目标记录）",
        "",
        AI_RULES_MARKDOWN_BLOCK.strip(),
        "",
        "## 1. 库里已有且允许使用的标准标签词表 (Allowed Genre Tags Vocabulary)",
        "",
        f"- **Allowed Tags ({len(allowed_tags)})**: {', '.join(allowed_tags)}",
        "",
        "## 2. 本批待处理记录 (请直接就地修改下方 JSON 并保存文件，不要修改 `item_id` 与 `fast_hash`)",
        "",
        "```json",
        json.dumps(records_payload, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    md_content = "\n".join(md_lines)
    if output_md_path is not None:
        try:
            output_md_path.write_text(md_content, encoding="utf-8")
            # Also sync AI_ENRICHMENT_GUIDE.md into the same directory so CLI agents see it
            repo_guide = resolve_bundle_root() / "AI_ENRICHMENT_GUIDE.md"
            target_guide = output_md_path.parent / "AI_ENRICHMENT_GUIDE.md"
            if repo_guide.is_file() and repo_guide.resolve() != target_guide.resolve():
                target_guide.write_text(repo_guide.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass

    meta = {
        "export_mode": resolved_mode,
        "batch_index": clamped_idx,
        "batch_size": batch_size,
        "total_batches": total_batches,
        "total_incomplete": total_target,
        "batch_count": len(batch_slice),
    }
    return md_content, meta


def _build_enhanced_ai_prompt(
    batch_items: List[MediaItem],
    batch_index: int = 0,
    total_batches: int = 1,
    total_incomplete: int = 0,
    export_mode: str = "incomplete",
    language: str = "zh",
) -> str:
    """
    Builds a batch-sized, multi-clue AI prompt containing the 4 strict rules,
    the Series -> Mandatory Tags table, the full allowed tag vocabulary, and `duration_sec`.
    """
    payload_list = [_build_record_dict_for_ai(item, export_mode=export_mode) for item in batch_items]
    allowed_tags = sorted(set(CANONICAL_GENRE_TAGS.values()))
    json_str = json.dumps(payload_list, ensure_ascii=False, indent=2)
    mode_banner = (
        "【本轮模式：仅校对标签 (tags_only) —— 只允许修改 `tags` 和 `tag_note`，严禁修改 `studio`、`title`、`performers`、`release_date`！】"
        if export_mode == "tags_only"
        else "【本轮模式：元数据与标签综合补全 (incomplete)】"
    )
    return (
        f"你现在是 CineVault Studio 影视资料库整理助手（第 {batch_index + 1}/{total_batches} 批，本批 {len(batch_items)} 条，共 {total_incomplete} 条）。\n"
        f"{mode_banner}\n\n"
        f"{AI_RULES_MARKDOWN_BLOCK}\n"
        f"### 库内允许使用的标准标签词表（共 {len(allowed_tags)} 个，严禁自造词表外的标签）：\n"
        f"{', '.join(allowed_tags)}\n\n"
        "### 输出格式要求：\n"
        "请直接就地修改 `AI_KEYWORD_DB.md` 中的 JSON 代码块，或只输出一个完整的 `json` 代码块（数组中每个对象保留 `item_id` 和 `tag_note`）：\n\n"
        f"```json\n{json_str}\n```"
    )


def _extract_json_records_from_text(raw_content: str) -> List[Dict[str, Any]]:
    """Extracts JSON record dicts from markdown fences, raw JSON arrays, or truncated JSON."""
    fence_match = re.search(r"```json\s*(\[.*?\]|\{.*?\})\s*```", raw_content, re.DOTALL)
    candidate_text = fence_match.group(1) if fence_match else raw_content.strip()
    try:
        parsed = json.loads(candidate_text)
        if isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
            return [r for r in parsed["records"] if isinstance(r, dict) and r.get("item_id")]
        if isinstance(parsed, list):
            return [r for r in parsed if isinstance(r, dict) and r.get("item_id")]
        if isinstance(parsed, dict) and parsed.get("item_id"):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # Fallback balanced `{ ... }` scanner for truncated JSON outputs
    recovered: List[Dict[str, Any]] = []
    idx = 0
    n = len(raw_content)
    while idx < n:
        start = raw_content.find("{", idx)
        if start == -1:
            break
        depth = 0
        in_str = False
        escape = False
        end = -1
        for j in range(start, n):
            ch = raw_content[j]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
        if end != -1:
            chunk = raw_content[start : end + 1]
            if '"item_id"' in chunk:
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict) and obj.get("item_id"):
                        recovered.append(obj)
                except json.JSONDecodeError:
                    pass
            idx = end + 1
        else:
            break
    return recovered


def _import_ai_completions_resilient(
    raw_content: str,
    items_map: Dict[str, MediaItem],
    force_tags_only: bool = False,
) -> int:
    """
    Safely imports AI JSON completions into `items_map`:
    1. Never lets an empty `tags: []` overwrite existing `target.tags` (merges non-empty canonical tags).
    2. When `export_mode == "tags_only"` or `force_tags_only=True`, ONLY updates `tags` (locks studio/title/performers/date).
    3. Blocks compilation series (`Anal Oil Latex`, `Oil Overload`) and platforms (`Pornhub`, `Pron Hub`, `PH-*`)
       from being registered as studios or studio aliases.
    """
    records = _extract_json_records_from_text(raw_content)
    if not records:
        return 0

    header_tags_only = force_tags_only or ("export_mode: tags_only" in raw_content)
    sanitized_for_core: List[Dict[str, Any]] = []
    preserved_tags_by_id: Dict[str, List[str]] = {}
    locked_fields_by_id: Dict[str, Tuple[str, bool, str, List[str], str, str, str]] = {}

    for rec in records:
        item_id = str(rec.get("item_id", "")).strip()
        if not item_id or item_id not in items_map:
            continue
        target = items_map[item_id]
        rec_tags_only = header_tags_only or str(rec.get("export_mode", "")).lower() == "tags_only" or bool(rec.get("only_update_tags"))

        # Snapshot existing tags + mandatory series tags so empty `[]` from AI never wipes them
        base_tags = _clean_genre_tags(target.tags + _compute_required_series_tags(target))
        ai_raw_tags = rec.get("tags")
        if isinstance(ai_raw_tags, list) and len(ai_raw_tags) > 0:
            ai_clean_tags = _clean_genre_tags([str(t) for t in ai_raw_tags if str(t).strip()])
            merged_tags = list(dict.fromkeys(base_tags + ai_clean_tags))
        else:
            merged_tags = base_tags
        preserved_tags_by_id[item_id] = merged_tags

        clean_rec = dict(rec)
        clean_rec["tags"] = merged_tags

        if rec_tags_only:
            # Lock non-tag fields so `tags_only` audit never alters studio, title, performers, or release_date
            locked_fields_by_id[item_id] = (
                target.studio,
                target.is_unknown_studio,
                target.title,
                list(target.performers),
                target.release_date,
                target.director,
                target.jav_code,
            )
            for k in ("studio", "new_studio_alias_to_register", "title", "performers", "release_date", "director", "jav_code"):
                clean_rec.pop(k, None)
        else:
            # Guard studio & alias registration against series names (`Anal Oil Latex`, `Oil Overload`) and platforms (`Pron Hub`)
            cand_studio = str(clean_rec.get("studio", "")).strip()
            cand_alias = str(clean_rec.get("new_studio_alias_to_register", "")).strip()
            if cand_studio and _is_invalid_studio_label(cand_studio):
                clean_rec["studio"] = ""
                clean_rec["new_studio_alias_to_register"] = ""
            elif cand_alias and _is_invalid_studio_label(cand_alias):
                clean_rec["new_studio_alias_to_register"] = ""

        sanitized_for_core.append(clean_rec)

    if not sanitized_for_core:
        return 0

    synthetic_md = "```json\n" + json.dumps(sanitized_for_core, ensure_ascii=False) + "\n```"
    updated = import_root_markdown_completions(synthetic_md, items_map)

    for item_id, merged_tags in preserved_tags_by_id.items():
        it = items_map[item_id]
        if item_id in locked_fields_by_id:
            st, unk, ti, perfs, rdate, direc, jcode = locked_fields_by_id[item_id]
            it.studio = st
            it.is_unknown_studio = unk
            it.title = ti
            it.performers = perfs
            it.release_date = rdate
            it.director = direc
            it.jav_code = jcode
        it.tags = merged_tags
        _clean_studio_classification(it)
        it.refresh_completeness()

    return updated


def run_library_refresh(
    repo: SQLiteLibraryRepository,
    config: Optional[Dict[str, Any]] = None,
    app_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Fast incremental refresh pipeline:
    - Uses (path, size_bytes, mtime_epoch) cache + parallel fast_hash computation
    - Skips redundant scraping/FFmpeg on unchanged & already-enriched items
    - Enriches new/modified/incomplete items concurrently
    """
    t0 = time.perf_counter()
    _set_refresh_status(running=True, phase="scanning", total=0, processed=0, message="正在扫描存储目录并比对文件状态...", elapsed_sec=0.0, summary={})

    cfg = config if config is not None else load_config()
    root_dir = app_root or resolve_app_root()
    covers_dir = root_dir / ".cinevault_covers"

    roots: List[Dict[str, str]] = cfg.get("storage_roots") or []
    existing_items = repo.load_all_items()
    known_files = {
        i.file_path: (i.size_bytes, i.mtime_epoch, i.fast_hash)
        for i in existing_items
        if i.fast_hash
    }

    scanned_entries = scan_storage_roots(roots, compute_hashes=True, known_files=known_files) if roots else []
    _set_refresh_status(phase="reconciling", message=f"已扫描 {len(scanned_entries)} 个视频，正在进行哈希校验与路径对齐...")
    report = reconcile_library_state(existing_items, scanned_entries)

    scraper = OnlineMetadataScraper(
        api_token=cfg.get("theporndb_token") or None,
        tmdb_api_key=cfg.get("tmdb_api_key") or None,
    )

    to_enrich: List[MediaItem] = []
    for item in report.active_library:
        _refine_item_from_path_clues(item)
        _clean_studio_classification(item)
        item.tags = _clean_genre_tags(item.tags)
        has_cover = bool(item.cover_path) and item.cover_source != CoverSourceType.PLACEHOLDER
        if item.diff_status == FileDiffStatus.UNCHANGED and not item.is_incomplete and has_cover:
            continue
        to_enrich.append(item)

    _set_refresh_status(
        phase="enriching",
        total=len(to_enrich),
        processed=0,
        message=f"正在并发刮削与封面补全 ({len(to_enrich)}/{len(report.active_library)} 项需要处理)...",
    )

    allow_ffmpeg = bool(cfg.get("auto_extract_frames", False)) and bool(find_ffmpeg_binary())

    def _enrich_one(item: MediaItem) -> None:
        apply_parsed_tokens_to_item(item)
        _refine_item_from_path_clues(item)
        tokens = parse_western_media_path(item.file_path, item.parent_dirs)
        if item.studio and not item.is_unknown_studio:
            tokens.studio = item.studio
            tokens.is_unknown_studio = False
        if item.performers:
            tokens.performers = list(item.performers)
        if item.title:
            tokens.title = item.title
        if item.release_date:
            tokens.release_date = item.release_date
        candidates = scraper.search_candidates(tokens, item.user_keywords)

        sidecar_file = _find_local_sidecar_cover_file(item.file_path)
        local_sidecar: Optional[str] = str(sidecar_file) if sidecar_file is not None else None

        extracted_cover: Optional[str] = None
        has_cover = bool(item.cover_path) and item.cover_source != CoverSourceType.PLACEHOLDER
        candidate_has_cover = any(c.cover_url for c in candidates)
        if allow_ffmpeg and not has_cover and not local_sidecar and not candidate_has_cover:
            cover_file = covers_dir / f"{item.item_id}.jpg"
            if (cover_file.is_file() and cover_file.stat().st_size > 0) or extract_fallback_cover_frame(
                item.file_path, str(cover_file), duration_sec=item.duration_sec
            ):
                extracted_cover = str(cover_file)

        enrich_media_item(
            item,
            tokens,
            candidates,
            local_sidecar_cover=local_sidecar,
            extracted_frame_cover=extracted_cover,
        )
        # Persist online posters locally in `.cinevault_covers/` so .cvpack export & offline mode work
        if item.cover_source == CoverSourceType.ONLINE_POSTER and item.cover_path.startswith(("http://", "https://")):
            local_poster = covers_dir / f"{item.item_id}.jpg"
            if _download_cover_to_local(item.cover_path, local_poster):
                item.cover_path = str(local_poster)

        _refine_item_from_path_clues(item)
        _clean_studio_classification(item)
        item.tags = _clean_genre_tags(item.tags)
        with _REFRESH_LOCK:
            REFRESH_STATUS["processed"] = int(REFRESH_STATUS["processed"]) + 1

    if to_enrich:
        workers = min(6, len(to_enrich))
        if workers <= 1:
            for item in to_enrich:
                _enrich_one(item)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(_enrich_one, to_enrich))

    _set_refresh_status(phase="saving", message="正在写入 SQLite 数据库并导出 AI 词库...")
    all_to_save = report.active_library + report.missing
    if all_to_save:
        repo.upsert_items(all_to_save)

    all_items = repo.load_all_items()
    _export_enhanced_keyword_db_md(all_items, root_dir / "AI_KEYWORD_DB.md", export_mode="incomplete", batch_index=0, batch_size=25)
    elapsed = round(time.perf_counter() - t0, 3)
    summary = report.summary_counts()
    _set_refresh_status(
        running=False,
        phase="done",
        total=len(to_enrich),
        processed=len(to_enrich),
        message=f"校验与补全完成（耗时 {elapsed}s）",
        elapsed_sec=elapsed,
        summary=summary,
    )
    return {
        "status": "ok",
        "elapsed_sec": elapsed,
        "summary": summary,
        "items": [i.to_dict() for i in all_items],
    }


# [HYDROGEN-TASK-06]
def dispatch_api_request(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]],
    repo: SQLiteLibraryRepository,
    config_path: Optional[Path] = None,
) -> Tuple[int, Dict[str, Any]]:
    """
    Pure, testable REST API dispatcher connecting the Web/PWA UI (`src/ui/index.html`)
    to the SQLite repository and Argon core engines.
    """
    body = payload or {}
    method_upper = method.upper()
    clean_path = path.split("?", 1)[0]

    if method_upper == "GET" and clean_path == "/api/library":
        loaded_items = repo.load_all_items()
        dirty_items: List[MediaItem] = []
        for it in loaded_items:
            before_state = (it.studio, it.is_unknown_studio, it.title, tuple(it.performers), tuple(it.tags), it.release_date, round(it.duration_sec, 1))
            _refine_item_from_path_clues(it)
            _clean_studio_classification(it)
            it.tags = _clean_genre_tags(it.tags)
            it.refresh_completeness()
            after_state = (it.studio, it.is_unknown_studio, it.title, tuple(it.performers), tuple(it.tags), it.release_date, round(it.duration_sec, 1))
            if before_state != after_state:
                dirty_items.append(it)
        if dirty_items:
            repo.upsert_items(dirty_items)
            app_root = config_path.parent if config_path else resolve_app_root()
            _export_enhanced_keyword_db_md(loaded_items, app_root / "AI_KEYWORD_DB.md", export_mode="incomplete", batch_index=0, batch_size=25)
        items = [i.to_dict() for i in loaded_items]
        players = [p.__dict__ for p in detect_local_players()]
        return 200, {"status": "ok", "items": items, "players": players}

    if method_upper == "GET" and clean_path == "/api/config":
        ff_path = find_ffmpeg_binary() or ""
        return 200, {
            "status": "ok",
            "config": load_config(config_path),
            "ffmpeg_available": bool(ff_path),
            "ffmpeg_path": ff_path,
        }

    if method_upper == "GET" and clean_path == "/api/refresh/status":
        return 200, {"status": "ok", **get_refresh_status()}

    if method_upper == "POST" and clean_path == "/api/config":
        saved = save_config(body, config_path)
        return 200, {"status": "ok", "config": saved}

    if method_upper == "POST" and clean_path == "/api/refresh":
        cfg = load_config(config_path)
        app_root = config_path.parent if config_path else resolve_app_root()
        result = run_library_refresh(repo, config=cfg, app_root=app_root)
        return 200, result

    if method_upper == "POST" and clean_path == "/api/search":
        all_items = repo.load_all_items()
        criteria = LibraryFilterCriteria(
            media_category=str(body.get("media_category", "all")),
            source_type=str(body.get("source_type", "all")),
            studio=str(body.get("studio", "all")),
            performer=str(body.get("performer", "all")),
            tag=str(body.get("tag", "all")),
            title_or_keyword=str(body.get("title_or_keyword", "")),
            min_rating=float(body.get("min_rating", 0.0)),
            max_rating=float(body.get("max_rating", 5.0)),
            exact_rating=float(body["exact_rating"]) if body.get("exact_rating") is not None else None,
            only_incomplete=bool(body.get("only_incomplete", False)),
            only_unknown_studio=bool(body.get("only_unknown_studio", False)),
            sort_by=str(body.get("sort_by", "release_date_desc")),
        )
        matched = filter_and_search_library(all_items, criteria)
        return 200, {"status": "ok", "count": len(matched), "items": [i.to_dict() for i in matched]}

    if method_upper == "POST" and clean_path == "/api/rate":
        item_id = str(body.get("item_id", ""))
        try:
            rating = float(body.get("rating", 0.0))
            ok = repo.update_rating(item_id, rating)
        except ValueError as exc:
            return 400, {"status": "error", "message": str(exc)}
        if not ok:
            return 404, {"status": "error", "message": f"Item not found: {item_id}"}
        return 200, {"status": "ok", "item_id": item_id, "rating": rating}

    if method_upper == "POST" and clean_path == "/api/keywords":
        item_id = str(body.get("item_id", ""))
        raw_kw = body.get("keywords", [])
        if isinstance(raw_kw, str):
            kw_list = [k.strip() for k in raw_kw.split(",") if k.strip()]
        else:
            kw_list = [str(k).strip() for k in raw_kw if str(k).strip()]
        ok = repo.update_user_keywords(item_id, kw_list)
        if not ok:
            return 404, {"status": "error", "message": f"Item not found: {item_id}"}
        return 200, {"status": "ok", "item_id": item_id, "user_keywords": kw_list}

    if method_upper == "POST" and clean_path == "/api/play/vlc":
        item_id = str(body.get("item_id", ""))
        item = repo.get_item(item_id)
        if item is None:
            return 404, {"status": "error", "message": f"Item not found: {item_id}"}
        cfg = load_config(config_path)
        vlc_exe = str(
            body.get("vlc_executable")
            or cfg.get("vlc_executable")
            or detect_local_players()[0].executable_path
        )
        start_sec = float(body.get("start_time_sec", item.last_played_pos_sec))
        cmd = build_vlc_launch_command(
            vlc_exe=vlc_exe,
            video_path=item.file_path,
            start_time_sec=start_sec,
            fullscreen=bool(body.get("fullscreen", False)),
            custom_title=item.title or item.file_name,
        )
        android_intent = build_android_intent_uri(item.file_path)
        resp: Dict[str, Any] = {
            "status": "ok",
            "command": cmd,
            "android_intent_uri": android_intent,
        }
        if body.get("launch"):
            try:
                popen_kwargs: Dict[str, Any] = {}
                if sys.platform == "win32":
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 1  # SW_SHOWNORMAL
                    popen_kwargs["startupinfo"] = si
                subprocess.Popen(cmd, **popen_kwargs)
                resp["launched"] = True
            except OSError as exc:
                resp["launched"] = False
                resp["launch_error"] = str(exc)
        return 200, resp

    if method_upper == "POST" and clean_path == "/api/ai/prompt":
        lang = str(body.get("language", "zh"))
        export_mode = str(body.get("export_mode", "incomplete")).strip().lower()
        batch_size = max(10, min(100, int(body.get("batch_size", 25))))
        batch_index = max(0, int(body.get("batch_index", 0)))
        write_to_disk = bool(body.get("write_to_disk", False))
        app_root = config_path.parent if config_path else resolve_app_root()
        md_file = app_root / "AI_KEYWORD_DB.md"

        all_items = repo.load_all_items()
        for it in all_items:
            _refine_item_from_path_clues(it)
            _clean_studio_classification(it)
            it.tags = _clean_genre_tags(it.tags)
            it.refresh_completeness()

        out_path = md_file if (write_to_disk or not md_file.is_file()) else None
        md_text, meta = _export_enhanced_keyword_db_md(
            all_items,
            output_md_path=out_path,
            export_mode=export_mode,
            batch_index=batch_index,
            batch_size=batch_size,
        )
        resolved_mode = meta["export_mode"]
        _, target_items = _select_items_for_ai_export(all_items, resolved_mode)
        clamped_idx = meta["batch_index"]
        start_idx = clamped_idx * batch_size
        batch_items = target_items[start_idx : start_idx + batch_size]
        prompt_text = _build_enhanced_ai_prompt(
            batch_items,
            batch_index=clamped_idx,
            total_batches=meta["total_batches"],
            total_incomplete=meta["total_incomplete"],
            export_mode=resolved_mode,
            language=lang,
        )
        return 200, {
            "status": "ok",
            "prompt": prompt_text,
            "root_markdown_preview": md_text,
            "written_to_disk": bool(out_path),
            "md_file_path": str(md_file),
            **meta,
        }

    if method_upper == "POST" and clean_path == "/api/ai/import":
        raw_content = str(body.get("content", ""))
        prefer_disk = bool(body.get("prefer_disk", False))
        force_tags_only = str(body.get("export_mode", "")).strip().lower() == "tags_only" or bool(body.get("force_tags_only", False))
        app_root = config_path.parent if config_path else resolve_app_root()
        md_file = app_root / "AI_KEYWORD_DB.md"
        items_map = {i.item_id: i for i in repo.load_all_items()}
        updated = 0
        stripped_raw = raw_content.strip()
        is_template_text = stripped_raw.startswith(("你现在是 CineVault Studio", "# CineVault Studio"))

        if prefer_disk and md_file.is_file():
            try:
                disk_md = md_file.read_text(encoding="utf-8")
                updated = _import_ai_completions_resilient(disk_md, items_map, force_tags_only=force_tags_only)
            except OSError:
                pass

        if updated == 0 and stripped_raw and not is_template_text:
            updated = _import_ai_completions_resilient(stripped_raw, items_map, force_tags_only=force_tags_only)
        elif updated == 0 and stripped_raw and is_template_text:
            parts = stripped_raw.split("```")
            if len(parts) >= 5:
                tail_content = "```" + "```".join(parts[3:])
                updated = _import_ai_completions_resilient(tail_content, items_map, force_tags_only=force_tags_only)

        if updated == 0 and not prefer_disk and md_file.is_file():
            try:
                disk_md = md_file.read_text(encoding="utf-8")
                updated = _import_ai_completions_resilient(disk_md, items_map, force_tags_only=force_tags_only)
            except OSError:
                pass

        repo.upsert_items(list(items_map.values()))
        return 200, {"status": "ok", "updated_count": updated, "md_file_path": str(md_file)}

    if method_upper == "POST" and clean_path == "/api/sync/export":
        app_root = config_path.parent if config_path else resolve_app_root()
        out_path = Path(str(body.get("output_path") or (app_root / "cinevault_sync.cvpack")))
        manifest = export_cvpack_bundle(
            repo.load_all_items(),
            out_path,
            include_covers=bool(body.get("include_covers", True)),
        )
        return 200, {"status": "ok", "path": str(out_path), "manifest": manifest}

    if method_upper == "POST" and clean_path == "/api/sync/import":
        cvpack_path = Path(str(body.get("cvpack_path", "")).strip())
        if not cvpack_path.is_file():
            return 400, {"status": "error", "message": f"Sync bundle not found: {cvpack_path}"}
        cfg = load_config(config_path)
        roots: List[Dict[str, str]] = cfg.get("storage_roots") or []
        scanned = scan_storage_roots(roots, compute_hashes=True) if roots else []
        reconciled = import_and_reconcile_cvpack(cvpack_path, scanned)
        if reconciled.synced_items:
            repo.upsert_items(reconciled.synced_items)
        return 200, {
            "status": "ok",
            "matched_by_hash": reconciled.matched_by_hash,
            "matched_by_size_and_name": reconciled.matched_by_size_and_name,
            "unmatched_remote_only": reconciled.unmatched_remote_only,
            "total": len(reconciled.synced_items),
        }

    if method_upper == "POST" and clean_path == "/api/covers/extract-missing":
        ff_path = find_ffmpeg_binary()
        if not ff_path:
            return 400, {
                "status": "error",
                "ffmpeg_available": False,
                "message": "未检测到 FFmpeg，无法执行截帧。您可以点击「安装 FFmpeg」或手动配置到系统 PATH。",
            }
        app_root = config_path.parent if config_path else resolve_app_root()
        covers_dir = app_root / ".cinevault_covers"
        all_items = repo.load_all_items()
        targets = [
            i for i in all_items
            if (not i.cover_path or i.cover_source == CoverSourceType.PLACEHOLDER)
            and Path(i.file_path).is_file()
        ]
        extracted_items: List[MediaItem] = []

        def _extract_one(it: MediaItem) -> None:
            cover_file = covers_dir / f"{it.item_id}.jpg"
            if (cover_file.is_file() and cover_file.stat().st_size > 0) or extract_fallback_cover_frame(
                it.file_path, str(cover_file), duration_sec=it.duration_sec
            ):
                it.cover_path = str(cover_file)
                it.cover_source = CoverSourceType.VIDEO_FRAME
                extracted_items.append(it)

        if targets:
            with ThreadPoolExecutor(max_workers=min(6, len(targets))) as pool:
                list(pool.map(_extract_one, targets))
            if extracted_items:
                repo.upsert_items(extracted_items)

        return 200, {
            "status": "ok",
            "extracted_count": len(extracted_items),
            "total_missing": len(targets),
            "items": [i.to_dict() for i in repo.load_all_items()],
        }

    if method_upper == "POST" and clean_path == "/api/system/install-ffmpeg":
        import shutil
        winget_bin = shutil.which("winget")
        if sys.platform == "win32" and winget_bin:
            try:
                subprocess.Popen(
                    ["cmd", "/c", "start", "cmd", "/k", "winget install -e --id Gyan.FFmpeg.Essentials"]
                )
                return 200, {
                    "status": "ok",
                    "method": "winget",
                    "message": "已打开安装终端执行: winget install -e --id Gyan.FFmpeg.Essentials（安装完成后重启软件即可生效）",
                }
            except OSError as exc:
                return 500, {"status": "error", "message": str(exc)}
        return 200, {
            "status": "ok",
            "method": "manual",
            "download_url": "https://ffmpeg.org/download.html",
            "message": "当前环境未检测到 winget，请访问 https://ffmpeg.org/download.html 下载并将 ffmpeg.exe 放到本程序同目录。",
        }

    return 404, {"status": "error", "message": f"Route not found: {method} {path}"}


def _parse_range_header(range_header: str, file_size: int) -> Optional[Tuple[int, int]]:
    if not range_header.startswith("bytes="):
        return None
    spec = range_header[len("bytes="):].split(",", 1)[0].strip()
    if "-" not in spec:
        return None
    start_str, end_str = spec.split("-", 1)
    if not start_str and not end_str:
        return None
    if start_str:
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
    else:
        suffix = int(end_str)
        start = max(0, file_size - suffix)
        end = file_size - 1
    if start < 0 or start >= file_size or end < start:
        return None
    end = min(end, file_size - 1)
    return start, end


class CineVaultHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler serving the UI, REST API, extracted covers, and Range video streams."""

    repo: SQLiteLibraryRepository
    ui_html_path: Path
    config_path: Path
    covers_dir: Path

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status_code: int, data: Dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        clean_path = urllib.parse.urlparse(self.path).path

        if clean_path in ("/", "/index.html"):
            if not self.ui_html_path.is_file():
                self.send_error(404, "UI file not found")
                return
            html_bytes = self.ui_html_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)
            return

        if clean_path.startswith("/api/covers/"):
            fname = Path(clean_path[len("/api/covers/"):]).name
            cover_file = self.covers_dir / fname
            if not cover_file.is_file():
                self.send_error(404, "Cover not found")
                return
            data = cover_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if clean_path.startswith("/api/local-cover/"):
            item_id = urllib.parse.unquote(clean_path[len("/api/local-cover/"):]).strip("/")
            item = self.repo.get_item(item_id)
            cover_file: Optional[Path] = None
            if item and item.cover_path and not item.cover_path.startswith(("http://", "https://", "/api/")):
                cand = Path(item.cover_path)
                if cand.is_file():
                    cover_file = cand
            if cover_file is None and item:
                cover_file = _find_local_sidecar_cover_file(item.file_path)
            if not cover_file:
                self.send_error(404, "Local cover not found")
                return
            mime_type, _ = mimetypes.guess_type(str(cover_file))
            data = cover_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime_type or "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if clean_path.startswith("/api/stream/"):
            item_id = urllib.parse.unquote(clean_path[len("/api/stream/"):]).strip("/")
            item = self.repo.get_item(item_id)
            if item is None:
                self._send_json(404, {"status": "error", "message": f"Item not found: {item_id}"})
                return
            video_file = Path(item.file_path)
            if not video_file.is_file():
                self._send_json(404, {"status": "error", "message": f"Video file not accessible: {item.file_path}"})
                return
            self._serve_video_range(video_file)
            return

        code, data = dispatch_api_request("GET", clean_path, None, self.repo, config_path=self.config_path)
        self._send_json(code, data)

    def do_POST(self) -> None:
        clean_path = urllib.parse.urlparse(self.path).path
        try:
            payload = self._read_json_body()
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"status": "error", "message": "Invalid JSON body"})
            return
        code, data = dispatch_api_request("POST", clean_path, payload, self.repo, config_path=self.config_path)
        self._send_json(code, data)

    def _serve_video_range(self, video_file: Path) -> None:
        file_size = video_file.stat().st_size
        mime_type, _ = mimetypes.guess_type(str(video_file))
        content_type = mime_type or "video/mp4"
        range_header = self.headers.get("Range")

        if range_header:
            parsed = _parse_range_header(range_header, file_size)
            if parsed is None:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
                return
            start, end = parsed
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        else:
            start = 0
            length = file_size
            self.send_response(200)

        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.end_headers()

        chunk_size = 262144
        remaining = length
        try:
            with video_file.open("rb") as f:
                f.seek(start)
                while remaining > 0:
                    buf = f.read(min(chunk_size, remaining))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    remaining -= len(buf)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


def create_http_server(
    repo: SQLiteLibraryRepository,
    host: str = "127.0.0.1",
    port: int = 8765,
    ui_html_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    covers_dir: Optional[Path] = None,
) -> ThreadingHTTPServer:
    app_root = resolve_app_root()
    bundle_root = resolve_bundle_root()
    resolved_ui = ui_html_path or (bundle_root / "src" / "ui" / "index.html")
    resolved_cfg = config_path or (app_root / "config.json")
    resolved_covers = covers_dir or (app_root / ".cinevault_covers")

    class BoundHandler(CineVaultHTTPRequestHandler):
        pass

    BoundHandler.repo = repo
    BoundHandler.ui_html_path = resolved_ui
    BoundHandler.config_path = resolved_cfg
    BoundHandler.covers_dir = resolved_covers
    return ThreadingHTTPServer((host, port), BoundHandler)
