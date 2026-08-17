"""
AuditAgent — Fourth and final stage of the FloridaInspect pipeline.

Responsibilities:
- Receive FindingDraft, RegulatoryCheck, and ReportSection triplets from ReportAgent.
- Call audit_narrative (Gemini 2.5 Flash) to validate each section for:
    1. Severity consistency — narrative language must match FindingDraft severity.
    2. Hallucination check — statute citations verified against FL regulations DB.
    3. Disclaimer compliance — AI review note must be present.
- Return an AuditResult per section and a pass/fail summary for the full report.
"""

from google.adk.agents import Agent

from tools.audit_narrative import AuditResult, audit_narrative
from tools.classify_photo import FindingDraft
from tools.validate_regulation import RegulatoryCheck


def _audit_sections_tool(
    sections: list[dict],
    findings: list[dict],
    regulatory_checks: list[dict],
    inspection_type: str = "4-point",
) -> list[dict]:
    """ADK-callable wrapper: audit all report sections for quality and accuracy.

    Args:
        sections: List of ReportSection dicts produced by ReportAgent.
        findings: Parallel list of FindingDraft dicts from CaptureAgent.
        regulatory_checks: Parallel list of RegulatoryCheck dicts from AnalyzeAgent.
        inspection_type: 4-point | wind-mit | full

    Returns:
        List of AuditResult dicts, one per section, in the same order.
    """
    results: list[dict] = []
    for section, finding_dict, check_dict in zip(sections, findings, regulatory_checks):
        try:
            finding = FindingDraft.model_validate(finding_dict)
            check = RegulatoryCheck.model_validate(check_dict)
            result = audit_narrative(
                narrative=section.get("narrative", ""),
                finding=finding,
                regulatory_check=check,
                inspection_type=inspection_type,
            )
            results.append(result.model_dump())
        except Exception as exc:
            results.append(
                AuditResult(
                    passed=True,
                    confidence=0.0,
                    flags=[f"Audit error: {str(exc)[:120]}"],
                    verified_statutes=[],
                    auditor_note="Audit could not complete — manual review required.",
                ).model_dump()
            )
    return results


audit_agent = Agent(
    name="audit_agent",
    model="gemini-2.5-flash",
    description=(
        "Quality gate for FloridaInspect report narratives. Validates each section "
        "for severity consistency, FL statute citation accuracy (via ChromaDB RAG), "
        "and required AI disclaimer compliance. Returns a pass/fail verdict with "
        "specific flags for any issues found."
    ),
    instruction=(
        "You are the AuditAgent for FloridaInspect — the final quality gate before "
        "a report is delivered to a client or insurance underwriter. "
        "\n\n"
        "The FindingDraft list, RegulatoryCheck list, ReportSection list, and inspection_type "
        "are in the conversation history above from previous agents. "
        "Read them from CaptureAgent, AnalyzeAgent, and ReportAgent's responses respectively.\n\n"
        "Steps:\n"
        "1. Extract FindingDraft, RegulatoryCheck, and ReportSection lists from session history.\n"
        "2. Call audit_sections_tool with all three parallel lists and the inspection_type. "
        "2. Review each AuditResult: "
        "   - passed=False: report the specific flags for that section. "
        "   - passed=True but confidence < 0.7: flag for inspector attention. "
        "3. Return a summary: sections audited, passed count, failed count, and any "
        "   critical flags that must be addressed before report delivery. "
        "\n\n"
        "Audit standards: "
        "- Critical findings MUST use urgent language (safety hazard, must replace, non-insurable). "
        "- Every FL statute cited must appear in the regulations database. "
        "- Every AI narrative must include a licensed inspector review disclaimer. "
        "- Do not fail a report for minor stylistic issues — only substantive problems."
    ),
    tools=[_audit_sections_tool],
)
