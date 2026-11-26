"""
SQLite Library Persistence Repository (`src/adapters/sqlite_repo.py`).
Assigned to Hydrogen: `[HYDROGEN-TASK-02]`.
"""

from __future__ import annotations
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Iterator, List, Optional
from ..core.models import MediaItem


# [HYDROGEN-TASK-02]
class SQLiteLibraryRepository:
    """
    Lightweight SQLite persistence engine storing MediaItem records indexed by `item_id` and `fast_hash`.
    """

    def __init__(self, db_path: str | Path = "cinevault_library.db") -> None:
        self.db_path = str(db_path)
        self.init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS media_items (
                    item_id TEXT PRIMARY KEY,
                    fast_hash TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    studio TEXT,
                    release_date TEXT,
                    rating_half_steps INTEGER DEFAULT 0,
                    is_incomplete INTEGER DEFAULT 1,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_media_fast_hash ON media_items(fast_hash)")
            conn.commit()

    def upsert_items(self, items: List[MediaItem]) -> int:
        if not items:
            return 0
        rows = []
        for item in items:
            item.refresh_completeness()
            payload = json.dumps(item.to_dict(), ensure_ascii=False)
            rows.append(
                (
                    item.item_id,
                    item.fast_hash,
                    item.file_path,
                    item.studio,
                    item.release_date,
                    item.rating_half_steps,
                    1 if item.is_incomplete else 0,
                    payload,
                )
            )
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO media_items
                (item_id, fast_hash, file_path, studio, release_date, rating_half_steps, is_incomplete, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(items)

    def load_all_items(self) -> List[MediaItem]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM media_items ORDER BY release_date DESC, item_id ASC").fetchall()
        return [MediaItem.from_dict(json.loads(r[0])) for r in rows]

    def get_item(self, item_id: str) -> Optional[MediaItem]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM media_items WHERE item_id = ?", (item_id,)).fetchone()
        if not row:
            return None
        return MediaItem.from_dict(json.loads(row[0]))

    def update_rating(self, item_id: str, rating: float) -> bool:
        item = self.get_item(item_id)
        if item is None:
            return False
        item.set_rating(rating)
        self.upsert_items([item])
        return True

    def update_user_keywords(self, item_id: str, keywords: List[str]) -> bool:
        item = self.get_item(item_id)
        if item is None:
            return False
        item.user_keywords = [k.strip() for k in keywords if k.strip()]
        self.upsert_items([item])
        return True
