"""
Dual-Mode AI Metadata & Unrecorded New Studio Completion Engine (`src/core/ai_bridge.py`).
Implemented and verified by Argon. DO NOT MODIFY in Hydrogen tasks.

Supports all three media categories (`western_adult`, `japanese_jav`, `mainstream_movie`/`mainstream_tv`)
AND automatically learns/registers new unrecorded studios (`is_unknown_studio`) into `CUSTOM_STUDIO_REGISTRY`
when AI completes the metadata!
"""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from .models import MediaItem, MediaCategory
from .parser import (
    WESTERN_STUDIO_ALIASES,
    JAV_PREFIX_TO_STUDIO,
    MAINSTREAM_STUDIO_ALIASES,
    CUSTOM_STUDIO_REGISTRY,
    GENRE_KEYWORD_MAP,
    register_custom_studio,
)


JSON_FENCE_REGEX = re.compile(r"```json\s*(\[.*?\]|\{.*?\})\s*```", re.DOTALL)


def export_root_markdown_keyword_db(
    items: List[MediaItem],
    output_md_path: Optional[str | Path] = None,
) -> str:
    """
    Generates the root `AI_KEYWORD_DB.md` content containing:
    - Section 1: Instructions for CLI AI Models (Western Adult + Japanese JAV + Mainstream Movies/TV + Unknown Studio Completion)
    - Section 2: Canonical Western Adult Studios, Japanese JAV Prefix->Maker Map, Mainstream Studios & Genre Glossary
    - Section 3: Machine-Readable JSON Block of Incomplete or Unknown-Studio Media Items
    """
    incomplete = [i for i in items if i.is_incomplete or i.is_unknown_studio or i.user_keywords]
    if not incomplete:
        incomplete = list(items)

    records_payload = []
    for item in incomplete:
        records_payload.append({
            "item_id": item.item_id,
            "fast_hash": item.fast_hash,
            "media_category": item.media_category.value,
            "jav_code": item.jav_code,
            "file_name": item.file_name,
            "parent_dirs": item.parent_dirs,
            "user_keywords": item.user_keywords,
            "studio": item.studio,
            "is_unknown_studio": item.is_unknown_studio,
            "new_studio_alias_to_register": item.jav_code.split("-")[0] if (item.jav_code and item.is_unknown_studio) else (item.studio if item.is_unknown_studio else ""),
            "director": item.director,
            "title": item.title,
            "performers": item.performers,
            "release_date": item.release_date,
            "tags": item.tags,
        })

    canonical_adult_studios = sorted(set(list(WESTERN_STUDIO_ALIASES.values()) + list(CUSTOM_STUDIO_REGISTRY["western_adult"].values())))
    canonical_jav_makers = sorted(set(list(JAV_PREFIX_TO_STUDIO.values()) + list(CUSTOM_STUDIO_REGISTRY["japanese_jav"].values())))
    canonical_mainstream_studios = sorted(set(list(MAINSTREAM_STUDIO_ALIASES.values()) + list(CUSTOM_STUDIO_REGISTRY["mainstream"].values())))
    canonical_genres = sorted(set(GENRE_KEYWORD_MAP.values()))

    md_lines = [
        "# CineVault Studio — AI CLI Keyword & New Studio Database (`AI_KEYWORD_DB.md`)",
        "",
        "> **CLI Model Instructions**:",
        "> 1. Read the **Tri-Library Glossary** in Section 1 (supports **Western Adult**, **Japanese JAV**, and **Mainstream Movies/TV**).",
        "> 2. Inspect each record in Section 2's `json` block (`media_category`, `jav_code`, `file_name`, `parent_dirs`, `is_unknown_studio`, and `user_keywords`).",
        "> 3. **New/Unrecorded Studio Completion**: When `is_unknown_studio` is `true`, identify the official canonical studio/maker name from the filename, JAV prefix (`new_studio_alias_to_register`), or `user_keywords`, set `studio` to the full official name, and set `is_unknown_studio` to `false`. CineVault Studio will automatically register the new studio into its dictionary!",
        "> 4. Fill in missing `title`, `performers` (actresses/actors), `release_date` (`YYYY-MM-DD` or `YYYY`), and `tags`.",
        "> 5. **DO NOT** alter `item_id` or `fast_hash`. Save this file when done.",
        "",
        "## 1. Keyword Database & Canonical Glossary",
        "",
        f"- **Western Adult Studios ({len(canonical_adult_studios)})**: {', '.join(canonical_adult_studios)}",
        f"- **Japanese JAV Makers ({len(canonical_jav_makers)})**: {', '.join(canonical_jav_makers)}",
        f"- **Mainstream Film/TV Studios ({len(canonical_mainstream_studios)})**: {', '.join(canonical_mainstream_studios)}",
        f"- **Standard Genre & Technical Tags ({len(canonical_genres)})**: {', '.join(canonical_genres)}",
        "",
        "## 2. Incomplete & Unknown-Studio Media Records (Edit JSON In-Place)",
        "",
        "```json",
        json.dumps(records_payload, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    content = "\n".join(md_lines)
    if output_md_path is not None:
        Path(output_md_path).write_text(content, encoding="utf-8")
    return content


def _is_existing_file_path(candidate: str | Path) -> bool:
    if isinstance(candidate, Path):
        return candidate.is_file()
    s = str(candidate).strip()
    if "\n" in s or len(s) > 240 or s.startswith("{") or s.startswith("["):
        return False
    try:
        return Path(s).is_file()
    except OSError:
        return False


def import_root_markdown_completions(
    md_content_or_path: str | Path,
    items_by_id: Dict[str, MediaItem],
) -> int:
    """
    Parses a CLI-model-updated `AI_KEYWORD_DB.md` (or raw JSON response pasted from an LLM dialog),
    updates matching `MediaItem` instances in `items_by_id`, AND automatically registers any newly
    completed studios into `CUSTOM_STUDIO_REGISTRY` so future scans recognize that studio/label!
    """
    if _is_existing_file_path(md_content_or_path):
        raw_text = Path(md_content_or_path).read_text(encoding="utf-8")
    else:
        raw_text = str(md_content_or_path)

    match = JSON_FENCE_REGEX.search(raw_text)
    json_str = match.group(1) if match else raw_text.strip()
    parsed = json.loads(json_str)
    if isinstance(parsed, dict) and "records" in parsed:
        records = parsed["records"]
    elif isinstance(parsed, list):
        records = parsed
    else:
        records = [parsed]

    updated_count = 0
    for rec in records:
        item_id = rec.get("item_id")
        if not item_id or item_id not in items_by_id:
            continue
        target = items_by_id[item_id]
        was_unknown_studio = target.is_unknown_studio
        old_raw_studio = rec.get("new_studio_alias_to_register") or target.studio

        if rec.get("media_category"):
            try:
                target.media_category = MediaCategory(rec["media_category"])
            except ValueError:
                pass
        if rec.get("jav_code"):
            target.jav_code = str(rec["jav_code"]).strip().upper()
        if rec.get("studio"):
            new_studio = str(rec["studio"]).strip()
            target.studio = new_studio
            target.is_unknown_studio = False
            if was_unknown_studio or rec.get("new_studio_alias_to_register"):
                alias_key = str(old_raw_studio).strip()
                if target.jav_code and "-" in target.jav_code:
                    alias_key = target.jav_code.split("-")[0]
                if alias_key:
                    register_custom_studio(alias_key, new_studio, target.media_category)
        if rec.get("director"):
            target.director = str(rec["director"]).strip()
        if rec.get("title"):
            target.title = str(rec["title"]).strip()
        if isinstance(rec.get("performers"), list) and rec["performers"]:
            target.performers = [str(p).strip() for p in rec["performers"] if str(p).strip()]
        if rec.get("release_date"):
            target.release_date = str(rec["release_date"]).strip()
        if isinstance(rec.get("tags"), list) and rec["tags"]:
            merged = list(dict.fromkeys(target.tags + [str(t).strip() for t in rec["tags"] if str(t).strip()]))
            target.tags = merged
        target.refresh_completeness()
        updated_count += 1

    return updated_count


def build_interactive_ai_prompt(
    incomplete_items: List[MediaItem],
    language: str = "zh",
) -> str:
    """
    Builds a self-contained prompt + JSON payload that users can copy directly from the UI
    and paste into any chat LLM to complete missing metadata and unrecorded new studios/makers.
    """
    payload = [
        {
            "item_id": i.item_id,
            "media_category": i.media_category.value,
            "jav_code": i.jav_code,
            "file_name": i.file_name,
            "parent_dirs": i.parent_dirs,
            "user_keywords": i.user_keywords,
            "studio": i.studio,
            "is_unknown_studio": i.is_unknown_studio,
            "new_studio_alias_to_register": i.jav_code.split("-")[0] if (i.jav_code and i.is_unknown_studio) else (i.studio if i.is_unknown_studio else ""),
            "director": i.director,
            "title": i.title,
            "performers": i.performers,
            "release_date": i.release_date,
            "tags": i.tags,
        }
        for i in incomplete_items
    ]
    json_block = json.dumps(payload, indent=2, ensure_ascii=False)

    if language.lower().startswith("en"):
        return (
            "You are a tri-library media metadata & studio specialist for CineVault Studio (Western Adult, Japanese JAV, and Mainstream Cinema).\n"
            "Below is a JSON array of video files with incomplete metadata or unrecorded studios (`is_unknown_studio: true`). Using each item's "
            "`media_category`, `jav_code`, `file_name`, `parent_dirs`, and `user_keywords`, infer and fill in:\n"
            "- `media_category` (`western_adult`, `japanese_jav`, `mainstream_movie`, or `mainstream_tv`)\n"
            "- `jav_code` (standardized JAV ID like `SSIS-001` or `FC2-PPV-3109221` for Japanese adult videos)\n"
            "- `studio` (official studio/maker name; if `is_unknown_studio` was true, provide the full official studio name so CineVault can permanently register it!)\n"
            "- `is_unknown_studio` (set to `false` once you fill in `studio`)\n"
            "- `title`, `performers` (actresses/actors/cast), `release_date` (`YYYY-MM-DD` or `YYYY`), and `tags`\n\n"
            "Keep `item_id` unchanged and output ONLY a valid ```json ... ``` code block:\n\n"
            f"```json\n{json_block}\n```"
        )

    return (
        "你是 CineVault Studio 三轨影视资料库（欧美成人 + 日本AV番号 + 常规院线电影）元数据与新厂牌补全助手。\n"
        "请根据下方 JSON 列表中每个视频文件的 `media_category`、`jav_code`、`file_name`、`parent_dirs` 以及用户补充的 "
        "`user_keywords`，自动推断并补全以下字段：\n"
        "- `media_category`（`western_adult` 欧美成人、`japanese_jav` 日本AV番号、`mainstream_movie` 常规院线电影）\n"
        "- `jav_code`（日本AV标准番号，如 `SSIS-001`, `IPX-888`, `STARS-707`, `FC2-PPV-3109221`）\n"
        "- `studio`（正式厂牌/片商名称；若 `is_unknown_studio: true` 表示系统遇到未收录新厂牌，请根据文件前缀或提示词补全正式厂牌名并将 `is_unknown_studio` 设为 `false`，系统会自动将该新厂牌永久收录进词库！）\n"
        "- `title`（影片正式标题）、`performers`（女优/主演全名数组）、`release_date`（`YYYY-MM-DD` 或 `YYYY`）、`tags`（3~6个分类/中字/无码/画质标签）\n\n"
        "请严禁修改 `item_id`，直接输出补全后的 ```json ... ``` 代码块：\n\n"
        f"```json\n{json_block}\n```"
    )


class MCPServerEngine:
    """
    Standard Model Context Protocol (MCP) JSON-RPC 2.0 Engine for CineVault Studio.
    """

    def __init__(self, items_by_id: Dict[str, MediaItem]) -> None:
        self.items_by_id = items_by_id

    def get_mcp_config_snippet(self, project_root: str = "/path/to/cinevault-studio") -> Dict[str, Any]:
        return {
            "mcpServers": {
                "cinevault-studio": {
                    "command": "python3",
                    "args": ["-m", "src.adapters.mcp_stdio_server"],
                    "cwd": project_root,
                }
            }
        }

    def handle_jsonrpc(self, request: Dict[str, Any]) -> Dict[str, Any]:
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "cinevault-studio-mcp", "version": "1.2.0"},
                    "capabilities": {"tools": {}},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "list_incomplete_media",
                            "description": "List media items (Western Adult, Japanese JAV, Mainstream) with missing metadata or unrecorded new studios (`is_unknown_studio`).",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                        {
                            "name": "get_keyword_glossary",
                            "description": "Retrieve canonical Western adult studios, Japanese JAV maker prefixes, mainstream studios, and custom AI-registered studios.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                        {
                            "name": "apply_enriched_metadata",
                            "description": "Batch update media items with AI-completed metadata and automatically register newly identified studios/labels.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "records": {
                                        "type": "array",
                                        "items": {"type": "object"},
                                    }
                                },
                                "required": ["records"],
                            },
                        },
                        {
                            "name": "register_new_studio",
                            "description": "Register a newly discovered Western Adult studio alias, Japanese JAV code prefix, or Mainstream studio into CineVault's dictionary.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "alias_or_prefix": {"type": "string"},
                                    "canonical_name": {"type": "string"},
                                    "media_category": {"type": "string"},
                                },
                                "required": ["alias_or_prefix", "canonical_name"],
                            },
                        },
                    ]
                },
            }

        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments") or {}

            if tool_name == "list_incomplete_media":
                incomplete = [
                    i.to_dict()
                    for i in self.items_by_id.values()
                    if i.is_incomplete or i.is_unknown_studio or i.user_keywords
                ]
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(incomplete, ensure_ascii=False)}]
                    },
                }

            if tool_name == "get_keyword_glossary":
                glossary = {
                    "adult_studios": sorted(set(WESTERN_STUDIO_ALIASES.values())),
                    "jav_prefix_to_maker": JAV_PREFIX_TO_STUDIO,
                    "mainstream_studios": sorted(set(MAINSTREAM_STUDIO_ALIASES.values())),
                    "custom_registered_studios": CUSTOM_STUDIO_REGISTRY,
                    "genres": sorted(set(GENRE_KEYWORD_MAP.values())),
                }
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(glossary, ensure_ascii=False)}]
                    },
                }

            if tool_name == "apply_enriched_metadata":
                records = args.get("records", [])
                updated = import_root_markdown_completions(
                    json.dumps({"records": records}),
                    self.items_by_id,
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"updated_count": updated})}]
                    },
                }

            if tool_name == "register_new_studio":
                alias_or_prefix = str(args.get("alias_or_prefix", "")).strip()
                canonical_name = str(args.get("canonical_name", "")).strip()
                raw_cat = str(args.get("media_category", "western_adult"))
                try:
                    cat = MediaCategory(raw_cat)
                except ValueError:
                    cat = MediaCategory.WESTERN_ADULT
                register_custom_studio(alias_or_prefix, canonical_name, cat)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "status": "registered",
                                        "alias_or_prefix": alias_or_prefix,
                                        "canonical_name": canonical_name,
                                        "media_category": cat.value,
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ]
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
