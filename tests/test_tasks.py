"""
Hydrogen Atomic Task Verification Suite (`tests/test_tasks.py`).
Validates TASK-01 through TASK-06 in `HYDROGEN_TASKS.md`.
"""

from __future__ import annotations
import io
import json
import tempfile
import unittest
from pathlib import Path

from src.core.models import MediaItem, ParsedMediaTokens
from src.core.ai_bridge import MCPServerEngine
from src.adapters.storage_smb_cloud import scan_storage_roots
from src.adapters.sqlite_repo import SQLiteLibraryRepository
from src.adapters.online_scrapers import OnlineMetadataScraper
from src.adapters.ffmpeg_runner import build_ffmpeg_extract_cmd
from src.adapters.mcp_stdio_server import run_mcp_stdio_loop
from src.adapters.http_server import dispatch_api_request


class TestHydrogenTasks(unittest.TestCase):
    def test_task01_storage_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            studio_dir = root / "Vixen" / "2025"
            studio_dir.mkdir(parents=True)
            vid = studio_dir / "Vixen.25.02.14.Eve.Sweet.Sunset.Villa.mp4"
            vid.write_bytes(b"FAKE_VIDEO_DATA" * 100)

            entries = scan_storage_roots(
                [{"path": str(root), "source_type": "local_disk"}],
                compute_hashes=True,
            )
            self.assertEqual(len(entries), 1)
            self.assertTrue(entries[0].fast_hash.startswith("cvh1_"))
            self.assertIn("Vixen", entries[0].parent_dirs)

    def test_task02_sqlite_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "test_lib.db"
            repo = SQLiteLibraryRepository(db_file)
            item = MediaItem(
                item_id="cv_sql01",
                file_path="/nas/Vixen/Sunset.mp4",
                file_name="Sunset.mp4",
                parent_dirs=["Vixen"],
                size_bytes=4096,
                mtime_epoch=1700000000.0,
                fast_hash="cvh1_000000001000_abcdef",
                studio="Vixen",
                title="Sunset Villa",
                performers=["Eve Sweet"],
                release_date="2025-02-14",
                rating=4.0,
            )
            repo.upsert_items([item])
            self.assertTrue(repo.update_rating("cv_sql01", 4.5))
            self.assertTrue(repo.update_user_keywords("cv_sql01", ["4K", "Mediterranean"]))

            loaded = repo.get_item("cv_sql01")
            self.assertIsNotNone(loaded)
            self.assertAlmostEqual(loaded.rating, 4.5)
            self.assertEqual(loaded.rating_half_steps, 9)
            self.assertIn("Mediterranean", loaded.user_keywords)

    def test_task03_online_scraper(self) -> None:
        scraper = OnlineMetadataScraper(api_token=None)
        tokens = ParsedMediaTokens(
            raw_path="/nas/Vixen/Sunset Villa.mp4",
            studio="Vixen",
            title="Sunset Villa",
            performers=["Eve Sweet"],
        )
        candidates = scraper.search_candidates(tokens, extra_keywords=[])
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0].studio, "Vixen")

        mock_tpdb_payload = {
            "data": [
                {
                    "id": "scene_999",
                    "title": "Parisian Nights",
                    "date": "2024-09-19",
                    "duration": 2100,
                    "site": {"name": "Tushy"},
                    "performers": [{"name": "Kelly Collins"}],
                    "tags": [{"name": "Glamour"}],
                    "posters": {"large": "https://example.com/poster.jpg"},
                }
            ]
        }
        parsed = scraper.parse_tpdb_json_response(mock_tpdb_payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].studio, "Tushy")

    def test_task04_ffmpeg_runner(self) -> None:
        cmd = build_ffmpeg_extract_cmd(
            video_path="/nas/movie.mp4",
            output_jpg_path="/tmp/cover.jpg",
            timestamp_sec=180.5,
            ffmpeg_bin="ffmpeg",
        )
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("180.50", cmd)
        self.assertEqual(cmd[-1], "/tmp/cover.jpg")

    def test_task05_mcp_stdio(self) -> None:
        item = MediaItem(
            item_id="cv_mcp01",
            file_path="/nas/scene.mp4",
            file_name="scene.mp4",
            parent_dirs=["nas"],
            size_bytes=1024,
            mtime_epoch=1700000000.0,
            fast_hash="cvh1_000000000400_111111",
        )
        engine = MCPServerEngine({"cv_mcp01": item})
        in_stream = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 10, "method": "tools/list"}) + "\n"
        )
        out_stream = io.StringIO()
        count = run_mcp_stdio_loop(engine, in_stream, out_stream)
        self.assertEqual(count, 1)
        resp = json.loads(out_stream.getvalue().strip())
        self.assertEqual(resp["id"], 10)
        self.assertEqual(len(resp["result"]["tools"]), 4)

    def test_task06_http_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = SQLiteLibraryRepository(Path(tmpdir) / "api.db")
            item = MediaItem(
                item_id="cv_http01",
                file_path=r"D:\Media\Vixen_Sunset.mp4",
                file_name="Vixen_Sunset.mp4",
                parent_dirs=["Media"],
                size_bytes=2048,
                mtime_epoch=1700000000.0,
                fast_hash="cvh1_000000000800_222222",
                studio="Vixen",
                title="Sunset Villa",
                performers=["Eve Sweet"],
                tags=["Glamour"],
            )
            repo.upsert_items([item])

            code, data = dispatch_api_request("GET", "/api/library", None, repo)
            self.assertEqual(code, 200)
            self.assertEqual(len(data["items"]), 1)

            code, data = dispatch_api_request(
                "POST", "/api/rate", {"item_id": "cv_http01", "rating": 4.5}, repo
            )
            self.assertEqual(code, 200)

            code, data = dispatch_api_request(
                "POST",
                "/api/search",
                {"studio": "Vixen", "performer": "Eve Sweet", "tag": "Glamour", "min_rating": 4.5},
                repo,
            )
            self.assertEqual(code, 200)
            self.assertEqual(data["count"], 1)

            code, data = dispatch_api_request(
                "POST", "/api/keywords", {"item_id": "cv_http01", "keywords": "Vixen, Eve Sweet"}, repo
            )
            self.assertEqual(code, 200)

            code, data = dispatch_api_request(
                "POST", "/api/play/vlc", {"item_id": "cv_http01"}, repo
            )
            self.assertEqual(code, 200)
            self.assertIn("command", data)

    def test_http_server_range_and_sync(self) -> None:
        import threading
        import urllib.request
        from src.adapters.http_server import create_http_server

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            media_dir = tmp / "Vixen"
            media_dir.mkdir()
            video_file = media_dir / "Vixen.25.02.14.Eve.Sweet.Sunset.Villa.mp4"
            video_bytes = b"0123456789ABCDEF" * 64  # 1024 bytes
            video_file.write_bytes(video_bytes)

            cfg_path = tmp / "config.json"
            repo = SQLiteLibraryRepository(tmp / "live.db")

            code, cfg_resp = dispatch_api_request(
                "POST",
                "/api/config",
                {"storage_roots": [{"path": str(tmp), "source_type": "local_disk"}]},
                repo,
                config_path=cfg_path,
            )
            self.assertEqual(code, 200)
            self.assertEqual(len(cfg_resp["config"]["storage_roots"]), 1)

            code, refresh_resp = dispatch_api_request(
                "POST", "/api/refresh", {}, repo, config_path=cfg_path
            )
            self.assertEqual(code, 200)
            self.assertEqual(len(refresh_resp["items"]), 1)
            item_id = refresh_resp["items"][0]["item_id"]

            pack_path = tmp / "out.cvpack"
            code, exp_resp = dispatch_api_request(
                "POST",
                "/api/sync/export",
                {"output_path": str(pack_path)},
                repo,
                config_path=cfg_path,
            )
            self.assertEqual(code, 200)
            self.assertTrue(pack_path.is_file())

            code, imp_resp = dispatch_api_request(
                "POST",
                "/api/sync/import",
                {"cvpack_path": str(pack_path)},
                repo,
                config_path=cfg_path,
            )
            self.assertEqual(code, 200)
            self.assertEqual(imp_resp["matched_by_hash"], 1)

            server = create_http_server(
                repo=repo,
                host="127.0.0.1",
                port=0,
                ui_html_path=Path("src/ui/index.html"),
                config_path=cfg_path,
                covers_dir=tmp / "covers",
            )
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/stream/{item_id}",
                    headers={"Range": "bytes=10-25"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self.assertEqual(resp.status, 206)
                    self.assertEqual(resp.headers.get("Content-Range"), "bytes 10-25/1024")
                    self.assertEqual(resp.read(), video_bytes[10:26])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
