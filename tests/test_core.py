"""
Argon Core Verification Suite (`tests/test_core.py`).
Validates all Argon core engines with zero network dependencies:
1. Half-star rating validation (0.0 to 5.0 in 0.5 increments).
2. O(1) 3-chunk 64KB fast composite hashing (`compute_fast_fingerprint`) & stateful move/add/delete/duplicate reconciliation.
3. Tri-Engine Heuristic Parsing + Unrecorded New Studio Detection:
   - Western Adult Studio / Release Date / Performer / Title + unrecorded studio (`is_unknown_studio=True`).
   - Japanese JAV (`SSIS-001-C`, `FC2-PPV-3109221`, unrecorded new JAV prefix `KMHRS-099`).
   - Mainstream Movies (`Dune.Part.Two.2024.2160p.UHD.BluRay...`, `Oppenheimer (2023)`) and TV Series (`S02E01`).
4. Multi-Faceted Category Search (`filter_and_search_library`) across Genre Tag, Studio, Performer, Title/JAV Code, and Half-Star Rating.
5. Dual-mode AI enrichment + Auto-Registration of New Unrecorded Studios (`register_custom_studio` via Markdown CLI & MCP `register_new_studio` / `apply_enriched_metadata`).
6. Cross-platform `.cvpack` export and hash-matched Android/PC import reconciliation.
7. VLC Media Player CLI launch command, Android intent URI, and M3U8 playlist generation.
"""

from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from src.core.models import (
    MediaCategory,
    StorageSourceType,
    FileDiffStatus,
    CoverSourceType,
    ScannedFileEntry,
    OnlineMetadataCandidate,
    MediaItem,
    LibraryFilterCriteria,
)
from src.core.hasher import (
    compute_fast_fingerprint,
    reconcile_library_state,
)
from src.core.parser import (
    parse_western_media_path,
    apply_parsed_tokens_to_item,
    normalize_studio_name,
    normalize_jav_maker,
    CUSTOM_STUDIO_REGISTRY,
)
from src.core.metadata_engine import (
    select_metadata_providers,
    compute_smart_frame_timestamp,
    enrich_media_item,
    filter_and_search_library,
    generate_kodi_nfo_xml,
)
from src.core.ai_bridge import (
    export_root_markdown_keyword_db,
    import_root_markdown_completions,
    build_interactive_ai_prompt,
    MCPServerEngine,
)
from src.core.sync_bundle import (
    export_cvpack_bundle,
    import_and_reconcile_cvpack,
)
from src.core.player_bridge import (
    build_vlc_launch_command,
    build_android_intent_uri,
    export_m3u8_playlist,
)


class TestArgonCoreEngine(unittest.TestCase):
    def setUp(self) -> None:
        CUSTOM_STUDIO_REGISTRY["western_adult"].clear()
        CUSTOM_STUDIO_REGISTRY["japanese_jav"].clear()
        CUSTOM_STUDIO_REGISTRY["mainstream"].clear()

    def test_half_star_rating_invariants(self) -> None:
        item = MediaItem(
            item_id="cv_test01",
            file_path="/media/vixen_scene.mp4",
            file_name="vixen_scene.mp4",
            parent_dirs=["media"],
            size_bytes=1024,
            mtime_epoch=1700000000.0,
            fast_hash="cvh1_000000000400_abcdef",
        )
        for valid_stars in [0.0, 0.5, 1.0, 2.5, 3.5, 4.5, 5.0]:
            item.set_rating(valid_stars)
            self.assertAlmostEqual(item.rating, valid_stars)
            self.assertEqual(item.rating_half_steps, int(round(valid_stars * 2)))

        with self.assertRaises(ValueError):
            item.set_rating(5.5)
        with self.assertRaises(ValueError):
            item.set_rating(-0.5)
        with self.assertRaises(ValueError):
            item.set_rating(3.3)

    def test_fast_fingerprint_and_move_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            f1 = root / "Vixen.25.02.14.Eve.Sweet.Sunset.Villa.mp4"
            payload_1 = (b"HEAD_BLOCK_" * 8000) + (b"MID_BLOCK_" * 16000) + (b"TAIL_BLOCK_" * 8000)
            f1.write_bytes(payload_1)
            hash_1 = compute_fast_fingerprint(f1)
            self.assertTrue(hash_1.startswith("cvh1_"))

            scan_1 = [
                ScannedFileEntry(
                    path=str(f1),
                    filename=f1.name,
                    parent_dirs=["Vixen", "2025"],
                    size_bytes=f1.stat().st_size,
                    mtime_epoch=f1.stat().st_mtime,
                    source_type=StorageSourceType.LOCAL_DISK,
                    fast_hash=hash_1,
                )
            ]
            rep_1 = reconcile_library_state([], scan_1, auto_Enrich_parser_callback=apply_parsed_tokens_to_item)
            self.assertEqual(len(rep_1.added), 1)
            added_item = rep_1.added[0]
            added_item.set_rating(4.5)
            added_item.last_played_pos_sec = 315.0

            new_nas_path = "//192.168.1.50/MediaVault/Archive/Eve_Sweet_Moved.mp4"
            scan_2 = [
                ScannedFileEntry(
                    path=new_nas_path,
                    filename="Eve_Sweet_Moved.mp4",
                    parent_dirs=["MediaVault", "Archive"],
                    size_bytes=f1.stat().st_size,
                    mtime_epoch=f1.stat().st_mtime + 100,
                    source_type=StorageSourceType.SAMBA_SMB,
                    fast_hash=hash_1,
                )
            ]
            rep_2 = reconcile_library_state(rep_1.active_library, scan_2)
            self.assertEqual(len(rep_2.moved_or_renamed), 1)
            moved_item = rep_2.moved_or_renamed[0]
            self.assertEqual(moved_item.file_path, new_nas_path)
            self.assertEqual(moved_item.previous_path, str(f1))
            self.assertAlmostEqual(moved_item.rating, 4.5)
            self.assertAlmostEqual(moved_item.last_played_pos_sec, 315.0)

    def test_tri_engine_parser_western_jav_and_mainstream(self) -> None:
        # 1. Western Adult Scene Dot-Notation
        t1 = parse_western_media_path(
            "/nas/Vixen.25.02.14.Eve.Sweet.And.Alberto.Blanco.Sunset.Villa.XXX.2160p.MP4",
            parent_dirs=["nas"],
        )
        self.assertEqual(t1.media_category, MediaCategory.WESTERN_ADULT)
        self.assertEqual(t1.studio, "Vixen")
        self.assertFalse(t1.is_unknown_studio)
        self.assertEqual(t1.release_date, "2025-02-14")
        self.assertIn("Eve Sweet", t1.performers)

        # 2. Unrecorded New Western Adult Studio -> Flagged `is_unknown_studio=True`
        t_new_west = parse_western_media_path(
            "D:/Vault/[LuxureAesthetics] (2025-01-18) Agatha Vega - Velvet Chateau [4K].mp4",
            parent_dirs=["Vault"],
        )
        self.assertEqual(t_new_west.media_category, MediaCategory.WESTERN_ADULT)
        self.assertEqual(t_new_west.studio, "LuxureAesthetics")
        self.assertTrue(t_new_west.is_unknown_studio)
        self.assertEqual(t_new_west.raw_studio_token, "LuxureAesthetics")

        # 3. Japanese JAV Standard Maker Code (`SSIS-001-C`)
        t_jav = parse_western_media_path(
            "//192.168.1.50/JAV/S1/SSIS-001-C 河北彩花 - 最高峰アイドル [4K].mp4",
            parent_dirs=["JAV", "S1"],
        )
        self.assertEqual(t_jav.media_category, MediaCategory.JAPANESE_JAV)
        self.assertEqual(t_jav.jav_code, "SSIS-001")
        self.assertEqual(t_jav.studio, "S1 NO.1 STYLE")
        self.assertFalse(t_jav.is_unknown_studio)
        self.assertIn("中文字幕", t_jav.tags)
        self.assertIn("河北彩花", t_jav.performers)

        # 4. Japanese JAV FC2-PPV Amateur Code
        t_fc2 = parse_western_media_path(
            "D:/JAV/FC2-PPV-3109221 初撮り素人 1080p.mp4",
            parent_dirs=["JAV"],
        )
        self.assertEqual(t_fc2.media_category, MediaCategory.JAPANESE_JAV)
        self.assertEqual(t_fc2.jav_code, "FC2-PPV-3109221")
        self.assertEqual(t_fc2.studio, "FC2-PPV Amateur")
        self.assertIn("FC2 素人", t_fc2.tags)

        # 5. Unrecorded New Japanese JAV Prefix (`KMHRS-099`) -> Flagged `is_unknown_studio=True`
        t_new_jav = parse_western_media_path(
            "D:/JAV/KMHRS-099-C 铃森玲梦 - 新锐企划.mp4",
            parent_dirs=["JAV"],
        )
        self.assertEqual(t_new_jav.media_category, MediaCategory.JAPANESE_JAV)
        self.assertEqual(t_new_jav.jav_code, "KMHRS-099")
        self.assertTrue(t_new_jav.is_unknown_studio)
        self.assertEqual(t_new_jav.raw_studio_token, "KMHRS")

        # 6. Mainstream Movie Release Dot-Notation
        t4 = parse_western_media_path(
            "//192.168.1.50/Cinema/Dune.Part.Two.2024.2160p.UHD.BluRay.Remux.HEVC.Atmos.mkv",
            parent_dirs=["Cinema", "WarnerBros"],
        )
        self.assertEqual(t4.media_category, MediaCategory.MAINSTREAM_MOVIE)
        self.assertEqual(t4.title, "Dune Part Two")
        self.assertEqual(t4.release_date, "2024")
        self.assertEqual(t4.studio, "Warner Bros. Pictures")

    def test_multi_faceted_category_search_engine(self) -> None:
        items = [
            MediaItem(
                item_id="cv_1",
                file_path="/nas/vixen.mp4",
                file_name="vixen.mp4",
                parent_dirs=[],
                size_bytes=100,
                mtime_epoch=1.0,
                fast_hash="h1",
                media_category=MediaCategory.WESTERN_ADULT,
                studio="Vixen",
                title="Sunset Villa",
                performers=["Eve Sweet"],
                release_date="2025-02-14",
                tags=["Glamour", "4K Ultra HD"],
                rating=4.5,
            ),
            MediaItem(
                item_id="cv_2",
                file_path="/nas/ssis001.mp4",
                file_name="ssis001.mp4",
                parent_dirs=[],
                size_bytes=100,
                mtime_epoch=1.0,
                fast_hash="h2",
                media_category=MediaCategory.JAPANESE_JAV,
                jav_code="SSIS-001",
                studio="S1 NO.1 STYLE",
                title="最高峰アイドル",
                performers=["河北彩花"],
                release_date="2024-05-19",
                tags=["中文字幕", "4K Ultra HD"],
                rating=5.0,
            ),
            MediaItem(
                item_id="cv_3",
                file_path="/nas/dune2.mkv",
                file_name="dune2.mkv",
                parent_dirs=[],
                size_bytes=100,
                mtime_epoch=1.0,
                fast_hash="h3",
                media_category=MediaCategory.MAINSTREAM_MOVIE,
                studio="Warner Bros. Pictures",
                title="Dune Part Two",
                performers=["Timothée Chalamet", "Zendaya"],
                release_date="2024-03-01",
                tags=["Sci-Fi", "IMAX"],
                rating=5.0,
            ),
        ]

        # Filter by Japanese JAV + Performer '河北彩花' + Tag '中文字幕' + Min Rating 4.5
        res_jav = filter_and_search_library(
            items,
            LibraryFilterCriteria(
                media_category="japanese_jav",
                performer="河北彩花",
                tag="中文字幕",
                min_rating=4.5,
            ),
        )
        self.assertEqual(len(res_jav), 1)
        self.assertEqual(res_jav[0].jav_code, "SSIS-001")

        # Filter by Studio 'Vixen' and Exact Rating 4.5
        res_vixen = filter_and_search_library(
            items,
            LibraryFilterCriteria(studio="Vixen", exact_rating=4.5),
        )
        self.assertEqual(len(res_vixen), 1)
        self.assertEqual(res_vixen[0].title, "Sunset Villa")

        # Search by JAV code substring
        res_code = filter_and_search_library(
            items,
            LibraryFilterCriteria(title_or_keyword="ssis-001"),
        )
        self.assertEqual(len(res_code), 1)

    def test_ai_new_studio_auto_registration_md_and_mcp(self) -> None:
        # Item with unrecorded new JAV prefix `KMHRS`
        jav_item = MediaItem(
            item_id="cv_newjav01",
            file_path="D:/JAV/KMHRS-099-C.mp4",
            file_name="KMHRS-099-C.mp4",
            parent_dirs=["JAV"],
            size_bytes=2048,
            mtime_epoch=1700000000.0,
            fast_hash="cvh1_000000000800_998877",
            media_category=MediaCategory.JAPANESE_JAV,
            jav_code="KMHRS-099",
            studio="待AI识别日系厂牌 (KMHRS)",
            is_unknown_studio=True,
            user_keywords=["SOD KMHRS", "铃森玲梦"],
        )
        self.assertTrue(jav_item.is_incomplete)
        self.assertIsNone(normalize_jav_maker("KMHRS"))

        # Export Root Markdown CLI DB and verify `is_unknown_studio` is included
        md_text = export_root_markdown_keyword_db([jav_item])
        self.assertIn("KMHRS-099", md_text)
        self.assertIn("new_studio_alias_to_register", md_text)

        # Simulate AI completing the studio name and importing back
        items_map = {jav_item.item_id: jav_item}
        mcp = MCPServerEngine(items_map)

        call_resp = mcp.handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "apply_enriched_metadata",
                "arguments": {
                    "records": [
                        {
                            "item_id": "cv_newjav01",
                            "media_category": "japanese_jav",
                            "jav_code": "KMHRS-099",
                            "new_studio_alias_to_register": "KMHRS",
                            "studio": "SOD KMHRS (キミホレ)",
                            "title": "キミだけに惚れた 新鋭デビュー",
                            "performers": ["铃森玲梦"],
                            "release_date": "2025-01-22",
                            "tags": ["中文字幕", "专属女优"],
                        }
                    ]
                },
            },
        })
        res_data = json.loads(call_resp["result"]["content"][0]["text"])
        self.assertEqual(res_data["updated_count"], 1)
        self.assertFalse(jav_item.is_unknown_studio)
        self.assertFalse(jav_item.is_incomplete)
        # Verify KMHRS is now permanently registered in the runtime JAV maker dictionary!
        self.assertEqual(normalize_jav_maker("KMHRS"), "SOD KMHRS (キミホレ)")

        # Also test direct MCP `register_new_studio` tool for a new Western studio
        mcp.handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "register_new_studio",
                "arguments": {
                    "alias_or_prefix": "LuxureAesthetics",
                    "canonical_name": "Luxure Aesthetics",
                    "media_category": "western_adult",
                },
            },
        })
        self.assertEqual(normalize_studio_name("LuxureAesthetics"), "Luxure Aesthetics")

    def test_metadata_enrichment_and_smart_frame_fallback(self) -> None:
        self.assertEqual(select_metadata_providers(MediaCategory.WESTERN_ADULT), ["ThePornDB", "StashDB"])
        self.assertEqual(select_metadata_providers(MediaCategory.JAPANESE_JAV), ["JavDB", "FANZA"])
        self.assertEqual(select_metadata_providers(MediaCategory.MAINSTREAM_MOVIE), ["TMDB", "OMDb"])

        timestamps = compute_smart_frame_timestamp(2000.0)
        self.assertEqual(len(timestamps), 3)
        self.assertGreaterEqual(timestamps[0], 300.0)

        item = MediaItem(
            item_id="cv_meta01",
            file_path="/nas/MetArt/2025/Eva Elfie - Golden Hour.mp4",
            file_name="Eva Elfie - Golden Hour.mp4",
            parent_dirs=["MetArt", "2025"],
            size_bytes=500000,
            mtime_epoch=1700000000.0,
            fast_hash="cvh1_00000007a120_112233",
        )
        tokens = parse_western_media_path(item.file_path, item.parent_dirs)
        cand = OnlineMetadataCandidate(
            provider="ThePornDB",
            external_id="tpdb_1",
            title="Golden Hour",
            studio="MetArt",
            performers=["Eva Elfie"],
            release_date="2025-01-10",
            tags=["Artistic", "Glamour"],
            cover_url="",
        )
        enrich_media_item(
            item,
            tokens,
            [cand],
            extracted_frame_cover="/cache/frames/cv_meta01_frame.jpg",
        )
        self.assertFalse(item.is_incomplete)
        self.assertEqual(item.cover_source, CoverSourceType.VIDEO_FRAME)
        self.assertEqual(item.cover_path, "/cache/frames/cv_meta01_frame.jpg")

        nfo_xml = generate_kodi_nfo_xml(item)
        self.assertIn("<studio>MetArt</studio>", nfo_xml)

    def test_cross_platform_cvpack_sync_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            win_item = MediaItem(
                item_id="cv_sync01",
                file_path=r"D:\Videos\Blacked\Midnight_Heat.mkv",
                file_name="Midnight_Heat.mkv",
                parent_dirs=["Videos", "Blacked"],
                size_bytes=987654,
                mtime_epoch=1700000000.0,
                fast_hash="cvh1_0000000f1206_aabbccddeeff00112233445566778899",
                studio="Blacked",
                title="Midnight Heat",
                performers=["Violet Myers"],
                release_date="2024-11-08",
                rating=5.0,
            )
            pack_path = tmp / "export.cvpack"
            manifest = export_cvpack_bundle([win_item], pack_path, include_covers=False)
            self.assertEqual(manifest["total_items"], 1)

            android_scan = [
                ScannedFileEntry(
                    path="/storage/emulated/0/Movies/Vault/Midnight_Heat_Renamed.mkv",
                    filename="Midnight_Heat_Renamed.mkv",
                    parent_dirs=["Movies", "Vault"],
                    size_bytes=987654,
                    mtime_epoch=1700005000.0,
                    source_type=StorageSourceType.LOCAL_DISK,
                    fast_hash="cvh1_0000000f1206_aabbccddeeff00112233445566778899",
                )
            ]
            sync_res = import_and_reconcile_cvpack(pack_path, android_scan)
            self.assertEqual(sync_res.matched_by_hash, 1)
            synced_item = sync_res.synced_items[0]
            self.assertEqual(synced_item.file_path, "/storage/emulated/0/Movies/Vault/Midnight_Heat_Renamed.mkv")
            self.assertAlmostEqual(synced_item.rating, 5.0)

    def test_vlc_player_bridge_and_m3u8(self) -> None:
        cmd = build_vlc_launch_command(
            vlc_exe=r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            video_path=r"D:\Media\Vixen_Sunset.mp4",
            start_time_sec=125.0,
            fullscreen=True,
            custom_title="Sunset Villa",
        )
        self.assertEqual(cmd[0], r"C:\Program Files\VideoLAN\VLC\vlc.exe")
        self.assertIn("--start-time=125", cmd)
        self.assertIn("--fullscreen", cmd)

        intent_uri = build_android_intent_uri("/storage/emulated/0/Movies/Sunset.mp4")
        self.assertTrue(intent_uri.startswith("vlc://file://"))

        item = MediaItem(
            item_id="cv_p01",
            file_path=r"D:\Media\Vixen_Sunset.mp4",
            file_name="Vixen_Sunset.mp4",
            parent_dirs=["Media"],
            size_bytes=1024,
            mtime_epoch=1700000000.0,
            fast_hash="cvh1_000000000400_123456",
            studio="Vixen",
            title="Sunset Villa",
            performers=["Eve Sweet"],
            rating=4.5,
        )
        m3u8 = export_m3u8_playlist([item])
        self.assertIn("#EXTM3U", m3u8)
        self.assertIn("[Vixen] Eve Sweet - Sunset Villa (4.5★)", m3u8)


if __name__ == "__main__":
    unittest.main()
