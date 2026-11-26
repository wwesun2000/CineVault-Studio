#!/usr/bin/env python3
"""
Quick Local Launcher for CineVault Studio (`scripts/run_dev.py`).
Starts the SQLite repository, generates the root `AI_KEYWORD_DB.md` file,
launches the ThreadingHTTPServer on `http://127.0.0.1:8765`, and opens the UI.
"""

from __future__ import annotations
import argparse
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.http_server import (
    _export_enhanced_keyword_db_md,
    create_http_server,
    resolve_app_root,
    resolve_bundle_root,
)
from src.adapters.sqlite_repo import SQLiteLibraryRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="CineVault Studio Local Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    parser.add_argument("--self-check", action="store_true", help="Start server, probe endpoints, and exit")
    args = parser.parse_args()

    app_root = resolve_app_root()
    bundle_root = resolve_bundle_root()
    db_path = app_root / "cinevault_library.db"
    repo = SQLiteLibraryRepository(db_path)
    items = repo.load_all_items()
    md_path = app_root / "AI_KEYWORD_DB.md"
    if not md_path.is_file():
        _export_enhanced_keyword_db_md(items, md_path, export_mode="incomplete", batch_index=0, batch_size=25)

    ui_file = bundle_root / "src" / "ui" / "index.html"
    server = create_http_server(
        repo=repo,
        host=args.host,
        port=args.port,
        ui_html_path=ui_file,
        config_path=app_root / "config.json",
        covers_dir=app_root / ".cinevault_covers",
    )
    url = f"http://{args.host}:{args.port}"
    print(f"[CineVault Studio] Database initialized at: {db_path}")
    print(f"[CineVault Studio] Root CLI Keyword DB ready at: {app_root / 'AI_KEYWORD_DB.md'}")
    print(f"[CineVault Studio] Serving UI & REST API at: {url}")

    if args.self_check:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(f"{url}/", timeout=5) as resp:
                assert resp.status == 200, f"Unexpected / status: {resp.status}"
                html_len = len(resp.read())
            with urllib.request.urlopen(f"{url}/api/library", timeout=5) as resp:
                assert resp.status == 200, f"Unexpected /api/library status: {resp.status}"
            with urllib.request.urlopen(f"{url}/api/config", timeout=5) as resp:
                assert resp.status == 200, f"Unexpected /api/config status: {resp.status}"
            print(f"[Self-Check OK] / ({html_len} bytes), /api/library (200), /api/config (200)")
        finally:
            server.shutdown()
            server.server_close()
        return 0

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[CineVault Studio] Shutting down server...")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
