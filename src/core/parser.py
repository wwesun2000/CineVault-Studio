"""
Tri-Engine Media Filename & Directory Hierarchy Heuristic Parser (`src/core/parser.py`).
Implemented and verified by Argon. DO NOT MODIFY in Hydrogen tasks.

Supports THREE Media Domains + Dynamic AI Custom Studio Registry:
A. Western Adult Media (`MediaCategory.WESTERN_ADULT`):
   - Scene Dot-Notation: `Vixen.25.02.14.Eve.Sweet.And.Alberto.Blanco.Sunset.Villa.XXX.2160p.MP4`
   - Bracketed / Dash-Separated: `[Blacked] (2024-11-08) Violet Myers - Midnight Heat [4K].mkv`
   - Unknown Studio Detection: If a bracketed studio `[NewEuroClub]`, scene prefix `NewBoutique.25.01.10...`,
     or JAV code prefix `NEWJAV-001` is not in the built-in or user/AI-learned studio dictionary,
     marks `is_unknown_studio=True` and preserves `raw_studio_token` so AI can complete and register it!

B. Japanese Adult Video / JAV (`MediaCategory.JAPANESE_JAV`):
   - Standard Maker Codes: `SSIS-001`, `SONE-245`, `IPX-888`, `IPZZ-102`, `STARS-707`, `MIDV-512`,
     `MIDE-900`, `ABP-987`, `ABW-310`, `CAWD-402`, `PRED-550`, `JUL-880`, `ROE-120`, `SNIS-500`
   - Amateur / Uncensored Codes: `FC2-PPV-3109221`, `HEYZO-2810`, `1Pondo-021425_001`, `Carib-021425-001`, `TOKYO-HOT-n1234`
   - Chinese Subtitle / Uncensored Suffix Detection: `-C`, `-ch`, `中文字幕`, `-U`, `-UC`, `无码破解`, `4K`

C. Mainstream Movies & TV Shows (`MediaCategory.MAINSTREAM_MOVIE` / `MAINSTREAM_TV`):
   - Scene Release: `Dune.Part.Two.2024.2160p.UHD.BluRay.Remux.HEVC.Atmos.mkv`
   - Title (Year): `Oppenheimer (2023) [IMAX 4K].mkv`
   - TV Series (`SxxExx`): `Severance.S02E01.2025.2160p.ATVP.WEB-DL.mkv`
"""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from .models import MediaCategory, ParsedMediaTokens, MediaItem


# 1. Built-in Western Adult Studios & Networks
WESTERN_STUDIO_ALIASES: Dict[str, str] = {
    "vixen": "Vixen",
    "vxn": "Vixen",
    "blacked": "Blacked",
    "blk": "Blacked",
    "blackedraw": "Blacked Raw",
    "blacked raw": "Blacked Raw",
    "tushy": "Tushy",
    "tushyraw": "Tushy Raw",
    "tushy raw": "Tushy Raw",
    "deeper": "Deeper",
    "slayed": "Slayed",
    "milfy": "Milfy",
    "wifey": "Wifey",
    "brazzers": "Brazzers",
    "brazzersexxtra": "Brazzers Exxtra",
    "brazzers exxtra": "Brazzers Exxtra",
    "zz": "Brazzers",
    "naughtyamerica": "Naughty America",
    "naughty america": "Naughty America",
    "na": "Naughty America",
    "realitykings": "Reality Kings",
    "reality kings": "Reality Kings",
    "rk": "Reality Kings",
    "mofos": "Mofos",
    "twistys": "Twistys",
    "digitalplayground": "Digital Playground",
    "digital playground": "Digital Playground",
    "dp": "Digital Playground",
    "babes": "Babes",
    "metart": "MetArt",
    "met art": "MetArt",
    "metartx": "MetArtX",
    "sexart": "SexArt",
    "sex art": "SexArt",
    "thelifeerotic": "The Life Erotic",
    "vivthomas": "VivThomas",
    "nubiles": "Nubiles",
    "nubilefilms": "Nubile Films",
    "nubile films": "Nubile Films",
    "bratty sis": "Bratty Sis",
    "brattysis": "Bratty Sis",
    "stepsiblingscaught": "Step Siblings Caught",
    "teamskeet": "TeamSkeet",
    "team skeet": "TeamSkeet",
    "mylf": "MYLF",
    "bangbros": "BangBros",
    "bang bros": "BangBros",
    "evilangel": "Evil Angel",
    "evil angel": "Evil Angel",
    "julesjordan": "Jules Jordan",
    "jules jordan": "Jules Jordan",
    "manuelferrara": "Manuel Ferrara",
    "dorcel": "Marc Dorcel",
    "marcdorcel": "Marc Dorcel",
    "dorcelclub": "DorcelClub",
    "wicked": "Wicked Pictures",
    "wickedpictures": "Wicked Pictures",
    "adulttime": "Adult Time",
    "adult time": "Adult Time",
    "puretaboo": "Pure Taboo",
    "pure taboo": "Pure Taboo",
    "girlsway": "Girlsway",
    "sweetheartvideo": "Sweetheart Video",
    "erito": "Erito",
    "hegre": "Hegre",
    "femjoy": "FemJoy",
    "xart": "X-Art",
    "x-art": "X-Art",
    "passionhd": "Passion-HD",
    "passion-hd": "Passion-HD",
    "tiny4k": "Tiny4K",
    "lubed": "Lubed",
    "holed": "Holed",
    "pervmom": "PervMom",
    "propertysex": "PropertySex",
    "publicagent": "PublicAgent",
    "fakehub": "FakeHub",
    "private": "Private",
    "harmonyvision": "Harmony Vision",
    "new sensations": "New Sensations",
    "newsensations": "New Sensations",
    "sweet sinner": "Sweet Sinner",
    "sweetsinner": "Sweet Sinner",
    "cherrypimps": "Cherry Pimps",
    "kink": "Kink",
}

# 2. Built-in Japanese JAV Code Prefix -> Canonical Japanese Maker/Studio Map
JAV_PREFIX_TO_STUDIO: Dict[str, str] = {
    "SSIS": "S1 NO.1 STYLE",
    "SONE": "S1 NO.1 STYLE",
    "SSNI": "S1 NO.1 STYLE",
    "SNIS": "S1 NO.1 STYLE",
    "SOE": "S1 NO.1 STYLE",
    "IPX": "IdeaPocket",
    "IPZZ": "IdeaPocket",
    "IPZ": "IdeaPocket",
    "SUPD": "IdeaPocket",
    "MIDV": "MOODYZ",
    "MIDE": "MOODYZ",
    "MIRD": "MOODYZ",
    "MIAA": "MOODYZ",
    "MIAB": "MOODYZ",
    "STARS": "SOD Create",
    "SDJS": "SOD Create",
    "SDNM": "SOD Create",
    "SDAB": "SOD Create",
    "ABP": "Prestige",
    "ABW": "Prestige",
    "ABF": "Prestige",
    "ABS": "Prestige",
    "CAWD": "kawaii*",
    "KAWD": "kawaii*",
    "PRED": "Premium",
    "PGD": "Premium",
    "PPPE": "OPPAI",
    "PPP": "OPPAI",
    "JUL": "Madonna",
    "JUQ": "Madonna",
    "JUSD": "Madonna",
    "ROE": "Madonna",
    "WANZ": "Wanz Factory",
    "WAAA": "Wanz Factory",
    "EBOD": "E-BODY",
    "EBWH": "E-BODY",
    "FSDSS": "FALENO",
    "FADSS": "FALENO",
    "ATID": "Attackers",
    "ADN": "Attackers",
    "RBD": "Attackers",
    "SHKD": "Attackers",
    "DASD": "DAS!",
    "DLDSS": "DAHLIA",
    "HMN": "Honnaka",
    "HND": "Honnaka",
    "MEYD": "Tameike Goro",
    "VENX": "Venus",
    "START": "SOD Create",
    "FC2": "FC2-PPV Amateur",
    "HEYZO": "HEYZO Uncensored",
    "1PON": "1Pondo Uncensored",
    "CARIB": "Caribbeancom",
}

# 3. Built-in Mainstream Film / TV Studios
MAINSTREAM_STUDIO_ALIASES: Dict[str, str] = {
    "warner": "Warner Bros. Pictures",
    "warnerbros": "Warner Bros. Pictures",
    "universal": "Universal Pictures",
    "paramount": "Paramount Pictures",
    "a24": "A24",
    "sony": "Sony Pictures",
    "columbia": "Columbia Pictures",
    "20thcentury": "20th Century Studios",
    "fox": "20th Century Studios",
    "disney": "Walt Disney Pictures",
    "marvel": "Marvel Studios",
    "lionsgate": "Lionsgate",
    "legendary": "Legendary Pictures",
    "syncopy": "Syncopy",
    "netflix": "Netflix",
    "hbo": "HBO",
    "appletv": "Apple TV+",
    "atvp": "Apple TV+",
    "amax": "Amazon MGM Studios",
}

# 4. Runtime AI/User Extensible Studio Registry (Allows AI to permanently register newly discovered studios/labels)
CUSTOM_STUDIO_REGISTRY: Dict[str, Dict[str, str]] = {
    "western_adult": {},   # alias_lower -> Canonical Studio Name
    "japanese_jav": {},    # prefix_upper -> Canonical JAV Maker Name
    "mainstream": {},      # alias_lower -> Canonical Mainstream Studio Name
}


def register_custom_studio(
    alias_or_prefix: str,
    canonical_name: str,
    category: MediaCategory = MediaCategory.WESTERN_ADULT,
) -> None:
    """
    Registers a newly discovered studio or JAV code prefix (e.g. learned via AI completion)
    into the runtime registry so all subsequent scans recognize it immediately.
    """
    clean_alias = alias_or_prefix.strip()
    clean_canon = canonical_name.strip()
    if not clean_alias or not clean_canon:
        return
    if category == MediaCategory.JAPANESE_JAV:
        CUSTOM_STUDIO_REGISTRY["japanese_jav"][clean_alias.upper()] = clean_canon
    elif category in (MediaCategory.MAINSTREAM_MOVIE, MediaCategory.MAINSTREAM_TV):
        CUSTOM_STUDIO_REGISTRY["mainstream"][re.sub(r"[\s._\-]+", "", clean_alias.lower())] = clean_canon
    else:
        CUSTOM_STUDIO_REGISTRY["western_adult"][re.sub(r"[\s._\-]+", "", clean_alias.lower())] = clean_canon
        CUSTOM_STUDIO_REGISTRY["western_adult"][clean_alias.lower()] = clean_canon


def save_custom_studio_registry(json_path: str | Path) -> None:
    Path(json_path).write_text(json.dumps(CUSTOM_STUDIO_REGISTRY, indent=2, ensure_ascii=False), encoding="utf-8")


def load_custom_studio_registry(json_path: str | Path) -> Dict[str, Dict[str, str]]:
    p = Path(json_path)
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        for k in ("western_adult", "japanese_jav", "mainstream"):
            if isinstance(data.get(k), dict):
                CUSTOM_STUDIO_REGISTRY[k].update(data[k])
    return CUSTOM_STUDIO_REGISTRY


RESOLUTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:2160p|4k|uhd)\b", re.IGNORECASE), "4K"),
    (re.compile(r"\b(?:1440p|2k|qhd)\b", re.IGNORECASE), "1440p"),
    (re.compile(r"\b(?:1080p|fhd|fullhd)\b", re.IGNORECASE), "1080p"),
    (re.compile(r"\b(?:720p|hd)\b", re.IGNORECASE), "720p"),
    (re.compile(r"\b(?:480p|sd)\b", re.IGNORECASE), "480p"),
]

GENRE_KEYWORD_MAP: Dict[str, str] = {
    "anal": "Anal",
    "dp": "Double Penetration",
    "interracial": "Interracial",
    "lesbian": "Lesbian",
    "girlsway": "Lesbian",
    "threesome": "Threesome",
    "foursome": "Group",
    "gangbang": "Gangbang",
    "milf": "MILF",
    "mature": "Mature",
    "blonde": "Blonde",
    "brunette": "Brunette",
    "redhead": "Redhead",
    "pov": "POV",
    "massage": "Massage",
    "office": "Office",
    "lingerie": "Lingerie",
    "stockings": "Stockings",
    "outdoor": "Outdoor",
    "glamour": "Glamour",
    "artistic": "Artistic",
    "uncensored": "无码 (Uncensored)",
    "无码": "无码 (Uncensored)",
    "破解": "无码流出",
    "中字": "中文字幕",
    "中文字幕": "中文字幕",
    "字幕": "中文字幕",
    "imax": "IMAX",
    "remux": "BluRay Remux",
    "bluray": "Blu-Ray",
    "hdr": "HDR",
    "dv": "Dolby Vision",
    "atmos": "Dolby Atmos",
    "scifi": "Sci-Fi",
    "thriller": "Thriller",
    "action": "Action",
    "drama": "Drama",
    "4k": "4K Ultra HD",
    "60fps": "60FPS",
    "vr": "VR",
}

NOISE_TOKENS = {
    "xxx", "mp4", "mkv", "avi", "wmv", "mov", "1080p", "2160p", "720p", "480p", "4k", "uhd",
    "hevc", "x264", "x265", "h264", "h265", "aac", "webrip", "web-dl", "web", "prt", "sd",
    "hd", "fhd", "60fps", "split", "scene", "full", "video", "rarbg", "ktr", "xvid", "ac3",
    "bluray", "remux", "imax", "atmos", "ddp5", "ddp", "truehd", "hdr", "hdr10", "dv", "proper",
    "repack", "extended", "directors", "cut", "atvp", "nf", "amzn", "hmax", "dts",
}

GENERIC_FOLDER_NAMES = {
    "videos", "video", "movies", "movie", "media", "downloads", "download", "collection",
    "vault", "western", "eu", "us", "av", "adult", "share", "samba", "smb", "cloud", "nas",
    "mnt", "storage", "disk", "drive", "root", "library", "scenes", "4k", "1080p", "new",
    "cinema", "films", "film", "tv", "series", "shows", "mainstream", "jav", "japan", "jp",
}

MAINSTREAM_PATH_HINTS = {"movies", "cinema", "films", "boxoffice", "imdb", "tmdb", "tv", "series", "imax"}
JAV_PATH_HINTS = {"jav", "japan", "japanese", "番号", "日系", "日本", "步兵", "骑兵", "s1", "moodyz", "ideapocket"}

# Non-JAV technical prefixes to exclude from JAV code regex
NON_JAV_PREFIXES = {
    "H264", "H265", "X264", "X265", "HEVC", "WEB", "WEBDL", "AAC", "AC3", "DTS", "HDR",
    "UHD", "FHD", "IMDB", "TMDB", "PART", "DISC", "CD", "DVD", "SCENE", "MP4", "MKV",
}

# 1. Japanese JAV FC2-PPV regex: `FC2-PPV-3109221` or `FC2 PPV 3109221`
JAV_FC2_REGEX = re.compile(
    r"\bFC2[\s._\-]*(?:PPV[\s._\-]*)?(?P<num>\d{5,8})\b",
    re.IGNORECASE,
)

# 2. Japanese Standard JAV Code regex: `SSIS-001`, `IPX-888-C`, `STARS-707-UC`, `HEYZO-2810`
JAV_STD_CODE_REGEX = re.compile(
    r"(?:^|[\s\[\]()_.\-])(?P<prefix>[A-Za-z]{2,6})[\-_](?P<num>\d{3,5})(?P<suffix>(?:[\-_](?:C|CH|U|UC|4K))*)(?=$|[\s\[\]()_.\-])",
    re.IGNORECASE,
)

# 3. Adult Scene dot-notation regex: Studio.YY.MM.DD.Performer.And.Performer.Title.XXX...
SCENE_DOT_REGEX = re.compile(
    r"^(?P<studio>[A-Za-z0-9_-]+)\.(?P<yy>\d{2})\.(?P<mm>0[1-9]|1[0-2])\.(?P<dd>0[1-9]|[12]\d|3[01])\.(?P<rest>.+)$"
)

# 4. TV Series SxxExx regex: Title.S01E02...
TV_EPISODE_REGEX = re.compile(
    r"^(?P<title>.+?)[.\s_-]+[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,3})\b(?P<rest>.*)$"
)

# 5. Mainstream Movie Release regex: Title.Words.(1990..2029).(2160p|1080p|BluRay|WEB|IMAX|Remux...)
MAINSTREAM_MOVIE_DOT_REGEX = re.compile(
    r"^(?P<title>[A-Za-z0-9][A-Za-z0-9.\s'_-]+?)[.\s(\[]+(?P<yyyy>19\d{2}|20[0-2]\d)[)\].\s]+(?P<tech>(?:2160p|1080p|720p|4K|UHD|BluRay|BDRip|WEBRip|WEB-DL|Remux|IMAX|HDR|DV|x264|x265|HEVC).*)$",
    re.IGNORECASE,
)

# 6. Title (Year) clean format: `Interstellar (2014) [IMAX 4K]`
TITLE_PAREN_YEAR_REGEX = re.compile(
    r"^(?P<title>[^(\[\-]+?)\s*\((?P<yyyy>19\d{2}|20[0-2]\d)\)(?P<rest>.*)$"
)

ISO_DATE_REGEX = re.compile(
    r"\b(?P<yyyy>19\d{2}|20\d{2})[-._](?P<mm>0[1-9]|1[0-2])[-._](?P<dd>0[1-9]|[12]\d|3[01])\b"
)

SHORT_DATE_REGEX = re.compile(
    r"(?:^|[\s.\-_(\[])(?P<yy>\d{2})[-._](?P<mm>0[1-9]|1[0-2])[-._](?P<dd>0[1-9]|[12]\d|3[01])(?:$|[\s.\-_)\]])"
)

YEAR_ONLY_REGEX = re.compile(r"\b(?P<yyyy>20[0-2]\d|19\d{2})\b")


def normalize_studio_name(raw_candidate: str) -> Optional[str]:
    """
    Matches a raw token against built-in AND AI/user-registered Western Adult studios.
    """
    if not raw_candidate:
        return None
    cleaned = re.sub(r"[\s._\-]+", " ", raw_candidate.strip()).lower()
    compact = re.sub(r"[\s._\-]+", "", cleaned)
    if cleaned in CUSTOM_STUDIO_REGISTRY["western_adult"]:
        return CUSTOM_STUDIO_REGISTRY["western_adult"][cleaned]
    if compact in CUSTOM_STUDIO_REGISTRY["western_adult"]:
        return CUSTOM_STUDIO_REGISTRY["western_adult"][compact]
    if cleaned in WESTERN_STUDIO_ALIASES:
        return WESTERN_STUDIO_ALIASES[cleaned]
    if compact in WESTERN_STUDIO_ALIASES:
        return WESTERN_STUDIO_ALIASES[compact]
    return None


def normalize_jav_maker(prefix: str) -> Optional[str]:
    """
    Maps a JAV code prefix (e.g., 'SSIS', 'IPX', 'STARS') to its Japanese Maker/Studio name,
    checking both the built-in map and the AI-registered custom JAV studio registry.
    """
    if not prefix:
        return None
    up = prefix.strip().upper()
    if up in CUSTOM_STUDIO_REGISTRY["japanese_jav"]:
        return CUSTOM_STUDIO_REGISTRY["japanese_jav"][up]
    return JAV_PREFIX_TO_STUDIO.get(up)


def normalize_mainstream_studio(raw_candidate: str) -> Optional[str]:
    if not raw_candidate:
        return None
    compact = re.sub(r"[\s._\-]+", "", raw_candidate.strip()).lower()
    if compact in CUSTOM_STUDIO_REGISTRY["mainstream"]:
        return CUSTOM_STUDIO_REGISTRY["mainstream"][compact]
    return MAINSTREAM_STUDIO_ALIASES.get(compact)


def _extract_resolution(text: str) -> Optional[str]:
    for pattern, label in RESOLUTION_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _extract_date(text: str) -> Tuple[Optional[str], str]:
    m_iso = ISO_DATE_REGEX.search(text)
    if m_iso:
        iso = f"{m_iso.group('yyyy')}-{m_iso.group('mm')}-{m_iso.group('dd')}"
        cleaned = text[:m_iso.start()] + " " + text[m_iso.end():]
        return iso, cleaned

    m_short = SHORT_DATE_REGEX.search(text)
    if m_short:
        yy = int(m_short.group("yy"))
        yyyy = 2000 + yy if yy <= 69 else 1900 + yy
        iso = f"{yyyy:04d}-{m_short.group('mm')}-{m_short.group('dd')}"
        cleaned = text[:m_short.start()] + " " + text[m_short.end():]
        return iso, cleaned

    return None, text


def _clean_title_tokens(raw_text: str) -> str:
    tokens = re.split(r"[\s._]+", raw_text.strip(" -_—.()[]"))
    filtered = []
    for t in tokens:
        low = t.lower().strip("[]()")
        if not low or low in NOISE_TOKENS:
            continue
        filtered.append(t)
    return " ".join(filtered).strip(" -_—.")


def _split_performers(perf_segment: str) -> List[str]:
    normalized = re.sub(r"\band\b|\bfeat\.?\b|\bft\.?\b|&|,", ",", perf_segment, flags=re.IGNORECASE)
    parts = [p.strip(" ._-()[]") for p in normalized.split(",")]
    performers: List[str] = []
    for part in parts:
        words = [w for w in re.split(r"[\s._]+", part) if w and w.lower() not in NOISE_TOKENS]
        if 1 <= len(words) <= 4:
            name = " ".join(w.capitalize() if w.islower() else w for w in words)
            if name and name not in performers:
                performers.append(name)
    return performers


def _try_parse_jav(
    stem: str,
    parent_dirs: List[str],
    detected_tags: List[str],
    resolution: Optional[str],
    raw_path: str,
) -> Optional[ParsedMediaTokens]:
    """
    Detects and parses Japanese Adult Video (JAV) filenames and parent directories.
    Handles standard maker codes (`SSIS-001`, `IPX-888-C`, `STARS-707`) and `FC2-PPV-xxxxxxx`.
    If the JAV prefix is not in `JAV_PREFIX_TO_STUDIO` or `CUSTOM_STUDIO_REGISTRY`, flags
    `is_unknown_studio=True` so AI can identify the new Japanese maker/label!
    """
    # Check FC2-PPV first
    m_fc2 = JAV_FC2_REGEX.search(stem)
    if m_fc2:
        code = f"FC2-PPV-{m_fc2.group('num')}"
        tags = list(detected_tags)
        if "FC2 素人" not in tags:
            tags.append("FC2 素人")
        if "无码 (Uncensored)" not in tags:
            tags.append("无码 (Uncensored)")
        remainder = (stem[:m_fc2.start()] + " " + stem[m_fc2.end():]).strip(" -_[]()")
        return ParsedMediaTokens(
            raw_path=raw_path,
            media_category=MediaCategory.JAPANESE_JAV,
            jav_code=code,
            studio=normalize_jav_maker("FC2") or "FC2-PPV Amateur",
            is_unknown_studio=False,
            title=_clean_title_tokens(remainder) or code,
            resolution=resolution,
            tags=tags,
            confidence=0.93,
        )

    # Check standard JAV code `[SSIS-001]` or `SSIS-001-C`
    m_jav = JAV_STD_CODE_REGEX.search(stem)
    if m_jav:
        prefix = m_jav.group("prefix").upper()
        if prefix not in NON_JAV_PREFIXES:
            num = m_jav.group("num")
            suffix_raw = (m_jav.group("suffix") or "").upper()
            jav_code = f"{prefix}-{num}"
            tags = list(detected_tags)

            if any(s in suffix_raw for s in ("-C", "_C", "-CH", "_CH")):
                if "中文字幕" not in tags:
                    tags.append("中文字幕")
            if any(s in suffix_raw for s in ("-U", "_U", "-UC", "_UC")):
                if "无码 (Uncensored)" not in tags:
                    tags.append("无码 (Uncensored)")

            known_maker = normalize_jav_maker(prefix)
            is_unknown = known_maker is None
            studio_label = known_maker if known_maker else f"待AI识别日系厂牌 ({prefix})"

            # Extract date if present in stem or parent dirs
            date_found, stem_no_date = _extract_date(stem)
            remainder = (stem_no_date[:m_jav.start()] + " " + stem_no_date[m_jav.end():]).strip()
            # Strip brackets around the JAV code if left over
            remainder = re.sub(r"\[\s*\]|\(\s*\)", " ", remainder).strip(" -_[]()")

            performers: List[str] = []
            title_str = remainder

            # Common JAV pattern: `SSIS-001 河北彩花 标题...` or `[SSIS-001] 河北彩花 - 标题`
            dash_parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", remainder) if p.strip()]
            if len(dash_parts) >= 2:
                performers = [p.strip() for p in dash_parts[0].split(",") if p.strip()]
                title_str = " - ".join(dash_parts[1:])
            else:
                # Check if parent folder is an actress name or studio
                for folder in reversed(parent_dirs):
                    f_clean = folder.strip()
                    if not f_clean or f_clean.lower() in GENERIC_FOLDER_NAMES or f_clean.lower() in JAV_PATH_HINTS:
                        continue
                    if not date_found:
                        f_date, _ = _extract_date(f_clean)
                        if f_date:
                            date_found = f_date
                            continue
                    if not performers and len(f_clean) <= 16 and not f_clean.isascii():
                        performers = [f_clean]

            return ParsedMediaTokens(
                raw_path=raw_path,
                media_category=MediaCategory.JAPANESE_JAV,
                jav_code=jav_code,
                studio=studio_label,
                is_unknown_studio=is_unknown,
                raw_studio_token=prefix if is_unknown else None,
                title=_clean_title_tokens(title_str) or jav_code,
                performers=performers,
                release_date=date_found,
                resolution=resolution,
                tags=tags,
                confidence=0.92 if not is_unknown else 0.72,
            )

    return None


def parse_western_media_path(
    file_path: str,
    parent_dirs: Optional[List[str]] = None,
) -> ParsedMediaTokens:
    """
    Tri-Engine Parser:
    Automatically detects and parses:
    1. Japanese JAV (`MediaCategory.JAPANESE_JAV`) with `jav_code` and maker prefix lookup.
    2. Western Adult Media (`MediaCategory.WESTERN_ADULT`) with studio lookup & unknown studio detection.
    3. Mainstream Cinema & TV Series (`MediaCategory.MAINSTREAM_MOVIE` / `MediaCategory.MAINSTREAM_TV`).
    """
    norm_path = file_path.replace("\\", "/")
    p = Path(norm_path)
    stem = p.stem

    if parent_dirs is None:
        parent_dirs = [part for part in p.parent.parts if part not in ("/", "\\", "") and not part.endswith(":")]

    result = ParsedMediaTokens(raw_path=file_path)
    combined_context = " ".join(parent_dirs + [stem])

    # 1. Resolution & automatic tags
    result.resolution = _extract_resolution(combined_context)
    detected_tags: List[str] = []
    if result.resolution == "4K":
        detected_tags.append("4K Ultra HD")
    for kw, tag_label in GENRE_KEYWORD_MAP.items():
        if kw.isascii():
            if re.search(rf"\b{re.escape(kw)}\b", combined_context, re.IGNORECASE):
                if tag_label not in detected_tags:
                    detected_tags.append(tag_label)
        else:
            if kw in combined_context and tag_label not in detected_tags:
                detected_tags.append(tag_label)

    # 2. Strategy J: Japanese JAV Code Detection (`SSIS-001`, `IPX-888-C`, `FC2-PPV-3109221`)
    jav_parsed = _try_parse_jav(stem, parent_dirs, detected_tags, result.resolution, file_path)
    if jav_parsed is not None:
        return jav_parsed

    has_xxx_marker = bool(re.search(r"\bXXX\b", stem, re.IGNORECASE))
    known_adult_studio_in_path = None
    known_mainstream_studio_in_path = None
    for folder in reversed(parent_dirs):
        st_adult = normalize_studio_name(folder)
        if st_adult and not known_adult_studio_in_path:
            known_adult_studio_in_path = st_adult
        st_main = normalize_mainstream_studio(folder)
        if st_main and not known_mainstream_studio_in_path:
            known_mainstream_studio_in_path = st_main

    # 3. Strategy A1: Adult Scene Dot-Notation (`Studio.YY.MM.DD.Performer.Title.XXX.1080p`)
    m_scene = SCENE_DOT_REGEX.match(stem)
    if m_scene:
        raw_studio = m_scene.group("studio")
        result.media_category = MediaCategory.WESTERN_ADULT
        canon_studio = normalize_studio_name(raw_studio)
        if canon_studio:
            result.studio = canon_studio
            result.is_unknown_studio = False
        else:
            result.studio = raw_studio
            result.is_unknown_studio = True
            result.raw_studio_token = raw_studio

        yy = int(m_scene.group("yy"))
        yyyy = 2000 + yy if yy <= 69 else 1900 + yy
        result.release_date = f"{yyyy:04d}-{m_scene.group('mm')}-{m_scene.group('dd')}"

        rest = m_scene.group("rest")
        rest = re.split(r"\.(?:XXX|2160p|1080p|720p|480p|4K)\b", rest, flags=re.IGNORECASE)[0]
        tokens = [t for t in rest.split(".") if t]

        and_indices = [i for i, t in enumerate(tokens) if t.lower() == "and"]
        if and_indices and and_indices[0] >= 1:
            idx = and_indices[0]
            perf_end = min(len(tokens), idx + 3)
            perf_str = " ".join(tokens[:idx]) + " , " + " ".join(tokens[idx + 1:perf_end])
            result.performers = _split_performers(perf_str)
            title_tokens = tokens[perf_end:]
            result.title = " ".join(title_tokens) if title_tokens else " ".join(tokens[idx + 1:])
        elif len(tokens) >= 4:
            result.performers = [" ".join(tokens[:2])]
            result.title = " ".join(tokens[2:])
        elif len(tokens) >= 2:
            result.performers = [tokens[0]]
            result.title = " ".join(tokens[1:])
        else:
            result.title = " ".join(tokens)

        result.tags = detected_tags
        result.confidence = 0.94 if not result.is_unknown_studio else 0.75
        return result

    # 4. Strategy B1: Mainstream TV Series (`Title.S01E02...`)
    m_tv = TV_EPISODE_REGEX.match(stem)
    if m_tv and not has_xxx_marker and not known_adult_studio_in_path:
        result.media_category = MediaCategory.MAINSTREAM_TV
        result.title = _clean_title_tokens(m_tv.group("title"))
        result.season = int(m_tv.group("season"))
        result.episode = int(m_tv.group("episode"))
        m_yr = YEAR_ONLY_REGEX.search(m_tv.group("rest")) or YEAR_ONLY_REGEX.search(combined_context)
        if m_yr:
            result.release_date = m_yr.group("yyyy")
        result.studio = known_mainstream_studio_in_path or "TV Network"
        result.tags = detected_tags
        result.confidence = 0.90
        return result

    # 5. Strategy B2: Mainstream Movie Scene Release (`Dune.Part.Two.2024.2160p.UHD.BluRay...`)
    m_movie_dot = MAINSTREAM_MOVIE_DOT_REGEX.match(stem)
    if m_movie_dot and not has_xxx_marker and not known_adult_studio_in_path:
        raw_title = m_movie_dot.group("title").replace(".", " ").strip()
        first_word = raw_title.split()[0] if raw_title else ""
        if not normalize_studio_name(first_word):
            result.media_category = MediaCategory.MAINSTREAM_MOVIE
            result.title = _clean_title_tokens(raw_title)
            result.release_date = m_movie_dot.group("yyyy")
            result.studio = known_mainstream_studio_in_path or ""
            result.tags = detected_tags
            result.confidence = 0.88
            return result

    # 6. Strategy B3: Mainstream Movie `Title (Year)` format (`Interstellar (2014) [IMAX 4K]`)
    m_paren_yr = TITLE_PAREN_YEAR_REGEX.match(stem)
    if m_paren_yr and not has_xxx_marker and not known_adult_studio_in_path and " - " not in stem:
        clean_t = _clean_title_tokens(m_paren_yr.group("title"))
        if not normalize_studio_name(clean_t):
            result.media_category = MediaCategory.MAINSTREAM_MOVIE
            result.title = clean_t
            result.release_date = m_paren_yr.group("yyyy")
            result.studio = known_mainstream_studio_in_path or ""
            result.tags = detected_tags
            result.confidence = 0.86
            return result

    # 7. Strategy A2: Bracketed & Dash-Separated Adult (or General) Filenames
    working = stem

    bracket_matches = re.findall(r"\[([^\]]+)\]", working)
    for bm in bracket_matches:
        canon_studio = normalize_studio_name(bm)
        if canon_studio and not result.studio:
            result.studio = canon_studio
            result.media_category = MediaCategory.WESTERN_ADULT
            working = working.replace(f"[{bm}]", " ").strip()
        elif not _extract_resolution(bm) and not ISO_DATE_REGEX.search(bm):
            if not result.studio and len(bm) <= 28:
                result.studio = bm.strip()
                result.is_unknown_studio = True
                result.raw_studio_token = bm.strip()
                working = working.replace(f"[{bm}]", " ").strip()

    date_found, working = _extract_date(working)
    if date_found:
        result.release_date = date_found

    working = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", working)
    dash_parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", working) if p.strip()]

    if len(dash_parts) >= 3:
        maybe_studio = normalize_studio_name(dash_parts[0])
        if maybe_studio:
            result.studio = maybe_studio
            result.is_unknown_studio = False
        elif not result.studio:
            result.studio = dash_parts[0].strip()
            result.is_unknown_studio = True
            result.raw_studio_token = dash_parts[0].strip()
        result.performers = _split_performers(dash_parts[1])
        result.title = _clean_title_tokens(" - ".join(dash_parts[2:]))
    elif len(dash_parts) == 2:
        p0_studio = normalize_studio_name(dash_parts[0])
        if p0_studio and not result.studio:
            result.studio = p0_studio
            result.title = _clean_title_tokens(dash_parts[1])
        else:
            result.performers = _split_performers(dash_parts[0])
            result.title = _clean_title_tokens(dash_parts[1])
    elif len(dash_parts) == 1:
        result.title = _clean_title_tokens(dash_parts[0])

    # 8. Strategy C: Parent Directory Inheritance
    for folder in reversed(parent_dirs):
        folder_clean = folder.strip()
        low_folder = folder_clean.lower()
        if not folder_clean or low_folder in GENERIC_FOLDER_NAMES:
            if low_folder in MAINSTREAM_PATH_HINTS and not known_adult_studio_in_path and not result.studio:
                result.media_category = MediaCategory.MAINSTREAM_MOVIE
            continue

        if not result.release_date:
            f_date, _ = _extract_date(folder_clean)
            if f_date:
                result.release_date = f_date
            else:
                m_yr = YEAR_ONLY_REGEX.search(folder_clean)
                if m_yr and len(folder_clean) <= 6:
                    result.release_date = m_yr.group("yyyy")
                    continue

        f_studio = normalize_studio_name(folder_clean)
        if f_studio and (not result.studio or result.is_unknown_studio):
            result.studio = f_studio
            result.is_unknown_studio = False
            result.media_category = MediaCategory.WESTERN_ADULT
            continue

        f_main_studio = normalize_mainstream_studio(folder_clean)
        if f_main_studio and not result.studio:
            result.studio = f_main_studio
            result.is_unknown_studio = False
            result.media_category = MediaCategory.MAINSTREAM_MOVIE
            continue

        if not result.performers and " " in folder_clean and not f_studio:
            words = folder_clean.split()
            if len(words) == 2 and all(w[0].isupper() for w in words if w):
                result.performers = [folder_clean]
                continue

        if not result.studio and len(folder_clean) <= 25 and low_folder not in GENERIC_FOLDER_NAMES:
            result.studio = folder_clean
            result.is_unknown_studio = True
            result.raw_studio_token = folder_clean

    if not result.release_date:
        m_yr = YEAR_ONLY_REGEX.search(stem)
        if m_yr:
            result.release_date = m_yr.group("yyyy")

    result.tags = detected_tags

    score = 0.15
    if result.studio and not result.is_unknown_studio:
        score += 0.30
    elif result.studio and result.is_unknown_studio:
        score += 0.10
    if result.title:
        score += 0.25
    if result.performers:
        score += 0.20
    if result.release_date:
        score += 0.10
    result.confidence = round(min(1.0, score), 2)
    return result


def apply_parsed_tokens_to_item(item: MediaItem) -> MediaItem:
    """
    Populates a MediaItem's fields from `parse_western_media_path` without overwriting
    non-empty user-curated fields.
    """
    tokens = parse_western_media_path(item.file_path, item.parent_dirs)
    item.media_category = tokens.media_category
    if tokens.jav_code and not item.jav_code:
        item.jav_code = tokens.jav_code
    if not item.studio and tokens.studio:
        item.studio = tokens.studio
        item.is_unknown_studio = tokens.is_unknown_studio
    if not item.title and tokens.title:
        item.title = tokens.title
    if not item.performers and tokens.performers:
        item.performers = list(tokens.performers)
    if not item.release_date and tokens.release_date:
        item.release_date = tokens.release_date
    if not item.resolution and tokens.resolution:
        item.resolution = tokens.resolution
    if item.season is None and tokens.season is not None:
        item.season = tokens.season
    if item.episode is None and tokens.episode is not None:
        item.episode = tokens.episode
    for t in tokens.tags:
        if t not in item.tags:
            item.tags.append(t)
    item.refresh_completeness()
    return item
