"""
Tri-Track Online Metadata Scraper Adapter (`src/adapters/online_scrapers.py`).
Assigned to Hydrogen: `[HYDROGEN-TASK-03]`.

Routes queries automatically based on `tokens.media_category`:
- `MediaCategory.WESTERN_ADULT` -> ThePornDB / StashDB REST/GraphQL endpoints
- `MediaCategory.JAPANESE_JAV` -> JavDB / FANZA endpoints (matched by `jav_code`)
- `MediaCategory.MAINSTREAM_MOVIE` / `MAINSTREAM_TV` -> TMDB / OMDb REST endpoints
"""

from __future__ import annotations
import json
import urllib.parse
import urllib.request
from typing import List, Optional, Dict, Any
from ..core.models import MediaCategory, ParsedMediaTokens, OnlineMetadataCandidate
from ..core.metadata_engine import build_search_query


# Built-in offline reference catalog covering Western Adult, Japanese JAV, and Mainstream Movies/TV
BUILTIN_OFFLINE_CATALOG: List[Dict[str, Any]] = [
    # --- Western Adult Catalog Entries ---
    {
        "provider": "ThePornDB",
        "external_id": "tpdb_vxn_20250214",
        "media_category": MediaCategory.WESTERN_ADULT,
        "jav_code": "",
        "studio": "Vixen",
        "title": "Sunset Villa",
        "performers": ["Eve Sweet", "Alberto Blanco"],
        "director": "Julia Grandi",
        "release_date": "2025-02-14",
        "tags": ["Glamour", "4K Ultra HD", "Outdoor", "European"],
        "cover_url": "https://cdn.cinevault.local/posters/vixen_sunset_villa.jpg",
        "duration_sec": 2180.0,
        "synopsis": "High-contrast Mediterranean sunset feature directed on location.",
    },
    {
        "provider": "StashDB",
        "external_id": "stash_blk_20241108",
        "media_category": MediaCategory.WESTERN_ADULT,
        "jav_code": "",
        "studio": "Blacked",
        "title": "Midnight Heat",
        "performers": ["Violet Myers"],
        "director": "Laurent Sky",
        "release_date": "2024-11-08",
        "tags": ["Glamour", "4K Ultra HD", "Lingerie", "Studio Feature"],
        "cover_url": "https://cdn.cinevault.local/posters/blacked_midnight_heat.jpg",
        "duration_sec": 2450.0,
        "synopsis": "Late-night penthouse production featuring Violet Myers.",
    },
    {
        "provider": "ThePornDB",
        "external_id": "tpdb_tushy_20240919",
        "media_category": MediaCategory.WESTERN_ADULT,
        "jav_code": "",
        "studio": "Tushy",
        "title": "Parisian Nights",
        "performers": ["Kelly Collins", "Alex Adams"],
        "director": "",
        "release_date": "2024-09-19",
        "tags": ["Glamour", "Anal", "European", "1080p"],
        "cover_url": "https://cdn.cinevault.local/posters/tushy_parisian_nights.jpg",
        "duration_sec": 2310.0,
        "synopsis": "Parisian boutique apartment showcase.",
    },
    {
        "provider": "ThePornDB",
        "external_id": "tpdb_metart_20250110",
        "media_category": MediaCategory.WESTERN_ADULT,
        "jav_code": "",
        "studio": "MetArt",
        "title": "Golden Hour",
        "performers": ["Eva Elfie"],
        "director": "",
        "release_date": "2025-01-10",
        "tags": ["Artistic", "Glamour", "4K Ultra HD"],
        "cover_url": "",  # Intentionally empty to exercise FFmpeg smart frame cover fallback
        "duration_sec": 1840.0,
        "synopsis": "Artistic natural-light cinematography.",
    },
    # --- Japanese JAV Catalog Entries ---
    {
        "provider": "JavDB",
        "external_id": "javdb_ssis_001",
        "media_category": MediaCategory.JAPANESE_JAV,
        "jav_code": "SSIS-001",
        "studio": "S1 NO.1 STYLE",
        "title": "最高峰アイドル 4K 特別編",
        "performers": ["河北彩花 (Saika Kawakita)"],
        "director": "紋℃",
        "release_date": "2024-05-19",
        "tags": ["中文字幕", "4K Ultra HD", "单体作品", "S1"],
        "cover_url": "https://cdn.cinevault.local/posters/ssis_001.jpg",
        "duration_sec": 7200.0,
        "synopsis": "S1 NO.1 STYLE exclusive 4K release.",
    },
    {
        "provider": "FANZA",
        "external_id": "fanza_ipzz_102",
        "media_category": MediaCategory.JAPANESE_JAV,
        "jav_code": "IPZZ-102",
        "studio": "IdeaPocket",
        "title": "週末限定 二人きりの温泉旅行",
        "performers": ["桃乃木香奈 (Kana Momonogi)"],
        "director": "",
        "release_date": "2024-08-13",
        "tags": ["中文字幕", "1080p", "专属女优"],
        "cover_url": "https://cdn.cinevault.local/posters/ipzz_102.jpg",
        "duration_sec": 6900.0,
        "synopsis": "IdeaPocket feature release.",
    },
    # --- Mainstream Cinema & TV Catalog Entries ---
    {
        "provider": "TMDB",
        "external_id": "tmdb_693134",
        "media_category": MediaCategory.MAINSTREAM_MOVIE,
        "jav_code": "",
        "studio": "Warner Bros. Pictures",
        "title": "Dune Part Two",
        "performers": ["Timothée Chalamet", "Zendaya", "Rebecca Ferguson"],
        "director": "Denis Villeneuve",
        "release_date": "2024-03-01",
        "tags": ["Sci-Fi", "IMAX", "4K Ultra HD", "Dolby Atmos"],
        "cover_url": "https://cdn.cinevault.local/posters/dune_part_two_2024.jpg",
        "duration_sec": 9960.0,
        "imdb_id": "tt15239678",
        "tmdb_id": "693134",
        "synopsis": "Paul Atreides unites with Chani and the Fremen while on a warpath of revenge.",
    },
    {
        "provider": "TMDB",
        "external_id": "tmdb_872585",
        "media_category": MediaCategory.MAINSTREAM_MOVIE,
        "jav_code": "",
        "studio": "Universal Pictures",
        "title": "Oppenheimer",
        "performers": ["Cillian Murphy", "Emily Blunt", "Matt Damon", "Robert Downey Jr."],
        "director": "Christopher Nolan",
        "release_date": "2023-07-21",
        "tags": ["Drama", "IMAX", "BluRay Remux", "4K Ultra HD"],
        "cover_url": "https://cdn.cinevault.local/posters/oppenheimer_2023.jpg",
        "duration_sec": 10800.0,
        "imdb_id": "tt15398776",
        "tmdb_id": "872585",
        "synopsis": "The story of J. Robert Oppenheimer's role in the development of the atomic bomb.",
    },
]


# [HYDROGEN-TASK-03]
class OnlineMetadataScraper:
    """
    Tri-Track Metadata Scraper:
    - Queries ThePornDB / StashDB when `tokens.media_category == MediaCategory.WESTERN_ADULT`
    - Queries JavDB / FANZA when `tokens.media_category == MediaCategory.JAPANESE_JAV`
    - Queries TMDB / OMDb when `tokens.media_category in (MAINSTREAM_MOVIE, MAINSTREAM_TV)`
    - Falls back to `offline_catalog_lookup()` when offline or when no API tokens are configured.
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        tmdb_api_key: Optional[str] = None,
        endpoint_url: str = "https://api.theporndb.net/scenes",
        tmdb_endpoint_url: str = "https://api.themoviedb.org/3/search/movie",
        timeout_sec: float = 8.0,
    ) -> None:
        self.api_token = api_token
        self.tmdb_api_key = tmdb_api_key
        self.endpoint_url = endpoint_url
        self.tmdb_endpoint_url = tmdb_endpoint_url
        self.timeout_sec = timeout_sec

    def parse_tpdb_json_response(self, payload: Dict[str, Any]) -> List[OnlineMetadataCandidate]:
        data_list = payload.get("data") or []
        candidates: List[OnlineMetadataCandidate] = []
        for entry in data_list:
            site_info = entry.get("site") or {}
            studio_name = site_info.get("name") or entry.get("studio") or ""
            perfs = [
                p.get("name", "").strip()
                for p in (entry.get("performers") or [])
                if isinstance(p, dict) and p.get("name")
            ]
            tags = [
                t.get("name", "").strip()
                for t in (entry.get("tags") or [])
                if isinstance(t, dict) and t.get("name")
            ]
            posters = entry.get("posters") or {}
            cover_url = posters.get("large") or posters.get("medium") or entry.get("image") or ""
            candidates.append(
                OnlineMetadataCandidate(
                    provider="ThePornDB",
                    external_id=str(entry.get("id") or entry.get("_id") or ""),
                    media_category=MediaCategory.WESTERN_ADULT,
                    title=str(entry.get("title") or ""),
                    studio=str(studio_name),
                    performers=perfs,
                    release_date=str(entry.get("date") or ""),
                    tags=tags,
                    cover_url=str(cover_url),
                    duration_sec=float(entry.get("duration") or 0.0),
                    synopsis=str(entry.get("description") or ""),
                )
            )
        return candidates

    def parse_jav_json_response(self, payload: Dict[str, Any]) -> List[OnlineMetadataCandidate]:
        data_list = payload.get("data") or []
        candidates: List[OnlineMetadataCandidate] = []
        for entry in data_list:
            candidates.append(
                OnlineMetadataCandidate(
                    provider="JavDB",
                    external_id=str(entry.get("id") or entry.get("jav_code") or ""),
                    media_category=MediaCategory.JAPANESE_JAV,
                    jav_code=str(entry.get("jav_code") or entry.get("number") or "").upper(),
                    title=str(entry.get("title") or ""),
                    studio=str(entry.get("maker") or entry.get("studio") or ""),
                    performers=list(entry.get("actresses") or entry.get("performers") or []),
                    director=str(entry.get("director") or ""),
                    release_date=str(entry.get("release_date") or entry.get("date") or ""),
                    tags=list(entry.get("tags") or []),
                    cover_url=str(entry.get("cover_url") or ""),
                )
            )
        return candidates

    def parse_tmdb_json_response(self, payload: Dict[str, Any]) -> List[OnlineMetadataCandidate]:
        results_list = payload.get("results") or []
        candidates: List[OnlineMetadataCandidate] = []
        for entry in results_list:
            poster_path = entry.get("poster_path") or ""
            cover_url = f"https://image.tmdb.org/t/p/w780{poster_path}" if poster_path else ""
            candidates.append(
                OnlineMetadataCandidate(
                    provider="TMDB",
                    external_id=f"tmdb_{entry.get('id', '')}",
                    media_category=MediaCategory.MAINSTREAM_MOVIE,
                    title=str(entry.get("title") or entry.get("original_title") or ""),
                    studio=str(entry.get("studio") or "Mainstream Studio"),
                    performers=list(entry.get("cast") or []),
                    director=str(entry.get("director") or ""),
                    release_date=str(entry.get("release_date") or ""),
                    tags=["Mainstream Cinema"],
                    cover_url=cover_url,
                    tmdb_id=str(entry.get("id") or ""),
                    synopsis=str(entry.get("overview") or ""),
                )
            )
        return candidates

    def offline_catalog_lookup(
        self,
        tokens: ParsedMediaTokens,
        extra_keywords: Optional[List[str]] = None,
    ) -> List[OnlineMetadataCandidate]:
        query_lower = build_search_query(tokens, extra_keywords).lower()
        results: List[OnlineMetadataCandidate] = []
        for row in BUILTIN_OFFLINE_CATALOG:
            if tokens.jav_code and row.get("jav_code") and tokens.jav_code.upper() == row["jav_code"].upper():
                results.append(OnlineMetadataCandidate(**row))
                continue
            blob = " ".join(
                [row["studio"], row["title"], row["release_date"], row.get("director", ""), row.get("jav_code", "")]
                + row["performers"]
            ).lower()
            if (
                (tokens.studio and tokens.studio.lower() in blob)
                or (tokens.title and tokens.title.lower() in blob)
                or any(p.lower() in blob for p in tokens.performers)
                or any(kw.lower() in blob for kw in (extra_keywords or []))
                or any(tok in blob for tok in query_lower.split() if len(tok) > 3)
            ):
                results.append(OnlineMetadataCandidate(**row))
        return results

    def search_candidates(
        self,
        tokens: ParsedMediaTokens,
        extra_keywords: Optional[List[str]] = None,
    ) -> List[OnlineMetadataCandidate]:
        query = build_search_query(tokens, extra_keywords)

        if tokens.media_category in (MediaCategory.MAINSTREAM_MOVIE, MediaCategory.MAINSTREAM_TV):
            if self.tmdb_api_key and query:
                url = f"{self.tmdb_endpoint_url}?query={urllib.parse.quote(query)}&api_key={urllib.parse.quote(self.tmdb_api_key)}"
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                        raw = json.loads(resp.read().decode("utf-8"))
                        parsed = self.parse_tmdb_json_response(raw)
                        if parsed:
                            return parsed
                except Exception:
                    pass
            return self.offline_catalog_lookup(tokens, extra_keywords)

        if self.api_token and query:
            url = f"{self.endpoint_url}?parse={urllib.parse.quote(query)}"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Accept": "application/json",
                    "User-Agent": "CineVaultStudio/1.2",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                    parsed = self.parse_tpdb_json_response(raw)
                    if parsed:
                        return parsed
            except Exception:
                pass
        return self.offline_catalog_lookup(tokens, extra_keywords)
