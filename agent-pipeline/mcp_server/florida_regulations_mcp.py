"""
Florida Regulations MCP Server — exposes ChromaDB as an MCP tool server.

Implements the Model Context Protocol (JSON-RPC 2.0 over HTTP transport,
protocol version 2024-11-05).

Tool exposed:
    query_florida_regulations(query: str, n_results: int = 4)
        → returns the N most relevant FL regulation excerpts from ChromaDB

Run standalone:
    uvicorn mcp_server.florida_regulations_mcp:mcp_app --port 8001
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions
from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_CHROMA_PATH = str(Path(__file__).parent.parent / "chroma_db")
_REGULATIONS_PATH = Path(__file__).parent.parent / "data" / "fl_regulations.txt"
_COLLECTION_NAME = "fl_regulations"

mcp_app = FastAPI(
    title="FloridaInspect MCP Server",
    version="1.0.0",
    description="MCP server exposing Florida home inspection regulations via ChromaDB RAG",
)

# ── ChromaDB helpers ──────────────────────────────────────────────────────────

def _get_collection() -> chromadb.Collection:
    """Return the regulations collection. Read-only — seeding is done by the main app at startup."""
    client = chromadb.PersistentClient(path=_CHROMA_PATH)
    ef = embedding_functions.DefaultEmbeddingFunction()
    return client.get_or_create_collection(name=_COLLECTION_NAME, embedding_function=ef)


def _seed_collection(collection: chromadb.Collection) -> None:
    """Parse fl_regulations.txt into chunks and seed ChromaDB."""
    if not _REGULATIONS_PATH.exists():
        logger.warning("fl_regulations.txt not found at %s", _REGULATIONS_PATH)
        return
    text = _REGULATIONS_PATH.read_text(encoding="utf-8")
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("---") and current:
            chunk = "\n".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []
        else:
            current.append(line)
    if current:
        chunk = "\n".join(current).strip()
        if chunk:
            chunks.append(chunk)
    if not chunks:
        return
    collection.add(
        documents=chunks,
        ids=[f"reg_{i}" for i in range(len(chunks))],
        metadatas=[{"source": "fl_regulations.txt", "chunk": i} for i in range(len(chunks))],
    )
    logger.info("MCP server: seeded ChromaDB with %d regulation chunks", len(chunks))


# ── MCP protocol constants ────────────────────────────────────────────────────

_PROTOCOL_VERSION = "2024-11-05"

_SERVER_INFO: dict[str, str] = {
    "name": "florida-regulations-mcp",
    "version": "1.0.0",
}

_CAPABILITIES: dict[str, Any] = {"tools": {}}

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_florida_regulations",
        "description": (
            "Query the Florida home inspection regulatory knowledge base. "
            "Performs semantic search over FL Statute 468, FBC, Citizens 4-Point, "
            "and Wind Mitigation requirements stored in ChromaDB. "
            "Returns the most relevant regulation excerpts for a given finding."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural language description of the inspection finding to look up. "
                        "Example: 'roof granule loss asphalt shingles Citizens insurance'"
                    ),
                },
                "n_results": {
                    "type": "integer",
                    "description": "Number of regulation excerpts to return (default: 4, max: 10)",
                    "default": 4,
                },
            },
            "required": ["query"],
        },
    }
]


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────

class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Any = None
    method: str
    params: dict = {}


def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@mcp_app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "server": "florida-regulations-mcp", "protocol": _PROTOCOL_VERSION}


@mcp_app.post("/")
def handle_rpc(req: JsonRpcRequest) -> dict:
    """Main MCP JSON-RPC 2.0 endpoint."""
    method = req.method

    # ── initialize ───────────────────────────────────────────────────────────
    if method == "initialize":
        return _ok(req.id, {
            "protocolVersion": _PROTOCOL_VERSION,
            "serverInfo": _SERVER_INFO,
            "capabilities": _CAPABILITIES,
        })

    # ── notifications/initialized (no response for notifications) ────────────
    if method == "notifications/initialized":
        return {}

    # ── tools/list ───────────────────────────────────────────────────────────
    if method == "tools/list":
        return _ok(req.id, {"tools": _TOOLS})

    # ── tools/call ───────────────────────────────────────────────────────────
    if method == "tools/call":
        name = req.params.get("name")
        args = req.params.get("arguments", {})

        if name != "query_florida_regulations":
            return _err(req.id, -32601, f"Unknown tool: {name!r}")

        query = str(args.get("query", "")).strip()
        if not query:
            return _err(req.id, -32602, "'query' argument is required and must be non-empty")

        n_results = min(int(args.get("n_results", 4)), 10)

        try:
            collection = _get_collection()
            n = min(n_results, max(1, collection.count()))
            results = collection.query(query_texts=[query], n_results=n)
            excerpts: list[str] = results["documents"][0] if results["documents"] else []
            logger.debug("MCP query returned %d excerpts for: %s", len(excerpts), query[:80])
            return _ok(req.id, {
                "content": [{"type": "text", "text": json.dumps(excerpts)}],
                "isError": False,
            })
        except Exception as exc:
            logger.exception("MCP tool call failed")
            return _ok(req.id, {
                "content": [{"type": "text", "text": "[]"}],
                "isError": True,
            })

    return _err(req.id, -32601, f"Method not found: {method!r}")
