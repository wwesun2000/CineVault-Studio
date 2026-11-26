"""
Standalone MCP Stdio Server Loop (`src/adapters/mcp_stdio_server.py`).
Assigned to Hydrogen: `[HYDROGEN-TASK-05]`.
"""

from __future__ import annotations
import json
import sys
from typing import TextIO
from ..core.ai_bridge import MCPServerEngine
from .sqlite_repo import SQLiteLibraryRepository


# [HYDROGEN-TASK-05]
def run_mcp_stdio_loop(
    engine: MCPServerEngine,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    """
    Reads line-delimited JSON-RPC 2.0 requests from `input_stream`, dispatches each request
    through `engine.handle_jsonrpc()`, and writes the JSON-RPC response line to `output_stream`.
    Returns the number of processed requests.
    """
    processed = 0
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = engine.handle_jsonrpc(req)
        except json.JSONDecodeError:
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        output_stream.write(json.dumps(resp, ensure_ascii=False) + "\n")
        output_stream.flush()
        processed += 1
    return processed


if __name__ == "__main__":
    repo = SQLiteLibraryRepository()
    items_map = {item.item_id: item for item in repo.load_all_items()}
    mcp_engine = MCPServerEngine(items_map)
    run_mcp_stdio_loop(mcp_engine)
    for updated_item in items_map.values():
        repo.upsert_items([updated_item])
