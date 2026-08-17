"""
generate_narrative — Report generation tool that converts validated findings
into professionally worded report sections suitable for a Florida home
inspection report delivered to a client or insurance underwriter.

Used by: ReportAgent
"""

import os
import time
from typing import Optional

from google import genai

_GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "mcag-hackathon")
_GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")


def _gemini_client() -> genai.Client:
    return genai.Client(vertexai=True, project=_GCP_PROJECT, location=_GCP_LOCATION)
from pydantic import BaseModel, Field

from tools.audit_narrative import AuditResult
from tools.classify_photo import FindingDraft
from tools.validate_regulation import RegulatoryCheck


class ReportSection(BaseModel):
    """A single section of the inspection report for one system."""

    system: str = Field(description="Inspection system this section covers")
    headline: str = Field(description="Short headline summarising the system's condition")
    narrative: str = Field(description="Full professional narrative (2-4 paragraphs)")
    action_items: list[str] = Field(description="Bulleted list of recommended actions")
    severity_summary: str = Field(description="Overall severity: satisfactory, fair, poor, critical")
    inspector_note: Optional[str] = Field(
        default=None,
        description="Optional disclaimer or limitation note (e.g. 'Area inaccessible')",
    )
    audit_result: Optional[AuditResult] = Field(
        default=None,
        description="Quality audit result from AuditAgent (severity, statutes, disclaimers)",
    )


class FullReport(BaseModel):
    """Complete inspection report for the property."""

    property_address: str
    inspection_date: str
    inspector_name: str
    inspector_license: str
    executive_summary: str
    sections: list[ReportSection]
    limitations: list[str]
    footer: str
    audit_summary: Optional[dict] = Field(
        default=None,
        description="Aggregate audit stats: total, passed, flagged, overall_passed",
    )


_NARRATIVE_PROMPT = """You are a licensed Florida home inspector writing a professional inspection report
for a residential property. Your report language must be:
- Clear and objective, using plain language a homeowner can understand.
- Compliant with Florida Statute 468.8326 (written report requirements).
- Accurate to the specific findings and regulatory references provided.
- Free of legal conclusions; you describe conditions, not determine liability.

Given the following inspection finding and regulatory check, write a ReportSection JSON object:

FINDING:
{finding_json}

REGULATORY CHECK:
{regulatory_json}

Return a JSON object with these fields:
{{
  "system": "<system name>",
  "headline": "<one short sentence summarising overall condition>",
  "narrative": "<2-4 paragraphs describing what was observed, why it matters, and applicable Florida standards>",
  "action_items": ["<specific action 1>", "<specific action 2>"],
  "severity_summary": "<satisfactory|fair|poor|critical>",
  "inspector_note": "<optional limitation or disclaimer, or null>"
}}

End the narrative with this exact sentence: 'This narrative was AI-generated and requires review and approval by the licensed inspector of record per Florida Statute 468.8314.'

Return ONLY valid JSON."""

_SUMMARY_PROMPT = """You are a licensed Florida home inspector. Based on the following list of report
sections, write a concise executive summary (3-5 sentences) for the full home inspection report.
Mention the most significant findings and overall property condition.

SECTIONS:
{sections_json}

Return only the plain text executive summary, no JSON, no headers."""


def generate_narrative(
    finding: FindingDraft,
    regulatory_check: RegulatoryCheck,
) -> ReportSection:
    """Generate a professional report section narrative for a single finding.

    Calls Gemini to convert raw FindingDraft + RegulatoryCheck into polished
    report language appropriate for Florida home inspection reports.

    Args:
        finding: Structured finding from classify_photo.
        regulatory_check: Regulatory validation from validate_regulation.

    Returns:
        ReportSection with professional narrative text and action items.
    """
    client = _gemini_client()

    prompt = _NARRATIVE_PROMPT.format(
        finding_json=finding.model_dump_json(indent=2),
        regulatory_json=regulatory_check.model_dump_json(indent=2),
    )

    last_error = ""
    for attempt in range(3):
        try:
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            raw = response.text.strip()

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            return ReportSection.model_validate_json(raw)
        except Exception as e:
            last_error = str(e)
            is_retryable = any(code in last_error for code in ("429", "503", "502", "500"))
            if is_retryable and attempt < 2:
                time.sleep(60 * (attempt + 1))
            else:
                break

    return _fallback_section(finding, regulatory_check, error=last_error)


def generate_executive_summary(sections: list[ReportSection]) -> str:
    """Generate an executive summary from all report sections.

    Args:
        sections: List of completed ReportSection objects.

    Returns:
        Plain-text executive summary string.
    """
    if not sections:
        return "No inspection sections were generated. Please review individual findings above."

    try:
        client = _gemini_client()

        import json
        sections_data = [s.model_dump() for s in sections]

        prompt = _SUMMARY_PROMPT.format(sections_json=json.dumps(sections_data, indent=2))
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return response.text.strip()
    except Exception:
        return _fallback_executive_summary(sections)


def assemble_full_report(
    sections: list[ReportSection],
    property_address: str,
    inspection_date: str,
    inspector_name: str = "FloridaInspect AI Agent",
    inspector_license: str = "AI-ASSISTED REVIEW — Requires licensed inspector sign-off",
) -> FullReport:
    """Assemble all sections into a FullReport object.

    Args:
        sections: List of ReportSection objects from generate_narrative calls.
        property_address: Street address of the inspected property.
        inspection_date: Date of the inspection (ISO format recommended).
        inspector_name: Name of the inspector of record.
        inspector_license: Florida home inspector license number.

    Returns:
        FullReport ready for serialisation to JSON or formatted output.
    """
    exec_summary = generate_executive_summary(sections)

    limitations = [
        "This inspection is a visual, non-invasive examination of accessible areas only.",
        "Areas not accessible (locked rooms, covered components) were not inspected.",
        "Wood-destroying organism (WDO) inspection requires a separate licensed pest control operator.",
        "Sinkhole determination requires a licensed geotechnical engineer.",
        "Mold testing, if warranted, requires a separate licensed mold assessor.",
        "This report does not constitute a warranty or guarantee of any system or component.",
        "AI-generated narratives must be reviewed and approved by the licensed inspector of record.",
    ]

    # Compute aggregate audit summary from sections that were audited
    audited = [s.audit_result for s in sections if s.audit_result is not None]
    audit_summary: Optional[dict] = None
    if audited:
        passed = sum(1 for r in audited if r.passed)
        audit_summary = {
            "total": len(audited),
            "passed": passed,
            "flagged": len(audited) - passed,
            "overall_passed": (len(audited) - passed) == 0,
        }

    return FullReport(
        property_address=property_address,
        inspection_date=inspection_date,
        inspector_name=inspector_name,
        inspector_license=inspector_license,
        executive_summary=exec_summary,
        sections=sections,
        limitations=limitations,
        footer=(
            "This report was prepared in accordance with Florida Statute 468 Part XV and the "
            "Florida Standards of Practice. For questions contact the inspector of record. "
            "FloridaInspect Agent — AI-assisted reporting system by MCAG Technologies."
        ),
        audit_summary=audit_summary,
    )


def _fallback_section(finding: FindingDraft, check: RegulatoryCheck, error: str = "") -> ReportSection:
    """Build a minimal ReportSection when Gemini narrative generation fails."""
    severity_map = {"critical": "critical", "major": "poor", "minor": "fair", "informational": "satisfactory"}
    note = "Narrative generated in fallback mode — manual review required."
    if error:
        note += f" (Gemini error: {error[:120]})"
    return ReportSection(
        system=finding.system.title(),
        headline=finding.photo_description,
        narrative=(
            f"During the inspection of the {finding.system} system at {finding.location}, "
            f"the following was observed: {finding.observation} "
            f"This condition is rated as {finding.severity}. "
            f"{check.recommended_action}"
        ),
        action_items=[check.recommended_action],
        severity_summary=severity_map.get(finding.severity, "fair"),
        inspector_note=note,
    )


def _fallback_executive_summary(sections: list[ReportSection]) -> str:
    """Build a plain-text executive summary without calling Gemini."""
    critical = [s for s in sections if s.severity_summary == "critical"]
    poor = [s for s in sections if s.severity_summary == "poor"]
    systems = ", ".join(s.system for s in sections)

    summary = (
        f"This inspection evaluated the following systems: {systems}. "
    )
    if critical:
        names = ", ".join(s.system for s in critical)
        summary += (
            f"Critical deficiencies were identified in the {names} system(s) requiring "
            f"immediate attention and likely affecting insurance eligibility. "
        )
    if poor:
        names = ", ".join(s.system for s in poor)
        summary += f"The {names} system(s) are in poor condition and require prompt repair. "
    if not critical and not poor:
        summary += "No critical or major deficiencies were identified at the time of inspection. "
    summary += (
        "All findings should be reviewed by a licensed Florida home inspector before "
        "delivery to clients or insurance underwriters."
    )
    return summary
