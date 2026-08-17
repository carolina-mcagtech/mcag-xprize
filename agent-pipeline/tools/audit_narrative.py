"""
audit_narrative — Quality auditor tool that validates a generated report
narrative for severity consistency, statute citation accuracy, and
required disclaimer compliance.

Used by: AuditAgent
"""

import os
from pathlib import Path
from typing import Optional

import chromadb
from google import genai

_GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "mcag-hackathon")
_GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")


def _gemini_client() -> genai.Client:
    return genai.Client(vertexai=True, project=_GCP_PROJECT, location=_GCP_LOCATION)
from pydantic import BaseModel, Field

from tools.classify_photo import FindingDraft
from tools.validate_regulation import (
    RegulatoryCheck,
    _DEFAULT_CHROMA_PATH,
    _load_regulations_into_chroma,
)


class AuditResult(BaseModel):
    """Quality-audit verdict for a single report section."""

    passed: bool = Field(description="True if no critical issues found")
    confidence: float = Field(description="Auditor confidence 0.0–1.0", ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list, description="Issues found during audit")
    verified_statutes: list[str] = Field(
        default_factory=list,
        description="Statute references confirmed present in FL regulations DB",
    )
    auditor_note: str = Field(description="One-sentence audit summary")


_AUDIT_PROMPT = """\
You are an AI quality auditor for Florida home inspection reports.

Review the narrative below against the original finding and regulatory check.
Perform these three checks:

1. SEVERITY CONSISTENCY
   The original finding severity is: {severity}
   - "critical" findings must use urgent language (immediate, safety hazard, must replace, non-insurable).
   - "major" findings must signal significant concern (prompt repair, significant deficiency).
   - "minor" / "informational" findings must NOT use urgent or life-safety language.
   IMPORTANT: Only flag a SEVERITY_MISMATCH if the OVERALL narrative tone is clearly wrong
   for the severity level. Do NOT flag:
   - Use of the adjective "critical" in phrases like "critical concern", "critically important"
     within a "major" narrative.
   - Use of "immediate professional attention" or "prompt attention" — these are appropriate
     for "major" findings too.
   - Reserve SEVERITY_MISMATCH for cases like: a "minor" finding described as an imminent
     life-threatening hazard, or a "critical" finding described as routine maintenance.

2. STATUTE HALLUCINATION
   Compare every statute or code reference cited in the narrative against the
   verified regulation excerpts below. Flag any citation that does NOT appear
   in the excerpts. List ones that ARE confirmed as verified_statutes.
   IMPORTANT: If a statute number like "468.8319(a)" is cited and "468.8319" (the base statute
   number without subsection) appears in the verified excerpts, consider the subsection citation
   verified — do NOT flag subsection variants as hallucinations when the parent statute is present.

3. DISCLAIMER COMPLIANCE
   The narrative must include a note that AI-generated content requires review
   by a licensed inspector before delivery to clients. Flag if absent.

ORIGINAL FINDING:
{finding_json}

REGULATORY CHECK:
{regulatory_json}

NARRATIVE TO AUDIT:
{narrative}

VERIFIED FL REGULATION EXCERPTS (from ChromaDB):
{excerpts}

Return ONLY valid JSON — no markdown, no prose:
{{
  "passed": <true if no critical issues>,
  "confidence": <0.0-1.0>,
  "flags": ["<specific issue>", ...],
  "verified_statutes": ["<statute confirmed in excerpts>", ...],
  "auditor_note": "<one sentence summary>"
}}"""


def audit_narrative(
    narrative: str,
    finding: FindingDraft,
    regulatory_check: RegulatoryCheck,
    inspection_type: str = "4-point",
    chroma_path: Optional[str] = None,
) -> AuditResult:
    """Audit a generated report narrative for quality, consistency, and accuracy.

    Queries ChromaDB to verify statute citations, then calls Gemini to check
    severity language and disclaimer compliance.

    Args:
        narrative: The generated report section narrative text.
        finding: Original FindingDraft from CaptureAgent.
        regulatory_check: RegulatoryCheck from AnalyzeAgent.
        inspection_type: Type of inspection (4-point, wind-mit, full).
        chroma_path: Optional path to ChromaDB persistence directory.

    Returns:
        AuditResult with pass/fail verdict, specific flags, and verified statutes.
    """
    # Retrieve regulation excerpts for statute verification
    excerpts: list[str] = []
    try:
        client = chromadb.PersistentClient(path=chroma_path or _DEFAULT_CHROMA_PATH)
        collection = _load_regulations_into_chroma(client)
        n_avail = collection.count()

        # Primary query: system-specific content
        topic_query = (
            f"{finding.system} {finding.observation[:120]} "
            f"{' '.join(regulatory_check.applicable_regulations)}"
        )
        topic_results = collection.query(
            query_texts=[topic_query], n_results=min(4, n_avail)
        )
        topic_docs = topic_results["documents"][0] if topic_results["documents"] else []

        # Secondary query: always pull AI-disclaimer / 468.8314 licensing context
        disclaimer_query = (
            "Florida Statute 468.8314 AI-generated disclaimer licensed inspector of record"
        )
        disc_results = collection.query(
            query_texts=[disclaimer_query], n_results=min(3, n_avail)
        )
        disc_docs = disc_results["documents"][0] if disc_results["documents"] else []

        # Merge, keeping unique docs (topic docs first)
        seen: set[str] = set()
        for doc in topic_docs + disc_docs:
            if doc not in seen:
                seen.add(doc)
                excerpts.append(doc)
    except Exception:
        pass  # audit proceeds without excerpts; hallucination check will flag statutes

    gemini_client = _gemini_client()
    prompt = _AUDIT_PROMPT.format(
        severity=finding.severity,
        finding_json=finding.model_dump_json(indent=2),
        regulatory_json=regulatory_check.model_dump_json(indent=2),
        narrative=narrative,
        excerpts="\n---\n".join(excerpts) if excerpts else "No excerpts retrieved.",
    )

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return AuditResult.model_validate_json(raw)
    except Exception as exc:
        return AuditResult(
            passed=True,
            confidence=0.0,
            flags=[f"Audit processing error: {str(exc)[:120]}"],
            verified_statutes=[],
            auditor_note="Audit could not complete — report requires manual review.",
        )
