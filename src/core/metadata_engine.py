"""
Tri-Track Online Metadata Scoring, Multi-Faceted Search & Filter Engine, Cover Fallback Strategy
& Kodi/Jellyfin NFO Exporter (`src/core/metadata_engine.py`).
Implemented and verified by Argon. DO NOT MODIFY in Hydrogen tasks.

Supports all three media categories:
1. `MediaCategory.WESTERN_ADULT` -> ThePornDB / StashDB
2. `MediaCategory.JAPANESE_JAV` -> JavDB / FANZA / JavBus (matched primarily by `jav_code`)
3. `MediaCategory.MAINSTREAM_MOVIE` / `MAINSTREAM_TV` -> TMDB / OMDb / IMDb
"""

from __future__ import annotations
import html
import re
from typing import List, Optional
from .models import (
    MediaCategory,
    MediaItem,
    ParsedMediaTokens,
    OnlineMetadataCandidate,
    CoverSourceType,
    LibraryFilterCriteria,
)
from .parser import register_custom_studio


def select_metadata_providers(category: MediaCategory) -> List[str]:
    """
    Returns the prioritized metadata providers for the item's category:
    - WESTERN_ADULT: ["ThePornDB", "StashDB"]
    - JAPANESE_JAV: ["JavDB", "FANZA"]
    - MAINSTREAM_MOVIE / MAINSTREAM_TV: ["TMDB", "OMDb"]
    """
    if category == MediaCategory.JAPANESE_JAV:
        return ["JavDB", "FANZA"]
    if category in (MediaCategory.MAINSTREAM_MOVIE, MediaCategory.MAINSTREAM_TV):
        return ["TMDB", "OMDb"]
    return ["ThePornDB", "StashDB"]


def build_search_query(
    tokens: ParsedMediaTokens,
    extra_keywords: Optional[List[str]] = None,
) -> str:
    """
    Constructs a clean, high-signal search string tailored to the category:
    - For Japanese JAV: prioritizes `jav_code` (e.g. `SSIS-001`) + `performers` + `extra_keywords`.
    - For Mainstream Movies/TV: prioritizes `title` + `release_date (year)` + `extra_keywords`.
    - For Western Adult Scenes: prioritizes `studio` + `release_date` + `performers` + `title` + `extra_keywords`.
    """
    parts: List[str] = []
    if tokens.media_category == MediaCategory.JAPANESE_JAV:
        if tokens.jav_code:
            parts.append(tokens.jav_code)
        if tokens.performers:
            parts.extend(tokens.performers[:2])
        if tokens.title and tokens.title != tokens.jav_code:
            parts.append(tokens.title)
    elif tokens.media_category in (MediaCategory.MAINSTREAM_MOVIE, MediaCategory.MAINSTREAM_TV):
        if tokens.title:
            parts.append(tokens.title)
        if tokens.release_date:
            parts.append(tokens.release_date[:4])
    else:
        if tokens.studio and not tokens.is_unknown_studio:
            parts.append(tokens.studio)
        if tokens.release_date:
            parts.append(tokens.release_date)
        if tokens.performers:
            parts.extend(tokens.performers[:2])
        if tokens.title:
            parts.append(tokens.title)

    if extra_keywords:
        for kw in extra_keywords:
            kw_clean = kw.strip()
            if kw_clean and kw_clean.lower() not in " ".join(parts).lower():
                parts.append(kw_clean)
    return " ".join(parts).strip()


def score_metadata_candidate(
    tokens: ParsedMediaTokens,
    candidate: OnlineMetadataCandidate,
    user_keywords: Optional[List[str]] = None,
) -> float:
    """
    Computes a deterministic similarity score in [0.0, 1.0] between local parsed tokens
    (+ user_keywords) and an online metadata candidate (works for Western Adult, Japanese JAV, and Mainstream).
    """
    score = 0.0

    if tokens.media_category == candidate.media_category:
        score += 0.10

    # Japanese JAV Exact Code Match Bonus (highest reliability)
    if tokens.jav_code and candidate.jav_code:
        if tokens.jav_code.upper().strip() == candidate.jav_code.upper().strip():
            score += 0.55

    # 1. Studio match (up to 0.25)
    if tokens.studio and candidate.studio:
        s1 = re.sub(r"\W+", "", tokens.studio.lower())
        s2 = re.sub(r"\W+", "", candidate.studio.lower())
        if s1 and s2 and (s1 == s2 or s1 in s2 or s2 in s1):
            score += 0.25

    # 2. Release date / year match (up to 0.20)
    if tokens.release_date and candidate.release_date:
        if tokens.release_date == candidate.release_date:
            score += 0.20
        elif tokens.release_date[:4] == candidate.release_date[:4]:
            score += 0.15

    # 3. Performer / Actress / Cast overlap (up to 0.20)
    if tokens.performers and candidate.performers:
        local_perfs = {p.lower().strip() for p in tokens.performers}
        cand_perfs = {p.lower().strip() for p in candidate.performers}
        overlap = local_perfs.intersection(cand_perfs)
        if overlap:
            score += min(0.20, 0.12 * len(overlap) + 0.08)

    # 4. Title token overlap
    if tokens.title and candidate.title:
        t_local = {w.lower() for w in re.findall(r"[A-Za-z0-9\u4e00-\u9fff\u3040-\u30ff]+", tokens.title) if len(w) > 1}
        t_cand = {w.lower() for w in re.findall(r"[A-Za-z0-9\u4e00-\u9fff\u3040-\u30ff]+", candidate.title) if len(w) > 1}
        if t_local and t_cand:
            jaccard = len(t_local & t_cand) / float(len(t_local | t_cand))
            weight = 0.35 if tokens.media_category in (MediaCategory.MAINSTREAM_MOVIE, MediaCategory.MAINSTREAM_TV) else 0.25
            score += weight * jaccard

    # 5. User keyword bonus (up to 0.15)
    if user_keywords:
        cand_blob = " ".join(
            [candidate.studio, candidate.title, candidate.release_date, candidate.director, candidate.jav_code]
            + candidate.performers
            + candidate.tags
        ).lower()
        hits = sum(1 for kw in user_keywords if kw.strip().lower() in cand_blob)
        if hits > 0:
            score += min(0.15, 0.05 * hits)

    return round(min(1.0, score), 3)


def compute_smart_frame_timestamp(duration_sec: float) -> List[float]:
    """
    Calculates 3 candidate video timestamps (in seconds) for FFmpeg cover frame extraction
    when no online or local cover image is available.
    """
    if duration_sec <= 0.0:
        return [30.0, 90.0, 180.0]
    if duration_sec < 20.0:
        return [round(duration_sec * 0.25, 2), round(duration_sec * 0.5, 2), round(duration_sec * 0.75, 2)]

    t1 = max(5.0, min(420.0, duration_sec * 0.18))
    t2 = max(10.0, min(900.0, duration_sec * 0.32))
    t3 = max(15.0, min(1500.0, duration_sec * 0.50))
    return [round(t1, 2), round(t2, 2), round(t3, 2)]


def enrich_media_item(
    item: MediaItem,
    tokens: ParsedMediaTokens,
    provider_results: List[OnlineMetadataCandidate],
    local_sidecar_cover: Optional[str] = None,
    extracted_frame_cover: Optional[str] = None,
    min_match_score: float = 0.35,
) -> MediaItem:
    """
    Merges local parsed tokens, online metadata candidates, and cover art fallback rules.
    If an unknown studio (`tokens.is_unknown_studio`) is resolved by an online candidate,
    automatically registers the newly learned studio in `CUSTOM_STUDIO_REGISTRY`!
    """
    item.media_category = tokens.media_category
    if tokens.jav_code and not item.jav_code:
        item.jav_code = tokens.jav_code

    best_cand: Optional[OnlineMetadataCandidate] = None
    best_score = -1.0

    for cand in provider_results:
        sc = score_metadata_candidate(tokens, cand, item.user_keywords)
        cand.match_score = sc
        if sc > best_score:
            best_score = sc
            best_cand = cand

    if best_cand is not None and best_score >= min_match_score:
        item.media_category = best_cand.media_category
        if best_cand.jav_code:
            item.jav_code = best_cand.jav_code
        item.title = best_cand.title or item.title or tokens.title or item.file_name
        if best_cand.studio:
            item.studio = best_cand.studio
            item.is_unknown_studio = False
            if tokens.raw_studio_token:
                register_custom_studio(tokens.raw_studio_token, best_cand.studio, item.media_category)
        else:
            item.studio = item.studio or tokens.studio or ""
            item.is_unknown_studio = tokens.is_unknown_studio
        if best_cand.director:
            item.director = best_cand.director
        if best_cand.performers:
            item.performers = list(best_cand.performers)
        elif not item.performers and tokens.performers:
            item.performers = list(tokens.performers)
        item.release_date = best_cand.release_date or item.release_date or tokens.release_date or ""
        merged_tags = list(dict.fromkeys(item.tags + tokens.tags + best_cand.tags))
        item.tags = merged_tags
        if best_cand.duration_sec > 0 and item.duration_sec <= 0:
            item.duration_sec = best_cand.duration_sec
        if best_cand.synopsis:
            item.synopsis = best_cand.synopsis
        if best_cand.imdb_id:
            item.imdb_id = best_cand.imdb_id
        if best_cand.tmdb_id:
            item.tmdb_id = best_cand.tmdb_id
        if best_cand.cover_url:
            item.cover_path = best_cand.cover_url
            item.cover_source = CoverSourceType.ONLINE_POSTER
    else:
        if not item.title:
            item.title = tokens.title or item.file_name
        if not item.studio and tokens.studio:
            item.studio = tokens.studio
            item.is_unknown_studio = tokens.is_unknown_studio
        if not item.performers and tokens.performers:
            item.performers = list(tokens.performers)
        if not item.release_date and tokens.release_date:
            item.release_date = tokens.release_date
        for t in tokens.tags:
            if t not in item.tags:
                item.tags.append(t)

    if not item.cover_path or item.cover_source == CoverSourceType.PLACEHOLDER:
        if local_sidecar_cover:
            item.cover_path = local_sidecar_cover
            item.cover_source = CoverSourceType.LOCAL_SIDECAR
        elif extracted_frame_cover:
            item.cover_path = extracted_frame_cover
            item.cover_source = CoverSourceType.VIDEO_FRAME
        else:
            item.cover_source = CoverSourceType.PLACEHOLDER

    item.refresh_completeness()
    return item


def filter_and_search_library(
    items: List[MediaItem],
    criteria: LibraryFilterCriteria,
) -> List[MediaItem]:
    """
    Multi-Dimensional Category & Attribute Search Engine:
    Simultaneously filters by:
    - Category (`western_adult`, `japanese_jav`, `mainstream`)
    - Storage Source (`local_disk`, `samba_smb`, `cloud_mount`)
    - Studio / Maker (`Vixen`, `Blacked`, `S1 NO.1 STYLE`, `IdeaPocket`, `Warner Bros. Pictures`, etc.)
    - Performer / Actress / Cast (`Eve Sweet`, `河北彩花`, `桃乃木香奈`, `Timothée Chalamet`, etc.)
    - Genre / Technical Tag (`4K Ultra HD`, `中文字幕`, `无码 (Uncensored)`, `Glamour`, `IMAX`, etc.)
    - Half-Star Rating Range (`min_rating`, `max_rating`, or `exact_rating` in 0.5 star steps)
    - Unknown Studio / Incomplete status (`only_unknown_studio`, `only_incomplete`)
    - Free-text search (`title_or_keyword` across title, JAV code, studio, actress, director, tags, and user_keywords)
    """
    matched: List[MediaItem] = []
    q = criteria.title_or_keyword.strip().lower()

    for item in items:
        # 1. Category filter
        if criteria.media_category and criteria.media_category != "all":
            if criteria.media_category == "mainstream":
                if item.media_category not in (MediaCategory.MAINSTREAM_MOVIE, MediaCategory.MAINSTREAM_TV):
                    continue
            elif item.media_category.value != criteria.media_category:
                continue

        # 2. Storage source filter
        if criteria.source_type and criteria.source_type != "all":
            if item.source_type.value != criteria.source_type:
                continue

        # 3. Studio / Maker filter
        if criteria.studio and criteria.studio != "all":
            if item.studio.lower() != criteria.studio.lower():
                continue

        # 4. Performer / Actress filter
        if criteria.performer and criteria.performer != "all":
            if not any(p.lower() == criteria.performer.lower() for p in item.performers):
                continue

        # 5. Genre / Tag filter
        if criteria.tag and criteria.tag != "all":
            if not any(t.lower() == criteria.tag.lower() for t in item.tags):
                continue

        # 6. Half-star rating filter
        if criteria.exact_rating is not None:
            if abs(item.rating - criteria.exact_rating) > 1e-6:
                continue
        else:
            if item.rating < criteria.min_rating - 1e-6 or item.rating > criteria.max_rating + 1e-6:
                continue

        # 7. Incomplete / Unknown Studio filter
        if criteria.only_incomplete and not item.is_incomplete:
            continue
        if criteria.only_unknown_studio and not item.is_unknown_studio:
            continue

        # 8. Substring search across Title, JAV Code, Studio, Performer, Director, Tags, and User Keywords
        if q:
            haystack = " ".join(
                [
                    item.title,
                    item.jav_code,
                    item.studio,
                    item.director,
                    item.release_date,
                    item.file_name,
                ]
                + item.performers
                + item.tags
                + item.user_keywords
            ).lower()
            if q not in haystack:
                continue

        matched.append(item)

    # Sort results
    if criteria.sort_by == "rating_desc":
        matched.sort(key=lambda x: (x.rating, x.release_date), reverse=True)
    elif criteria.sort_by == "title_asc":
        matched.sort(key=lambda x: (x.title or x.file_name).lower())
    elif criteria.sort_by == "studio_asc":
        matched.sort(key=lambda x: (x.studio.lower(), x.release_date))
    else:
        matched.sort(key=lambda x: (x.release_date, x.rating), reverse=True)

    return matched


def generate_kodi_nfo_xml(item: MediaItem) -> str:
    """
    Generates a standard Kodi / Jellyfin / Emby / Plex compatible `.nfo` XML sidecar string
    supporting Western Adult (`cinevault_hash`), Japanese JAV (`num` / `jav_code`), and Mainstream (`imdb` / `tmdb`).
    """
    esc = html.escape
    user_rating_10 = round(item.rating * 2.0, 1)
    display_title = f"[{item.jav_code}] {item.title}" if item.jav_code and item.jav_code not in item.title else (item.title or item.file_name)
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        "<movie>",
        f"  <title>{esc(display_title)}</title>",
        f"  <originaltitle>{esc(item.title or item.file_name)}</originaltitle>",
        f"  <num>{esc(item.jav_code)}</num>",
        f"  <studio>{esc(item.studio)}</studio>",
        f"  <director>{esc(item.director)}</director>",
        f"  <premiered>{esc(item.release_date)}</premiered>",
        f"  <userrating>{user_rating_10}</userrating>",
        f"  <customrating>{item.rating:.1f}/5.0</customrating>",
        f"  <plot>{esc(item.synopsis)}</plot>",
        f'  <uniqueid type="cinevault_hash" default="true">{esc(item.fast_hash)}</uniqueid>',
    ]
    if item.jav_code:
        lines.append(f'  <uniqueid type="jav">{esc(item.jav_code)}</uniqueid>')
    if item.imdb_id:
        lines.append(f'  <uniqueid type="imdb">{esc(item.imdb_id)}</uniqueid>')
    if item.tmdb_id:
        lines.append(f'  <uniqueid type="tmdb">{esc(item.tmdb_id)}</uniqueid>')
    for perf in item.performers:
        lines.extend([
            "  <actor>",
            f"    <name>{esc(perf)}</name>",
            "  </actor>",
        ])
    for tag in item.tags:
        lines.append(f"  <tag>{esc(tag)}</tag>")
    for kw in item.user_keywords:
        lines.append(f"  <keyword>{esc(kw)}</keyword>")
    if item.cover_path:
        lines.append(f'  <thumb aspect="poster">{esc(item.cover_path)}</thumb>')
    lines.append("</movie>")
    return "\n".join(lines) + "\n"
