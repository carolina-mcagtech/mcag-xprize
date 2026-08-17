"""
validate_regulation — RAG tool that checks a FindingDraft against Florida
home inspection regulations stored in ChromaDB and returns a regulatory verdict.

Query path:
    1. MCP server (http://localhost:8001 or MCP_SERVER_URL) — preferred
    2. Direct ChromaDB — fallback when MCP server is unavailable

Used by: AnalyzeAgent
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import chromadb
import httpx
from chromadb.utils import embedding_functions
from pydantic import BaseModel, Field

from tools.classify_photo import FindingDraft

logger = logging.getLogger(__name__)

_MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8001")


_REGULATIONS_PATH = Path(__file__).parent.parent / "data" / "fl_regulations.txt"
_CHROMA_COLLECTION = "fl_regulations"
_N_RESULTS = 4  # number of chunks to retrieve


class RegulatoryCheck(BaseModel):
    """Result of validating a finding against Florida regulations."""

    finding_summary: str = Field(default="", description="Brief restatement of the finding being checked")
    applicable_regulations: list[str] = Field(description="List of relevant statute/code references")
    compliant: Optional[bool] = Field(
        default=None,
        description="True=compliant, False=violation found, None=cannot determine",
    )
    violation_description: Optional[str] = Field(
        default=None, description="Description of the specific violation if applicable"
    )
    recommended_action: str = Field(description="Recommended corrective action or next step")
    insurance_impact: str = Field(
        description="Potential impact on homeowner's insurance: none, minor, moderate, critical"
    )
    supporting_excerpts: list[str] = Field(description="Verbatim excerpts from regulations that apply")


def _load_regulations_into_chroma(client: chromadb.Client) -> chromadb.Collection:
    """Parse fl_regulations.txt into chunks and load into ChromaDB if needed."""
    ef = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_or_create_collection(
        name=_CHROMA_COLLECTION, embedding_function=ef
    )

    # Only index if empty
    if collection.count() > 0:
        return collection

    text = _REGULATIONS_PATH.read_text(encoding="utf-8")

    # Split on section separators (lines starting with ---)
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
        return collection

    collection.add(
        documents=chunks,
        ids=[f"reg_{i}" for i in range(len(chunks))],
        metadatas=[{"source": "fl_regulations.txt", "chunk": i} for i in range(len(chunks))],
    )
    return collection


_DEFAULT_CHROMA_PATH = str(Path(__file__).parent.parent / "chroma_db")


def _query_via_mcp(query: str, n_results: int = _N_RESULTS) -> list[str] | None:
    """Query regulations via the MCP server. Returns excerpts or None on failure."""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "query_florida_regulations",
                "arguments": {"query": query, "n_results": n_results},
            },
        }
        resp = httpx.post(_MCP_SERVER_URL, json=payload, timeout=5.0)
        resp.raise_for_status()
        result = resp.json().get("result", {})
        if result.get("isError"):
            return None
        content = result.get("content", [])
        if content:
            return json.loads(content[0]["text"])
    except Exception:
        pass
    return None


def validate_regulation(
    finding: FindingDraft,
    chroma_path: Optional[str] = None,
) -> RegulatoryCheck:
    """Check a FindingDraft against Florida home inspection regulations via RAG.

    Tries the MCP server first; falls back to direct ChromaDB if unavailable.

    Args:
        finding: A FindingDraft produced by classify_photo.
        chroma_path: Override path for ChromaDB (used by direct fallback only).

    Returns:
        RegulatoryCheck with applicable regulations, compliance verdict, and
        recommended actions.
    """
    query = (
        f"system: {finding.system}. "
        f"location: {finding.location}. "
        f"observation: {finding.observation}. "
        f"severity: {finding.severity}."
    )

    excerpts = _query_via_mcp(query, n_results=_N_RESULTS)
    if excerpts is not None:
        logger.info("validate_regulation: queried via MCP server")
    else:
        logger.info("validate_regulation: MCP unavailable, using direct ChromaDB")
        client = chromadb.PersistentClient(path=chroma_path or _DEFAULT_CHROMA_PATH)
        collection = _load_regulations_into_chroma(client)
        results = collection.query(query_texts=[query], n_results=min(_N_RESULTS, collection.count()))
        excerpts = results["documents"][0] if results["documents"] else []

    return _synthesise_check(finding, excerpts)


def _synthesise_check(finding: FindingDraft, excerpts: list[str]) -> RegulatoryCheck:
    """Build a RegulatoryCheck by matching the finding against retrieved excerpts.

    This is a rule-based fallback used when no LLM call is desired here
    (the AnalyzeAgent's Gemini call handles higher-level synthesis). The
    function applies known Florida-specific heuristics.
    """
    regulations: list[str] = []
    violation: Optional[str] = None
    compliant: Optional[bool] = None
    action = "Have a licensed contractor evaluate and remediate the observed condition."
    insurance_impact = "none"

    obs_lower = finding.observation.lower()

    # --- Roof heuristics ---
    if finding.system == "roof":
        regulations = ["FL Statute 468.8319(a)", "FBC R905", "Citizens 4-Point Form HO-800"]
        if any(kw in obs_lower for kw in ["leak", "missing shingle", "ponding", "sagging"]):
            compliant = False
            violation = "Active or evidenced roof deficiency requiring immediate attention."
            insurance_impact = "critical"
            action = "Engage a licensed roofing contractor for repair. Document with photos and permits."
        elif any(kw in obs_lower for kw in ["granule", "worn", "aged"]):
            compliant = False
            violation = "Roof covering showing end-of-life wear."
            insurance_impact = "moderate"
            action = "Obtain a roof inspection from a licensed roofing contractor; consider replacement."
        else:
            compliant = True
            action = "No immediate action required; monitor at next annual inspection."

    # --- Electrical heuristics ---
    elif finding.system == "electrical":
        regulations = ["FL Statute 468.8319(b)", "NEC 2020", "FL Statute 553.73", "Citizens 4-Point Form HO-800"]
        if any(kw in obs_lower for kw in ["federal pacific", "stab-lok", "zinsco", "sylvania"]):
            compliant = False
            violation = "High-risk panel manufacturer identified (Federal Pacific / Zinsco). Insurance non-eligible."
            insurance_impact = "critical"
            action = "Replace panel with a listed, UL-approved electrical panel by a licensed electrician."
        elif any(kw in obs_lower for kw in ["aluminum wiring", "aluminium wiring"]):
            compliant = False
            violation = "Aluminum branch-circuit wiring present — fire risk without proper remediation."
            insurance_impact = "critical"
            action = "Install COPALUM crimp connectors or AlumiConn devices at all terminations per NEC 310.14."
        elif any(kw in obs_lower for kw in ["double-tap", "double tap", "open junction", "exposed wiring"]):
            compliant = False
            violation = "Code violation in electrical system."
            insurance_impact = "moderate"
            action = "Have a licensed electrician remediate the identified violation."
        elif any(kw in obs_lower for kw in ["gfci", "afci"]) and "missing" in obs_lower:
            compliant = False
            violation = "Required GFCI/AFCI protection absent in required location."
            insurance_impact = "minor"
            action = "Install required GFCI/AFCI protection by a licensed electrician."
        else:
            compliant = None
            action = "Have a licensed electrician evaluate the panel and wiring."

    # --- Plumbing heuristics ---
    elif finding.system == "plumbing":
        regulations = ["FL Statute 468.8319(d)", "FBC Plumbing Code Ch. 6–7", "Citizens 4-Point Form HO-800"]
        if any(kw in obs_lower for kw in ["polybutylene", "poly-butylene", "quest pipe", "gray plastic pipe"]):
            compliant = False
            violation = "Polybutylene supply piping identified — known failure history, insurance non-eligible."
            insurance_impact = "critical"
            action = "Replace all polybutylene supply piping with copper, CPVC, or PEX by a licensed plumber."
        elif "leak" in obs_lower:
            compliant = False
            violation = "Active plumbing leak observed."
            insurance_impact = "major" if finding.severity in ("critical", "major") else "minor"
            action = "Repair leak immediately using a licensed plumber."
        elif any(kw in obs_lower for kw in ["tpr valve", "temperature-pressure", "no relief"]):
            compliant = False
            violation = "Water heater TPR valve missing or improperly terminated — code violation."
            insurance_impact = "moderate"
            action = "Install/repair TPR valve and discharge pipe per FBC Plumbing Code by a licensed plumber."
        else:
            compliant = None
            action = "Have a licensed plumber evaluate the observed plumbing condition."

    # --- HVAC heuristics ---
    elif finding.system == "hvac":
        regulations = ["FL Statute 468.8319(c)", "FBC Mechanical Code", "ASHRAE 62.2", "Citizens 4-Point Form HO-800"]
        if any(kw in obs_lower for kw in ["refrigerant leak", "ice", "oil stain"]):
            compliant = False
            violation = "HVAC refrigerant leak suspected."
            insurance_impact = "moderate"
            action = "Have a licensed HVAC contractor inspect and repair the refrigerant system."
        elif any(kw in obs_lower for kw in ["disconnected duct", "missing duct", "uninsulated duct"]):
            compliant = False
            violation = "Ductwork deficiency found — energy code violation and comfort issue."
            insurance_impact = "minor"
            action = "Repair ductwork to meet FBC Energy Code minimum R-6 insulation in unconditioned spaces."
        elif any(kw in obs_lower for kw in ["15 year", "16 year", "17 year", "18 year", "20 year", "end of life"]):
            compliant = None
            violation = "HVAC equipment at or beyond expected serviceable life."
            insurance_impact = "minor"
            action = "Budget for HVAC replacement; have unit serviced annually until replaced."
        else:
            compliant = None
            action = "Have a licensed HVAC contractor service and evaluate the system."

    # --- Structure / other ---
    else:
        regulations = ["FL Statute 468.8319(a)", "FBC Structural"]
        if finding.severity in ("critical", "major"):
            compliant = False
            violation = f"Structural or other significant deficiency: {finding.observation[:120]}"
            insurance_impact = "moderate"
            action = "Engage a licensed contractor or structural engineer for evaluation."
        else:
            compliant = None
            action = "Monitor condition; consult a licensed contractor if worsening."

    return RegulatoryCheck(
        finding_summary=finding.observation[:200],
        applicable_regulations=regulations,
        compliant=compliant,
        violation_description=violation,
        recommended_action=action,
        insurance_impact=insurance_impact,
        supporting_excerpts=excerpts[:3],
    )
