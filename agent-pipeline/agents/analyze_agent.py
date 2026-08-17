"""
AnalyzeAgent — Second stage of the FloridaInspect pipeline.

Responsibilities:
- Receive FindingDraft objects from CaptureAgent.
- Use the Florida Regulations MCP tool to query relevant FL statutes and codes.
- Apply Florida-specific regulatory knowledge to produce RegulatoryCheck results.
- Flag findings that are insurance-blocking or require licensed specialist referral.

MCP integration: queries ChromaDB via google.adk.tools.mcp_tool.McpToolset with
stdio transport — no persistent process, no port, no OOM risk.
"""

import sys
from pathlib import Path

from mcp import StdioServerParameters
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

_SERVER_SCRIPT = str(Path(__file__).parent.parent / "mcp_server" / "florida_regulations_server.py")

_mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[_SERVER_SCRIPT],
        ),
        timeout=60.0,
    ),
)


def _flag_critical_findings_tool(regulatory_checks: list[dict]) -> dict:
    """Identify insurance-blocking and safety-critical issues requiring immediate attention.

    Args:
        regulatory_checks: List of RegulatoryCheck dicts produced by the agent.

    Returns:
        Summary dict with counts and lists of critical, major, and referral findings.
    """
    critical: list[dict] = []
    major: list[dict] = []
    referrals: list[str] = []

    referral_keywords = [
        "geotechnical engineer", "sinkhole", "mold remediator", "wdo", "pest control",
        "structural engineer", "licensed electrician", "licensed plumber",
    ]

    for check in regulatory_checks:
        if check.get("insurance_impact") == "critical":
            critical.append(check)
        elif check.get("insurance_impact") in ("major", "moderate"):
            major.append(check)

        action_lower = check.get("recommended_action", "").lower()
        for kw in referral_keywords:
            if kw in action_lower and kw not in referrals:
                referrals.append(kw.replace("licensed ", "").title())

    return {
        "critical_count": len(critical),
        "major_count": len(major),
        "critical_findings": critical,
        "major_findings": major,
        "specialist_referrals_required": list(set(referrals)),
        "insurance_eligible": len(critical) == 0,
    }


analyze_agent = Agent(
    name="analyze_agent",
    model="gemini-2.5-flash",
    description=(
        "Validates inspection findings against Florida home inspection regulations using "
        "the Florida Regulations MCP tool (ChromaDB RAG). Applies knowledge of FL Statute 468, "
        "4-Point inspection requirements, Wind Mitigation criteria, and common Florida-specific "
        "deficiencies (polybutylene pipe, Federal Pacific/Zinsco panels, Chinese drywall). "
        "Returns regulatory verdicts, violation descriptions, and recommended actions."
    ),
    instruction=(
        "You are the AnalyzeAgent for FloridaInspect, a Florida home inspection AI system. "
        "Your role is to validate each inspection finding against Florida building codes and "
        "insurance requirements using the query_florida_regulations MCP tool.\n\n"
        "The FindingDraft list produced by CaptureAgent is in the conversation history above. "
        "Read it from CaptureAgent's most recent response.\n\n"
        "Steps:\n"
        "1. For EACH finding, call query_florida_regulations with a descriptive query combining "
        "   the finding's system, observation, and severity (e.g. 'Zinsco electrical panel "
        "   insurance eligibility Citizens 4-point critical'). Use n_results=4.\n"
        "2. Based on the returned regulation excerpts, determine for each finding:\n"
        "   - applicable_regulations: list of specific statutes cited in the excerpts\n"
        "   - compliant: false if the excerpts indicate a violation, true if compliant\n"
        "   - violation_description: what specific rule is violated (or null if compliant)\n"
        "   - recommended_action: specific remediation step\n"
        "   - insurance_impact: 'critical' if insurance-blocking, 'moderate' if major concern, "
        "     'minor' if minor deficiency, 'none' if no insurance impact\n"
        "   - supporting_excerpts: list of the relevant excerpt strings returned by the tool\n"
        "3. Assemble all per-finding results as a list of RegulatoryCheck dicts.\n"
        "4. Call flag_critical_findings_tool with the complete list to summarise critical items.\n"
        "5. Return both the full regulatory_checks list and the critical findings summary.\n\n"
        "Key Florida-specific rules to enforce:\n"
        "- Federal Pacific / Zinsco panels: non-insurable, insurance_impact=critical.\n"
        "- Polybutylene supply piping: non-insurable, insurance_impact=critical.\n"
        "- Aluminum branch wiring without COPALUM/AlumiConn: insurance_impact=critical.\n"
        "- Roof age 20+ years or active leaks: insurance_impact=critical.\n"
        "- HVAC/water heater 15+ years: insurance_impact=moderate.\n"
        "- Sinkhole indicators and mold: insurance_impact=critical, refer to specialists."
    ),
    tools=[_mcp_toolset, _flag_critical_findings_tool],
)
