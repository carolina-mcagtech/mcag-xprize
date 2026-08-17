#!/usr/bin/env python3
"""Florida Regulations MCP Server — stdio transport for Google ADK McpToolset.

Run by the ADK framework as a subprocess when analyze_agent needs regulation
queries. No persistent process, no ports, no OOM risk.

Usage (standalone test):
    python mcp_server/florida_regulations_server.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from mcp.server.fastmcp import FastMCP

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
logger = logging.getLogger(__name__)

_CHROMA_PATH = str(Path(__file__).parent.parent / "chroma_db")
_REGULATIONS_PATH = Path(__file__).parent.parent / "data" / "fl_regulations.txt"
_COLLECTION_NAME = "fl_regulations"

mcp = FastMCP("florida-regulations")


def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=_CHROMA_PATH)
    ef = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_or_create_collection(
        name=_COLLECTION_NAME, embedding_function=ef
    )
    if collection.count() == 0:
        _seed(collection)
    return collection


def _seed(collection: chromadb.Collection) -> None:
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
    logger.info("Seeded ChromaDB with %d regulation chunks", len(chunks))


@mcp.tool()
def query_florida_regulations(query: str, n_results: int = 4) -> str:
    """Query the Florida home inspection regulatory knowledge base.

    Performs semantic search over FL Statute 468, Florida Building Code,
    Citizens 4-Point (HO-800), and Wind Mitigation (OIR-B1-1802) requirements.
    Returns a JSON array of the most relevant regulation excerpts.

    Args:
        query: Natural language description of the inspection finding, e.g.
               "Zinsco electrical panel insurance eligibility Citizens 4-point".
        n_results: Number of regulation excerpts to return (default 4, max 10).

    Returns:
        JSON-encoded list of regulation excerpt strings.
    """
    try:
        collection = _get_collection()
        count = collection.count()
        if count == 0:
            return json.dumps([])
        n = min(max(1, n_results), 10, count)
        results = collection.query(query_texts=[query], n_results=n)
        excerpts: list[str] = results["documents"][0] if results["documents"] else []
        return json.dumps(excerpts)
    except Exception as exc:
        logger.error("query_florida_regulations failed: %s", exc)
        return json.dumps([])


if __name__ == "__main__":
    mcp.run()
