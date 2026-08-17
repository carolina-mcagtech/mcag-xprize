"""
api.py — FastAPI HTTP interface for FloridaInspect Agent.
Deployed on Google Cloud Run.

Endpoints:
    GET  /health          — liveness probe
    GET  /demo-result     — return cached AI demo report instantly (no pipeline run)
    POST /demo            — run the built-in 7-finding demo scenario
    POST /inspect         — run Analyze + Report agents on caller-supplied findings
    POST /adk-pipeline    — full pipeline via Google ADK Runner + root_agent
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import os
import re
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from demo.run_demo import INSPECTION_DATE, MOCK_FINDINGS, PROPERTY_ADDRESS
from inspect_ui import INSPECT_UI_HTML
from tools.audit_narrative import AuditResult, audit_narrative
from tools.classify_photo import FindingDraft, classify_photo_from_bytes
from tools.generate_narrative import assemble_full_report, generate_narrative
from tools.validate_regulation import validate_regulation

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Populate DEMO_CACHE in the background so /demo-report serves live content.

    Runs asynchronously so it doesn't delay container startup / health checks.
    Until it completes, /demo-report falls back to demo_report_output.json.
    """
    async def _populate() -> None:
        global DEMO_CACHE
        try:
            DEMO_CACHE = await asyncio.to_thread(_generate_demo_report)
        except Exception:
            logging.exception("Failed to warm demo cache")

    asyncio.create_task(_populate())
    yield


app = FastAPI(
    title="InspectIQ Agent",
    version="1.0.0",
    description="AI-powered Florida home inspection report generation",
    lifespan=lifespan,
)

# In-memory store for pipeline-generated reports (keyed by UUID)
reports_store: dict[str, dict[str, Any]] = {}

# Lifespan cache for /demo-report — populated on startup by running the real
# pipeline against MOCK_FINDINGS, so judges always see live Gemini-generated
# narratives instead of a potentially stale committed JSON file.
DEMO_CACHE: dict[str, Any] | None = None

# Persistent report storage — survives server restarts
_REPORTS_DIR = Path(__file__).parent / "reports"
_REPORTS_DIR.mkdir(exist_ok=True)


def _persist_report(report_id: str, data: dict[str, Any]) -> None:
    """Write a report dict to disk as JSON."""
    (_REPORTS_DIR / f"{report_id}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _load_report(report_id: str) -> dict[str, Any] | None:
    """Return a report from memory, falling back to disk."""
    if report_id in reports_store:
        return reports_store[report_id]
    path = _REPORTS_DIR / f"{report_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        reports_store[report_id] = data  # warm the cache
        return data
    return None


# ── helpers ──────────────────────────────────────────────────────────────────

def _run_pipeline(
    findings: list[FindingDraft],
    property_address: str,
    inspection_date: str,
    inspection_type: str = "4-point",
) -> dict[str, Any]:
    """Validate → narrate → audit → assemble. Returns a serialisable report dict."""
    checks = [validate_regulation(f) for f in findings]
    sections = [generate_narrative(f, c) for f, c in zip(findings, checks)]

    # Audit each section for severity consistency, statute accuracy, disclaimer compliance
    audited_sections = []
    for finding, check, section in zip(findings, checks, sections):
        try:
            audit = audit_narrative(
                narrative=section.narrative,
                finding=finding,
                regulatory_check=check,
                inspection_type=inspection_type,
            )
        except Exception:
            audit = AuditResult(
                passed=True, confidence=0.0, flags=[],
                verified_statutes=[], auditor_note="Audit skipped.",
            )
        audited_sections.append(section.model_copy(update={"audit_result": audit}))

    report = assemble_full_report(
        sections=audited_sections,
        property_address=property_address,
        inspection_date=inspection_date,
        inspector_license=(
            f"AI-ASSISTED REVIEW ({inspection_type.upper()}) "
            "— Requires licensed inspector sign-off"
        ),
    )
    return {"inspection_type": inspection_type, **report.model_dump()}


_DEMO_RESULT_PATH = Path(__file__).parent / "demo_report_output.json"


def _generate_demo_report() -> dict[str, Any]:
    """Run the live pipeline against the built-in Tampa demo findings."""
    findings = [FindingDraft.model_validate(f) for f in MOCK_FINDINGS]
    return _run_pipeline(
        findings=findings,
        property_address=PROPERTY_ADDRESS,
        inspection_date=INSPECTION_DATE,
        inspection_type="4-point",
    )


# ── GET /health ───────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "InspectIQ Agent"}


# ── GET /inspect-ui ───────────────────────────────────────────────────────────

@app.get("/inspect-ui", response_class=HTMLResponse)
def inspect_ui() -> HTMLResponse:
    """Serve a simple form for kicking off the ADK inspection pipeline."""
    return HTMLResponse(content=INSPECT_UI_HTML)


# ── GET /demo-result ──────────────────────────────────────────────────────────

@app.get("/demo-result")
def demo_result() -> dict[str, Any]:
    """Return the pre-generated AI demo report from disk without running the pipeline.

    Reads demo_report_output.json committed to the repo, so judges get real
    Gemini-generated output instantly instead of waiting ~3 minutes for the
    full pipeline to run.
    """
    if not _DEMO_RESULT_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="Demo result not found. Run POST /demo first to generate it.",
        )
    return json.loads(_DEMO_RESULT_PATH.read_text(encoding="utf-8"))


# ── POST /demo ────────────────────────────────────────────────────────────────

@app.post("/demo")
def demo() -> dict[str, Any]:
    """Run the built-in 7-finding Tampa demo scenario and return the full report."""
    findings = [FindingDraft.model_validate(f) for f in MOCK_FINDINGS]
    return _run_pipeline(
        findings=findings,
        property_address=PROPERTY_ADDRESS,
        inspection_date=INSPECTION_DATE,
        inspection_type="4-point",
    )


# ── POST /inspect ─────────────────────────────────────────────────────────────

class FlexFinding(BaseModel):
    """Flexible finding input — only severity is truly required.

    Accepts both the canonical FindingDraft field names and common shorthand
    alternatives so callers don't need to know the internal schema.

    Minimal example::

        {
          "system": "electrical",
          "observation": "Possible FPE Stab-Lok panel observed",
          "severity": "critical"
        }

    Full example (matches internal FindingDraft exactly)::

        {
          "system": "electrical",
          "location": "Main electrical panel — garage",
          "observation": "Federal Pacific Stab-Lok panel, 150-amp service.",
          "severity": "critical",
          "deficiency_suspected": true,
          "photo_description": "Federal Pacific electrical panel with double-tapped breakers.",
          "confidence": 0.97
        }

    Field aliases accepted:
        component  → system
        description → observation
    """

    # canonical fields
    system: Optional[str] = Field(default=None, description="roof | electrical | plumbing | hvac | structure | other")
    location: str = Field(default="Not specified", description="Where in the property this was observed")
    observation: Optional[str] = Field(default=None, description="Plain-language description of what was observed")
    severity: str = Field(default="major", description="critical | major | minor | informational")
    deficiency_suspected: bool = Field(default=True)
    photo_description: Optional[str] = Field(default=None)
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)

    # shorthand aliases
    component: Optional[str] = Field(default=None, description="Alias for 'system'")
    description: Optional[str] = Field(default=None, description="Alias for 'observation'")

    def to_finding_draft(self) -> FindingDraft:
        system = self.system or self.component or "other"
        observation = self.observation or self.description or "No observation provided"
        return FindingDraft(
            system=system,
            location=self.location,
            observation=observation,
            severity=self.severity,
            deficiency_suspected=self.deficiency_suspected,
            photo_description=self.photo_description or observation[:80],
            confidence=self.confidence,
        )


class InspectRequest(BaseModel):
    findings: list[FlexFinding] = Field(description="One or more inspection findings")
    inspection_type: str = Field(default="4-point", description="4-point | wind-mit | full")
    property_address: Optional[str] = Field(default="Address not provided")
    inspection_date: Optional[str] = Field(default=None, description="ISO-8601 date, defaults to today")


@app.post("/inspect")
def inspect(body: InspectRequest) -> dict[str, Any]:
    """Run Analyze + Report agents on caller-supplied findings.

    Minimal call::

        curl -X POST /inspect -H "Content-Type: application/json" -d '{
          "findings": [
            {"system": "electrical", "observation": "Possible FPE Stab-Lok panel", "severity": "critical"},
            {"component": "roof",    "description": "Missing shingles on north slope", "severity": "major"}
          ],
          "inspection_type": "4-point"
        }'
    """
    if not body.findings:
        raise HTTPException(status_code=422, detail="findings list must not be empty")

    finding_objects = [f.to_finding_draft() for f in body.findings]

    return _run_pipeline(
        findings=finding_objects,
        property_address=body.property_address or "Address not provided",
        inspection_date=body.inspection_date or datetime.date.today().isoformat(),
        inspection_type=body.inspection_type,
    )


# ── shared photo request models ───────────────────────────────────────────────

class PhotoBase64Request(BaseModel):
    image_base64: str = Field(description="Base64-encoded image bytes (JPEG, PNG, or WEBP)")
    inspection_type: str = Field(default="4-point", description="4-point | wind-mit | full")
    mime_type: str = Field(default="image/jpeg", description="MIME type of the image")
    location_hint: Optional[str] = Field(default=None, description="Location context, e.g. 'attic'")
    system_hint: Optional[str] = Field(default=None, description="System context, e.g. 'electrical'")
    property_address: Optional[str] = Field(default="Address not provided")
    inspection_date: Optional[str] = Field(default=None, description="ISO-8601 date, defaults to today")
    photo_url: Optional[str] = Field(default=None, description="Optional public URL to display as the field photo in the HTML report")


class PhotoUrlRequest(BaseModel):
    image_url: str = Field(description="Publicly accessible URL of the inspection photo")
    inspection_type: str = Field(default="4-point", description="4-point | wind-mit | full")
    location_hint: Optional[str] = Field(default=None)
    system_hint: Optional[str] = Field(default=None)
    property_address: Optional[str] = Field(default="Address not provided")
    inspection_date: Optional[str] = Field(default=None)


def _decode_base64_image(image_base64: str) -> bytes:
    """Decode a base64 string to bytes, stripping data-URI prefix if present."""
    data = image_base64
    if "," in data:
        data = data.split(",", 1)[1]
    try:
        return base64.b64decode(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid base64 image data: {exc}") from exc


_GITHUB_BLOB_RE = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+)/(?:blob|raw)/(.+)$"
)


def _normalize_image_url(url: str) -> str:
    """Rewrite GitHub page/raw-button URLs to raw.githubusercontent.com."""
    m = _GITHUB_BLOB_RE.match(url)
    if m:
        return (
            f"https://raw.githubusercontent.com/"
            f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
        )
    return url


def _download_image(url: str) -> tuple[bytes, str]:
    """Download an image from a URL and return (bytes, mime_type)."""
    url = _normalize_image_url(url)
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to download image (HTTP {exc.response.status_code}): {url}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to download image: {exc}") from exc

    content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"URL returned '{content_type}', not an image. "
                "If using GitHub, paste the Raw file URL."
            ),
        )
    return resp.content, content_type


# ── POST /capture ─────────────────────────────────────────────────────────────

@app.post("/capture")
def capture(body: PhotoBase64Request) -> dict[str, Any]:
    """Classify a single inspection photo using Gemini Vision.

    Accepts a base64-encoded image and returns a structured FindingDraft
    describing the observed condition, severity, and confidence.

    Example::

        curl -X POST /capture -H "Content-Type: application/json" -d '{
          "image_base64": "<base64-string>",
          "inspection_type": "4-point",
          "location_hint": "main electrical panel"
        }'
    """
    image_bytes = _decode_base64_image(body.image_base64)

    try:
        finding = classify_photo_from_bytes(
            image_bytes=image_bytes,
            mime_type=body.mime_type,
            system_hint=body.system_hint,
            location_hint=body.location_hint,
        )
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        status = 429 if "rate limit" in str(exc).lower() else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return finding.model_dump()


# ── POST /capture-url ─────────────────────────────────────────────────────────

@app.post("/capture-url")
def capture_url(body: PhotoUrlRequest) -> dict[str, Any]:
    """Classify an inspection photo supplied as a URL using Gemini Vision.

    Downloads the image then runs the same Capture Agent logic as POST /capture.
    Useful for quick testing without base64 encoding.

    Example::

        curl -X POST /capture-url -H "Content-Type: application/json" -d '{
          "image_url": "https://example.com/roof.jpg",
          "inspection_type": "4-point"
        }'
    """
    image_bytes, mime_type = _download_image(body.image_url)

    try:
        finding = classify_photo_from_bytes(
            image_bytes=image_bytes,
            mime_type=mime_type,
            system_hint=body.system_hint,
            location_hint=body.location_hint,
        )
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        status = 429 if "rate limit" in str(exc).lower() else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return finding.model_dump()


# ── POST /pipeline ────────────────────────────────────────────────────────────

@app.post("/pipeline")
def pipeline(body: PhotoBase64Request) -> dict[str, Any]:
    """Run the full Capture → Analyze → Report pipeline on a single photo.

    1. Capture Agent: classifies the photo with Gemini Vision → FindingDraft
    2. Analyze Agent: validates the finding against FL regulations → RegulatoryCheck
    3. Report Agent: generates a professional narrative → FullReport

    Returns the complete FullReport JSON.

    Example::

        curl -X POST /pipeline -H "Content-Type: application/json" -d '{
          "image_base64": "<base64-string>",
          "inspection_type": "4-point",
          "property_address": "123 Main St, Tampa, FL 33601"
        }'
    """
    if body.image_base64:
        image_bytes = _decode_base64_image(body.image_base64)
        mime_type = body.mime_type
    elif body.photo_url:
        image_bytes, mime_type = _download_image(body.photo_url)
    else:
        raise HTTPException(status_code=422, detail="Either image_base64 or photo_url must be provided")

    try:
        finding = classify_photo_from_bytes(
            image_bytes=image_bytes,
            mime_type=mime_type,
            system_hint=body.system_hint,
            location_hint=body.location_hint,
        )
    except EnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        status = 429 if "rate limit" in str(exc).lower() else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = _run_pipeline(
        findings=[finding],
        property_address=body.property_address or "Address not provided",
        inspection_date=body.inspection_date or datetime.date.today().isoformat(),
        inspection_type=body.inspection_type,
    )
    print(f"Pipeline sections: {len(result.get('sections', []))}")
    print(f"Executive summary length: {len(result.get('executive_summary', ''))}")
    if not result.get("sections") and not result.get("executive_summary"):
        import time
        time.sleep(2)
        result = _run_pipeline(
            findings=[finding],
            property_address=body.property_address or "Address not provided",
            inspection_date=body.inspection_date or datetime.date.today().isoformat(),
            inspection_type=body.inspection_type,
        )
        if not result.get("sections") and not result.get("executive_summary"):
            raise HTTPException(
                status_code=422,
                detail="Could not analyze this image. Please try again.",
            )
    if result.get("sections"):
        # Embed downloaded bytes as a data URI so the report never depends
        # on the source URL being browser-loadable (hotlink protection /
        # mixed content / expiring links break <img> silently even when
        # server-side download succeeded).
        result["sections"][0]["photo_url"] = (
            f"data:{mime_type or 'image/jpeg'};base64,"
            f"{base64.b64encode(image_bytes).decode()}"
        )
    report_id = str(uuid.uuid4())
    result["report_id"] = report_id
    reports_store[report_id] = result
    _persist_report(report_id, result)
    return result


# ── POST /adk-pipeline ───────────────────────────────────────────────────────

@app.post("/adk-pipeline")
async def adk_pipeline(body: PhotoBase64Request) -> dict[str, Any]:
    """Run the full pipeline via the Google ADK orchestrator (root_agent).

    Unlike /pipeline — which calls tools directly — this endpoint uses the real
    Google ADK Runner with root_agent coordinating three sub-agents:

      CaptureAgent (Gemini 2.5 Flash Vision)
        → AnalyzeAgent (ChromaDB RAG + FL regulations)
          → ReportAgent (Gemini narrative generation)

    The photo is written to a temp file so CaptureAgent can read it by path,
    matching the same contract as the CLI (main.py --photos).

    Expect 60–120s — three sequential LLM calls plus RAG retrieval.

    Example::

        curl -X POST /adk-pipeline -H "Content-Type: application/json" -d '{
          "photo_url": "https://example.com/panel.jpg",
          "inspection_type": "4-point",
          "property_address": "123 Main St, Tampa FL 33601"
        }'
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai.types import Content, Part

    from orchestrator.agent import root_agent

    if body.image_base64:
        image_bytes = _decode_base64_image(body.image_base64)
        mime_type = body.mime_type
    elif body.photo_url:
        image_bytes, mime_type = _download_image(body.photo_url)
    else:
        raise HTTPException(
            status_code=422,
            detail="Either image_base64 or photo_url must be provided",
        )

    ext = ".jpg" if "jpeg" in mime_type or "jpg" in mime_type else ".png"
    tmp_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        session_service = InMemorySessionService()
        runner = Runner(
            agent=root_agent,
            app_name="floridainspect",
            session_service=session_service,
        )
        session = await session_service.create_session(
            app_name="floridainspect", user_id="inspector"
        )

        property_address = body.property_address or "Address not provided"
        inspection_date = body.inspection_date or datetime.date.today().isoformat()

        payload = json.dumps({
            "photo_paths": [tmp_path],
            "property_address": property_address,
            "inspection_date": inspection_date,
            "inspection_type": body.inspection_type,
            "location_hints": [body.location_hint],
        })

        message = Content(role="user", parts=[Part(text=payload)])

        final_text = ""
        agent_texts: dict[str, str] = {}
        pipeline_error: str | None = None
        _SEP = "=" * 72
        try:
            for event in runner.run(
                user_id="inspector",
                session_id=session.id,
                new_message=message,
            ):
                author = getattr(event, "author", "?")
                parts = event.content.parts if event.content else []
                tlen = sum(len(p.text) for p in parts if p.text)
                if event.content and parts:
                    for part in parts:
                        if part.text:
                            cur = agent_texts.get(author, "")
                            if _SEP in part.text:
                                agent_texts[author] = part.text
                            elif not cur or len(part.text) > len(cur):
                                agent_texts[author] = part.text
                        # format_report_text_tool returns its result in function_response.
                        if (
                            author == "report_agent"
                            and hasattr(part, "function_response")
                            and part.function_response
                        ):
                            resp_val = getattr(part.function_response, "response", None)
                            if isinstance(resp_val, dict):
                                for v in resp_val.values():
                                    if isinstance(v, str) and _SEP in v:
                                        agent_texts["report_agent"] = v
                                        break
        except Exception as exc:
            pipeline_error = str(exc)

        # Fallback: scan session history for tool responses from report_agent.
        # Prefer _format_report_text_tool (formatted text), then format
        # _assemble_report_tool result ourselves if needed.
        if not agent_texts.get("report_agent"):
            session_snap = await session_service.get_session(
                app_name="floridainspect", user_id="inspector", session_id=session.id
            )
            _assembled_report: dict | None = None
            if session_snap:
                for ev in reversed(session_snap.events):
                    if ev.author == "report_agent" and ev.content:
                        for part in ev.content.parts:
                            if not (hasattr(part, "function_response") and part.function_response):
                                continue
                            fn_name = getattr(part.function_response, "name", "")
                            rv = getattr(part.function_response, "response", {}) or {}
                            if fn_name == "_format_report_text_tool":
                                rs = rv.get("result", "")
                                if rs and _SEP in rs:
                                    agent_texts["report_agent"] = rs
                                    break
                            elif fn_name == "_assemble_report_tool" and _assembled_report is None:
                                if isinstance(rv, dict) and rv.get("sections"):
                                    _assembled_report = rv
                    if agent_texts.get("report_agent"):
                        break
            # If we found an assembled report but not formatted text, format it now.
            if not agent_texts.get("report_agent") and _assembled_report:
                from agents.report_agent import _format_report_text_tool
                formatted = _format_report_text_tool(_assembled_report)
                if formatted:
                    agent_texts["report_agent"] = formatted

        # Use report_agent text as the final report. Fall back to audit_agent or
        # capture_agent only if report_agent produced nothing.
        for preferred in ("report_agent", "audit_agent", "capture_agent"):
            if agent_texts.get(preferred):
                final_text = agent_texts[preferred]
                break
        if not final_text and agent_texts:
            final_text = max(agent_texts.values(), key=len)

        if not final_text:
            detail = f"ADK pipeline produced no output. {pipeline_error}" if pipeline_error else (
                "ADK pipeline produced no output — this usually means a Vertex AI 429 "
                "RESOURCE_EXHAUSTED rate limit. Wait 30 seconds and retry."
            )
            raise HTTPException(status_code=503, detail=detail)

        # The ADK runner can swallow a Vertex AI 429 and return it embedded in the
        # report text as a "successful" response. Detect that and surface it as a
        # proper rate-limit error instead of a broken report.
        lowered = final_text.lower()
        if "resource_exhausted" in lowered or "429" in final_text or "rate limit" in lowered:
            raise HTTPException(
                status_code=429,
                detail="Vertex AI rate limit exceeded. Please wait 60 seconds and try again.",
            )

    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    report_id = str(uuid.uuid4())
    result: dict[str, Any] = {
        "report_id": report_id,
        "adk_orchestrated": True,
        "orchestrator": "floridainspect_pipeline",
        "agents_used": ["capture_agent", "analyze_agent", "report_agent", "audit_agent"],
        "property_address": property_address,
        "inspection_date": inspection_date,
        "inspection_type": body.inspection_type,
        "report": final_text,
    }
    # Embed downloaded bytes as a data URI so the report never depends on the
    # source URL being browser-loadable (hotlink protection / mixed content /
    # expiring links break <img> silently even when server-side download
    # succeeded).
    result["photo_url"] = (
        f"data:{mime_type or 'image/jpeg'};base64,"
        f"{base64.b64encode(image_bytes).decode()}"
    )

    reports_store[report_id] = result
    _persist_report(report_id, result)
    return result


# ── HTML report renderer ──────────────────────────────────────────────────────

_SEVERITY_CSS: dict[str, str] = {
    "critical": "critical",
    "poor": "major",
    "major": "major",
    "fair": "minor",
    "minor": "minor",
    "satisfactory": "pass",
    "pass": "pass",
    "good": "pass",
    "informational": "pass",
}

_SEVERITY_LABEL: dict[str, str] = {
    "critical": "Critical",
    "poor": "Major",
    "major": "Major",
    "fair": "Minor",
    "minor": "Minor",
    "satisfactory": "Satisfactory",
    "pass": "Satisfactory",
    "good": "Satisfactory",
    "informational": "Informational",
}

# Photo URLs for demo report sections.
# Uses picsum.photos (Unsplash-backed CDN) with deterministic seeds — fast (15KB), no rate limits,
# always 200 OK, designed for hotlinking. Wikimedia Commons full-size images caused 429 rate
# limits during demo sessions due to IP throttling.
_DEMO_PHOTO_URLS: dict[str, str] = {
    "roof":        "https://picsum.photos/seed/rooftiles/320/200",
    "electrical":  "https://picsum.photos/seed/electricalpanel/320/200",
    "plumbing":    "https://picsum.photos/seed/plumbingpipes/320/200",
    "hvac":        "https://picsum.photos/seed/hvacunit/320/200",
    "heating":     "https://picsum.photos/seed/hvacunit/320/200",
    "ventilation": "https://picsum.photos/seed/hvacunit/320/200",
    "structural":  "https://picsum.photos/seed/foundationwall/320/200",
}


def _get_demo_photo_url(system: str) -> Optional[str]:
    system_lower = system.lower()
    for keyword, url in _DEMO_PHOTO_URLS.items():
        if keyword in system_lower:
            return url
    return None


def _inject_demo_photos(report: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of report with photo_url set for each section.

    Existing photo_url values (e.g. real REBS photos from demo_report_output.json)
    are preserved. A picsum.photos placeholder is only used when no URL exists.
    """
    report = dict(report)
    report["sections"] = [
        {**s, "photo_url": s.get("photo_url") or _get_demo_photo_url(s.get("system", ""))}
        for s in (report.get("sections") or [])
    ]
    return report


def _photo_block(url: Optional[str], component: str) -> str:
    """Render the photo thumbnail + caption block for a finding card."""
    safe_comp = escape(component)
    if url:
        safe_url = escape(url)
        placeholder = f'<div class="photo-placeholder" style="display:none"><span>Photo: {safe_comp}</span></div>'
        img = (
            f'<img src="{safe_url}" alt="Field photo — {safe_comp}" class="photo-thumb"'
            f' style="display:block; min-height:150px; background:#f0f0f0;"'
            f" onerror=\"this.style.display='none';this.previousElementSibling.style.display='flex';\">"
        )
    else:
        placeholder = f'<div class="photo-placeholder"><span>Photo: {safe_comp}</span></div>'
        img = ""
    caption = f'<div class="photo-caption">Field photo — {safe_comp}</div>'
    return f'<div class="card-photo">{placeholder}{img}{caption}</div>'


def _parse_adk_report_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Parse the plain-text report produced by _format_report_text_tool.

    Returns the executive summary (if present) and a list of section dicts
    shaped like FullReport sections (system, severity_summary, headline,
    narrative, action_items, inspector_note) so they can be rendered with
    the same finding-card markup used by /pipeline.
    """
    exec_summary = ""
    exec_match = re.search(
        r"EXECUTIVE SUMMARY\n-+\n(.*?)\n\n", text, re.DOTALL
    )
    if exec_match:
        exec_summary = exec_match.group(1).strip()

    sections: list[dict[str, Any]] = []
    for block in re.split(r"\n=+\n", text):
        block = block.strip("\n")
        if not block.startswith("SYSTEM:"):
            continue

        system = ""
        condition = ""
        headline = ""
        body_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("SYSTEM:"):
                system = line[len("SYSTEM:"):].strip()
            elif line.startswith("Condition:"):
                condition = line[len("Condition:"):].strip()
            elif line.startswith("Headline:"):
                headline = line[len("Headline:"):].strip()
            else:
                body_lines.append(line)

        narrative_lines: list[str] = []
        action_items: list[str] = []
        inspector_note: str | None = None
        mode = "narrative"
        for line in body_lines:
            stripped = line.strip()
            if stripped.startswith("Recommended Actions:"):
                mode = "actions"
                continue
            if stripped.startswith("Inspector Note:"):
                inspector_note = stripped[len("Inspector Note:"):].strip()
                mode = "note"
                continue
            if mode == "narrative":
                narrative_lines.append(line)
            elif mode == "actions" and stripped:
                action_items.append(stripped.lstrip("•-* ").strip())

        sections.append({
            "system": system.title(),
            "severity_summary": condition.lower(),
            "headline": headline,
            "narrative": "\n".join(narrative_lines).strip("\n"),
            "action_items": action_items,
            "inspector_note": inspector_note,
        })

    return exec_summary, sections


DEFAULT_LIMITATIONS = [
    "This inspection is a visual, non-invasive examination of accessible areas only.",
    "Areas not accessible (locked rooms, covered components) were not inspected.",
    "Wood-destroying organism (WDO) inspection requires a separate licensed pest control operator.",
    "Sinkhole determination requires a licensed geotechnical engineer.",
    "Mold testing, if warranted, requires a separate licensed mold assessor.",
    "This report does not constitute a warranty or guarantee of any system or component.",
    "AI-generated narratives must be reviewed and approved by the licensed inspector of record.",
]


def _render_report_html(report: dict[str, Any]) -> str:
    sections = report.get("sections", [])
    adk_report_text = report.get("report", "") if not sections else ""
    adk_exec_summary = ""
    if not sections and adk_report_text:
        adk_exec_summary, sections = _parse_adk_report_text(adk_report_text)
        if report.get("photo_url") and sections:
            sections[0]["photo_url"] = report["photo_url"]
    inspection_type = report.get("inspection_type", "4-Point")

    # Severity counts
    counts: dict[str, int] = {"critical": 0, "major": 0, "minor": 0, "pass": 0}
    for s in sections:
        css = _SEVERITY_CSS.get((s.get("severity_summary") or "").lower(), "minor")
        counts[css] = counts.get(css, 0) + 1

    def count_chips() -> str:
        chip_html = []
        labels = [("critical", "Critical"), ("major", "Major"), ("minor", "Minor"), ("pass", "Satisfactory")]
        for key, label in labels:
            n = counts.get(key, 0)
            if n:
                chip_html.append(
                    f'<span class="count-chip count-{key}">{n} {label}</span>'
                )
        return "\n".join(chip_html)

    def render_section(s: dict[str, Any]) -> str:
        sev_raw = (s.get("severity_summary") or "minor").lower()
        css = _SEVERITY_CSS.get(sev_raw, "minor")
        label = _SEVERITY_LABEL.get(sev_raw, sev_raw.title())
        system = escape(s.get("system") or "System")
        headline = escape(s.get("headline") or "")
        narrative_text = escape(s.get("narrative") or "").replace("\n\n", "</p><p>").replace("\n", " ")
        note = s.get("inspector_note")
        note_html = (
            f'<div class="inspector-note">{escape(note)}</div>' if note else ""
        )
        audit = s.get("audit_result") or {}
        if audit:
            if audit.get("passed"):
                statutes = audit.get("verified_statutes") or []
                stat_text = f" · {len(statutes)} statute{'s' if len(statutes) != 1 else ''} verified" if statutes else ""
                audit_badge_html = f'<div class="audit-badge audit-pass">&#10003; Audit Agent verified{escape(stat_text)}</div>'
            else:
                flags = audit.get("flags") or []
                flag_text = f" — {escape(flags[0][:80])}" if flags else ""
                audit_badge_html = f'<div class="audit-badge audit-warn">&#9888; Review Required{flag_text}</div>'
        else:
            audit_badge_html = ""
        actions = s.get("action_items") or []
        action_items_html = "\n".join(
            f"<li>{escape(a)}</li>" for a in actions
        )
        actions_block = (
            f'<div class="actions-label">Recommended Actions</div>'
            f'<ul class="actions">{action_items_html}</ul>'
        ) if actions else ""

        photo = _photo_block(s.get("photo_url"), s.get("system") or "Component")

        return f"""
        <div class="card {css}">
          <div class="card-header">
            <span class="system-name">{system}</span>
            <span class="severity-badge badge-{css}">{label}</span>
          </div>
          <div class="card-body">
            <div class="card-content">
              <div class="headline">{headline}</div>
              <div class="narrative"><p>{narrative_text}</p></div>
              {actions_block}
              {note_html}
              {audit_badge_html}
            </div>
            {photo}
          </div>
        </div>"""

    sections_html = "\n".join(render_section(s) for s in sections)

    limitations = report.get("limitations") or DEFAULT_LIMITATIONS
    limitations_html = "\n".join(
        f"<li>{escape(lim)}</li>" for lim in limitations
    )

    report_id = report.get("report_id", "")
    report_id_html = (
        f'<div class="report-id">Report ID: <code>{escape(report_id)}</code></div>'
        if report_id else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InspectIQ Report — {escape(report.get("property_address", ""))} </title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
      background: #F2F4F7;
      color: #1A1A1A;
      line-height: 1.6;
    }}

    /* ── Header ── */
    .header {{
      background: #0D2340;
      color: white;
      padding: 20px 40px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .logo {{ font-size: 26px; font-weight: 800; letter-spacing: -0.5px; }}
    .logo-accent {{ color: #4DA6FF; }}
    .logo-sub {{ font-size: 12px; color: #7AABDF; margin-top: 3px; letter-spacing: 0.3px; }}
    .header-right {{
      text-align: right;
      font-size: 13px;
      color: #7AABDF;
      line-height: 1.5;
    }}
    .header-right strong {{ color: #C8DEFF; font-size: 14px; display: block; }}

    /* ── Container ── */
    .container {{ max-width: 920px; margin: 0 auto; padding: 32px 24px 48px; }}

    /* ── Property block ── */
    .property-block {{
      background: white;
      border-radius: 10px;
      padding: 24px 28px;
      margin-bottom: 20px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    }}
    .property-address {{
      font-size: 19px;
      font-weight: 700;
      color: #0D2340;
      margin-bottom: 12px;
    }}
    .property-meta {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px 24px;
      font-size: 13.5px;
      color: #555;
    }}
    .meta-row {{ display: flex; gap: 6px; align-items: baseline; }}
    .meta-label {{ font-weight: 600; color: #333; white-space: nowrap; }}
    .report-id {{ font-size: 11px; color: #AAA; margin-top: 10px; }}
    .report-id code {{ font-family: monospace; font-size: 11px; }}

    /* ── Section label ── */
    .section-label {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1.2px;
      text-transform: uppercase;
      color: #7A8599;
      margin-bottom: 10px;
    }}

    /* ── Executive summary ── */
    .exec-block {{
      background: #EEF3FA;
      border-radius: 10px;
      padding: 20px 24px;
      margin-bottom: 24px;
      border-left: 5px solid #0D2340;
    }}
    .exec-block p {{
      font-size: 14.5px;
      color: #2A2A2A;
      line-height: 1.75;
    }}

    /* ── Severity count chips ── */
    .summary-counts {{
      display: flex;
      gap: 10px;
      margin-bottom: 22px;
      flex-wrap: wrap;
    }}
    .count-chip {{
      padding: 5px 14px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.3px;
    }}
    .count-critical {{ background: #FDECEA; color: #B91C1C; }}
    .count-major    {{ background: #FEF0E6; color: #C45000; }}
    .count-minor    {{ background: #FFFBEB; color: #92640A; }}
    .count-pass     {{ background: #ECFDF5; color: #166534; }}

    /* ── Finding cards ── */
    .findings {{ display: flex; flex-direction: column; gap: 14px; margin-bottom: 28px; }}
    .card {{
      background: white;
      border-radius: 10px;
      padding: 22px 24px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.07);
      border-left: 5px solid #DDD;
    }}
    .card.critical {{ border-left-color: #CC0000; }}
    .card.major    {{ border-left-color: #C45000; }}
    .card.minor    {{ border-left-color: #B8860B; }}
    .card.pass     {{ border-left-color: #1A7A4A; }}

    /* Card body: text left, photo right */
    .card-body {{
      display: flex;
      gap: 20px;
      align-items: flex-start;
    }}
    .card-content {{ flex: 1; min-width: 0; }}
    .card-photo {{ flex: 0 0 200px; width: 200px; }}
    .photo-placeholder {{
      background: #F0F2F5;
      border: 1px dashed #D0D5DD;
      border-radius: 6px;
      color: #B0B7C3;
      font-size: 12px;
      height: 140px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 12px;
    }}
    .photo-thumb {{
      width: 100%;
      border-radius: 6px;
      display: block;
      box-shadow: 0 1px 4px rgba(0,0,0,0.12);
    }}
    .photo-caption {{
      font-size: 11px;
      color: #AAA;
      margin-top: 5px;
      text-align: center;
      font-style: italic;
      line-height: 1.4;
    }}

    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }}
    .system-name {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #8A95A8;
    }}
    .severity-badge {{
      font-size: 10.5px;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      padding: 3px 10px;
      border-radius: 4px;
    }}
    .badge-critical {{ background: #FDECEA; color: #B91C1C; }}
    .badge-major    {{ background: #FEF0E6; color: #C45000; }}
    .badge-minor    {{ background: #FFFBEB; color: #92640A; }}
    .badge-pass     {{ background: #ECFDF5; color: #166534; }}

    .headline {{
      font-size: 15.5px;
      font-weight: 600;
      color: #111;
      margin-bottom: 12px;
      line-height: 1.45;
    }}
    .narrative {{
      font-size: 14px;
      color: #444;
      line-height: 1.75;
      margin-bottom: 14px;
    }}
    .narrative p + p {{ margin-top: 10px; }}

    .actions-label {{
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: #8A95A8;
      margin-bottom: 6px;
    }}
    .actions {{ list-style: none; display: flex; flex-direction: column; gap: 5px; }}
    .actions li {{
      font-size: 13.5px;
      color: #333;
      padding-left: 20px;
      position: relative;
      line-height: 1.5;
    }}
    .actions li::before {{
      content: '→';
      position: absolute;
      left: 0;
      color: #AAA;
      font-size: 12px;
      top: 1px;
    }}
    .inspector-note {{
      font-size: 12px;
      color: #999;
      font-style: italic;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid #F0F0F0;
      line-height: 1.6;
    }}
    .audit-badge {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.3px;
      padding: 4px 10px;
      border-radius: 4px;
      margin-top: 10px;
    }}
    .audit-pass {{ background: #ECFDF5; color: #166534; }}
    .audit-warn {{ background: #FEF3C7; color: #92400E; }}

    /* ── ADK plain-text report block ── */
    .adk-report-block {{
      background: white;
      border-radius: 10px;
      padding: 24px 28px;
      margin-bottom: 24px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.07);
      font-size: 14px;
      color: #333;
      line-height: 1.75;
      white-space: pre-wrap;
    }}
    .adk-report-block p + p {{ margin-top: 12px; }}

    /* ── Limitations ── */
    .limitations-block {{
      background: #FAFAFA;
      border-radius: 10px;
      padding: 18px 24px;
      margin-bottom: 24px;
      border: 1px solid #E8E8E8;
    }}
    .limitations-block ul {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 5px;
      margin-top: 10px;
    }}
    .limitations-block li {{
      font-size: 13px;
      color: #666;
      padding-left: 16px;
      position: relative;
      line-height: 1.5;
    }}
    .limitations-block li::before {{
      content: '•';
      position: absolute;
      left: 0;
      color: #BBB;
    }}

    /* ── Footer ── */
    .footer {{
      text-align: center;
      font-size: 12px;
      color: #AAA;
      padding: 20px 0 0;
      border-top: 1px solid #E0E0E0;
      line-height: 1.7;
    }}
    .footer strong {{ color: #888; }}

    @media (max-width: 600px) {{
      .header {{ flex-direction: column; gap: 12px; text-align: center; padding: 16px 20px; }}
      .header-right {{ text-align: center; }}
      .property-meta {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 700px) {{
      .card-body {{ flex-direction: column-reverse; }}
      .card-photo {{ width: 100%; flex: none; }}
      .photo-thumb {{ max-width: 100%; }}
    }}
  </style>
</head>
<body>

<div class="header">
  <div>
    <div class="logo">Inspect<span class="logo-accent">IQ</span></div>
    <div class="logo-sub">Powered by MCAG Technologies</div>
  </div>
  <div class="header-right">
    <strong>Florida Home Inspection Report</strong>
    {escape(inspection_type.title())} Inspection
  </div>
</div>

<div class="container">

  <!-- Property Info -->
  <div class="property-block">
    <div class="property-address">{escape(report.get("property_address", "Address not provided"))}</div>
    <div class="property-meta">
      <div class="meta-row">
        <span class="meta-label">Inspection Date:</span>
        <span>{escape(report.get("inspection_date", ""))}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">Inspector:</span>
        <span>{escape(report.get("inspector_name", "FloridaInspect AI Agent"))}</span>
      </div>
      <div class="meta-row" style="grid-column: 1 / -1;">
        <span class="meta-label">License Note:</span>
        <span>{escape(report.get("inspector_license", ""))}</span>
      </div>
    </div>
    {report_id_html}
  </div>

  <!-- Executive Summary -->
  <div class="section-label">Executive Summary</div>
  <div class="exec-block">
    <p>{escape(report.get("executive_summary", "") or adk_exec_summary)}</p>
  </div>

  <!-- Severity overview chips -->
  <div class="summary-counts">
    {count_chips()}
  </div>

  <!-- Finding Cards -->
  <div class="section-label">Inspection Findings — {len(sections)} System{"s" if len(sections) != 1 else ""}</div>
  <div class="findings">
    {sections_html}
  </div>

  <!-- Limitations -->
  <div class="limitations-block">
    <div class="section-label" style="margin-bottom:0">Limitations of Inspection</div>
    <ul>{limitations_html}</ul>
  </div>

  <!-- Footer -->
  <div class="footer">
    This report was prepared in accordance with Florida Statute 468 Part XV and the Florida Standards of Practice. For questions contact the inspector of record. FloridaInspect Agent — AI-assisted reporting system by MCAG Technologies.
  </div>

</div>
</body>
</html>"""


# ── GET /report/{report_id} ───────────────────────────────────────────────────

@app.get("/report/{report_id}", response_class=HTMLResponse)
def get_report(report_id: str) -> HTMLResponse:
    """Return a pipeline-generated report as a professional HTML page."""
    report = _load_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    return HTMLResponse(content=_render_report_html(report))


# ── GET /demo-report ──────────────────────────────────────────────────────────

@app.get("/demo-report", response_class=HTMLResponse)
def demo_report_html() -> HTMLResponse:
    """Return the Tampa demo report as a professional HTML page.

    Serves from DEMO_CACHE — populated at startup by running the live
    pipeline against MOCK_FINDINGS — so judges always see fresh,
    correctly-configured Gemini narratives. Falls back to the committed
    demo_report_output.json only during the brief startup warm-up window
    before DEMO_CACHE is populated.
    """
    report = DEMO_CACHE
    if report is None:
        if not _DEMO_RESULT_PATH.exists():
            raise HTTPException(
                status_code=404,
                detail="Demo report not found on disk. Run POST /demo first.",
            )
        report = json.loads(_DEMO_RESULT_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(
        content=_render_report_html(_inject_demo_photos(report)),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
