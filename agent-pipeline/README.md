# InspectIQ Agent Pipeline

Multi-agent pipeline (Google ADK SequentialAgent + Gemini via Vertex AI):
Capture → Analyze → Report → Audit. This module is part of the pre-existing
work declared in the root README disclosure (developed prior to this
hackathon window). During the hackathon it was deployed to production on
Google Cloud Run (project mcag-xprize) and integrated with the business
operations layer: every execution is recorded in the auditable
agent_executions log (see apps/api/app/modules/agent_log/).

- agents/: capture_agent, analyze_agent, report_agent, audit_agent
- orchestrator/: ADK SequentialAgent wiring
- mcp_server/: FastMCP server exposing RAG over FL Statute 468, DBPR,
  Wind Mitigation and Citizens HO-800 (ChromaDB; vector store built from
  source documents, not committed)
- tools/: shared agent tools
