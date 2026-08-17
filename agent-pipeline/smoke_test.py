#!/usr/bin/env python3
"""
smoke_test.py — Import-only smoke test for agent-pipeline/.

Verifies that each pipeline module can be *imported* without executing any
LLM/Vertex AI call and without requiring real GCP credentials. Agent objects
(google.adk.agents.Agent) and the MCP toolset are declarative at
construction time in this codebase — building them just holds config, it
does not open a network connection or spawn the MCP server subprocess.
The actual Gemini client (google.genai.Client) is constructed lazily inside
functions in tools/classify_photo.py, tools/generate_narrative.py, and
tools/audit_narrative.py, never at module import time — so importing these
modules alone should never call out to Gemini or GCP.

This script only verifies importability. It does not verify agent behavior.

Usage:
    python3 smoke_test.py

Exit code: 0 if every module imports cleanly, 1 otherwise.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# These modules use "from tools.x import y" / "from agents.x import y"
# (no "agent_pipeline." package prefix), matching the sys.path convention
# api.py and main.py already use in this repo: agent-pipeline/ itself must
# be on sys.path, not its parent.
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# Defensive stubs only. None of the modules below actually require these at
# import time (GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION are read lazily
# via os.environ.get(..., default) and only consumed when a Gemini client is
# constructed inside a function call, not at module scope). Set anyway so
# a clean environment can't accidentally mask a real requirement.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "smoke-test-project")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GEMINI_API_KEY", "smoke-test-key")
os.environ.setdefault("MCP_SERVER_URL", "http://localhost:8001")

MODULES = [
    "agents.capture_agent",
    "agents.analyze_agent",
    "agents.report_agent",
    "agents.audit_agent",
    "orchestrator.agent",
    "mcp_server",
    "mcp_server.florida_regulations_server",
    "mcp_server.florida_regulations_mcp",
]


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    for name in MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # smoke test: catch everything, report it
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
        else:
            results.append((name, True, ""))

    print("=" * 72)
    print("agent-pipeline import smoke test")
    print("=" * 72)
    failed = 0
    for name, ok, err in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failed += 1
            print(f"      {err}")
    print("-" * 72)
    print(f"{len(results) - failed}/{len(results)} modules imported cleanly")
    print("=" * 72)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
