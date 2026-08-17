"""
FloridaInspect Pipeline — root ADK agent coordinating the four inspection stages.

Uses SequentialAgent to run sub-agents in a fixed order:

  CaptureAgent → AnalyzeAgent → ReportAgent → AuditAgent

Each agent sees the full session history (previous agents' outputs) and
contributes its results to the session for the next agent to read.
SequentialAgent guarantees ordering without an LLM orchestrator — avoids the
transfer_to_agent problem where the first transfer is terminal.
"""

from google.adk.agents.sequential_agent import SequentialAgent

from agents.analyze_agent import analyze_agent
from agents.audit_agent import audit_agent
from agents.capture_agent import capture_agent
from agents.report_agent import report_agent


root_agent = SequentialAgent(
    name="floridainspect_pipeline",
    description=(
        "FloridaInspect sequential pipeline. Runs four specialist agents in order: "
        "CaptureAgent (photo → FindingDraft) → AnalyzeAgent (FL regulation RAG) → "
        "ReportAgent (professional narrative) → AuditAgent (quality gate). "
        "Returns a complete, audit-verified Florida home inspection report."
    ),
    sub_agents=[capture_agent, analyze_agent, report_agent, audit_agent],
)
