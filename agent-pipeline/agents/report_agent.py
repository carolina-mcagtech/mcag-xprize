"""
ReportAgent — Third and final stage of the FloridaInspect pipeline.

Responsibilities:
- Receive FindingDraft + RegulatoryCheck pairs from AnalyzeAgent.
- Call generate_narrative (Gemini 1.5 Pro) for each finding pair.
- Assemble a FullReport with executive summary, all sections, and limitations.
- Output the report as structured JSON and/or formatted text.

The output of this agent is a professional home inspection report that meets
Florida Statute 468.8326 requirements: it describes conditions observed,
references applicable regulations, and includes specific corrective actions.
It is suitable for delivery to the homebuyer, seller, or insurance underwriter.
"""

import json
from datetime import date

from google.adk.agents import Agent

from tools.classify_photo import FindingDraft
from tools.generate_narrative import ReportSection, assemble_full_report, generate_narrative
from tools.validate_regulation import RegulatoryCheck


def _generate_section_tool(finding_dict: dict, regulatory_check_dict: dict) -> dict:
    """ADK-callable wrapper: generate a ReportSection for one finding/check pair.

    Args:
        finding_dict: FindingDraft as a dict.
        regulatory_check_dict: RegulatoryCheck as a dict.

    Returns:
        ReportSection as a dict.
    """
    try:
        finding = FindingDraft.model_validate(finding_dict)
        check = RegulatoryCheck.model_validate(regulatory_check_dict)
        section = generate_narrative(finding, check)
        return section.model_dump()
    except Exception as exc:
        return {
            "system": finding_dict.get("system", "Unknown").title(),
            "headline": "Report section generation failed",
            "narrative": (
                f"The following condition was observed: {finding_dict.get('observation', 'N/A')}. "
                f"Recommended action: {regulatory_check_dict.get('recommended_action', 'N/A')}. "
                f"Error during AI narrative generation: {exc}"
            ),
            "action_items": [regulatory_check_dict.get("recommended_action", "Manual review required.")],
            "severity_summary": "fair",
            "inspector_note": "Narrative generation failed — manual review required.",
            "error": str(exc),
        }


def _assemble_report_tool(
    sections: list[dict],
    property_address: str,
    inspection_date: str | None = None,
    inspector_name: str = "FloridaInspect AI Agent",
    inspector_license: str = "AI-ASSISTED REVIEW — Requires licensed inspector sign-off",
) -> dict:
    """ADK-callable wrapper: assemble all sections into a FullReport.

    Args:
        sections: List of ReportSection dicts from _generate_section_tool.
        property_address: Street address of the inspected property.
        inspection_date: ISO date string; defaults to today if None.
        inspector_name: Name of the inspector of record.
        inspector_license: FL home inspector license number.

    Returns:
        FullReport as a dict.
    """
    if not inspection_date:
        inspection_date = date.today().isoformat()

    validated_sections = [ReportSection.model_validate(s) for s in sections]

    report = assemble_full_report(
        sections=validated_sections,
        property_address=property_address,
        inspection_date=inspection_date,
        inspector_name=inspector_name,
        inspector_license=inspector_license,
    )
    return report.model_dump()


def _format_report_text_tool(report_dict: dict) -> str:
    """Format a FullReport dict as a human-readable text report.

    Args:
        report_dict: FullReport as a dict.

    Returns:
        Formatted plain-text report string.
    """
    lines: list[str] = []
    sep = "=" * 72

    lines.append(sep)
    lines.append("FLORIDA HOME INSPECTION REPORT")
    lines.append(sep)
    lines.append(f"Property: {report_dict.get('property_address', 'N/A')}")
    lines.append(f"Date:     {report_dict.get('inspection_date', 'N/A')}")
    lines.append(f"Inspector:{report_dict.get('inspector_name', 'N/A')}")
    lines.append(f"License:  {report_dict.get('inspector_license', 'N/A')}")
    lines.append("")
    lines.append("EXECUTIVE SUMMARY")
    lines.append("-" * 40)
    lines.append(report_dict.get("executive_summary", ""))
    lines.append("")

    for section in report_dict.get("sections", []):
        lines.append(sep)
        lines.append(f"SYSTEM: {section.get('system', '').upper()}")
        lines.append(f"Condition: {section.get('severity_summary', '').upper()}")
        lines.append(f"Headline: {section.get('headline', '')}")
        lines.append("")
        lines.append(section.get("narrative", ""))
        lines.append("")

        actions = section.get("action_items", [])
        if actions:
            lines.append("Recommended Actions:")
            for action in actions:
                lines.append(f"  • {action}")
        lines.append("")

        note = section.get("inspector_note")
        if note:
            lines.append(f"Inspector Note: {note}")
        lines.append("")

    lines.append(sep)
    lines.append("LIMITATIONS OF INSPECTION")
    lines.append("-" * 40)
    for limitation in report_dict.get("limitations", []):
        lines.append(f"  • {limitation}")
    lines.append("")
    lines.append(report_dict.get("footer", ""))
    lines.append(sep)

    return "\n".join(lines)


report_agent = Agent(
    name="report_agent",
    model="gemini-2.5-flash",
    description=(
        "Generates professional Florida home inspection report narratives from validated findings. "
        "Uses Gemini 2.0 Flash to write clear, regulation-compliant report sections per Florida "
        "Statute 468.8326. Assembles a FullReport with executive summary, system sections, "
        "corrective actions, and required disclaimers suitable for client delivery or "
        "insurance underwriter submission."
    ),
    instruction=(
        "You are the ReportAgent for FloridaInspect, a Florida home inspection AI system. "
        "Your role is to produce professional written inspection report content. "
        "\n\n"
        "The FindingDraft list (from CaptureAgent) and RegulatoryCheck list (from AnalyzeAgent) "
        "are in the conversation history above. Read them from the previous agents' responses. "
        "The property_address and inspection_date are in the original user JSON message.\n\n"
        "Steps:\n"
        "1. Read FindingDraft list from CaptureAgent's response and RegulatoryCheck list from AnalyzeAgent's response.\n"
        "2. Call generate_section_tool for each finding/check pair to create ReportSection objects. "
        "3. Once all sections are generated, call assemble_report_tool with the property address "
        "   and inspection date to create the FullReport. "
        "4. Call format_report_text_tool to produce the human-readable report text. "
        "5. Output the formatted report text as your final response so AuditAgent can verify it. "
        "\n\n"
        "Report writing standards (per FL Statute 468.8326): "
        "- Use objective, professional language — describe conditions, not causes. "
        "- Reference specific Florida statutes and building codes when applicable. "
        "- Clearly distinguish observed conditions from suspected conditions. "
        "- Every critical or major finding must have at least one specific corrective action. "
        "- Include the standard inspection limitations disclaimer. "
        "- Flag that AI-generated content requires licensed inspector review and sign-off."
    ),
    tools=[_generate_section_tool, _assemble_report_tool, _format_report_text_tool],
)
