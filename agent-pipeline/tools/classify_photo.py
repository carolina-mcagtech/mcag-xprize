"""
classify_photo — Gemini Vision tool that analyses an inspection photo and
returns a structured FindingDraft describing what was observed.

Used by: CaptureAgent
"""

import base64
import os
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

_GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "mcag-hackathon")
_GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")


def _gemini_client() -> genai.Client:
    return genai.Client(vertexai=True, project=_GCP_PROJECT, location=_GCP_LOCATION)
from PIL import Image
from pydantic import BaseModel, Field


class FindingDraft(BaseModel):
    """Raw finding extracted from a single inspection photo."""

    system: str = Field(description="Inspection system: roof, electrical, plumbing, hvac, structure, other")
    location: str = Field(description="Where in the property the item was observed")
    observation: str = Field(description="Plain-language description of what is visible")
    severity: str = Field(description="Severity level: critical, major, minor, informational")
    deficiency_suspected: bool = Field(description="True if a deficiency is likely present")
    photo_description: str = Field(description="One-sentence caption for the photo")
    confidence: float = Field(description="Model confidence 0.0–1.0", ge=0.0, le=1.0)


_SYSTEM_PROMPT = """You are a licensed Florida home inspector's AI assistant with expertise in
the Florida Standards of Practice (Florida Statute 468 Part XV) and the Florida Building Code.

Analyse the provided inspection photo and return a JSON object matching this schema:
{
  "system": "<roof|electrical|plumbing|hvac|structure|other>",
  "location": "<specific location in property, e.g. 'main electrical panel', 'master bath ceiling'>",
  "observation": "<detailed plain-language description of visible conditions>",
  "severity": "<critical|major|minor|informational>",
  "deficiency_suspected": <true|false>,
  "photo_description": "<one-sentence photo caption>",
  "confidence": <0.0-1.0>
}

Severity guide:
- critical: Immediate safety hazard or insurance-blocking issue (e.g. active leak, exposed wiring)
- major: Significant deficiency requiring prompt repair (e.g. worn roof shingles, failing HVAC)
- minor: Maintenance item or cosmetic concern
- informational: Observable condition, no action required

Return ONLY valid JSON with no additional text."""


def classify_photo(
    image_path: str,
    system_hint: Optional[str] = None,
    location_hint: Optional[str] = None,
) -> FindingDraft:
    """Analyse an inspection photo with Gemini Vision and return a FindingDraft.

    Args:
        image_path: Absolute or relative path to the image file (JPEG, PNG, WEBP).
        system_hint: Optional hint about which inspection system this photo covers.
        location_hint: Optional hint about where in the property this was taken.

    Returns:
        FindingDraft with structured information extracted from the photo.

    Raises:
        FileNotFoundError: If the image file does not exist.
        ValueError: If Gemini returns unparseable output.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    client = _gemini_client()

    img = Image.open(path)

    hint_text = ""
    if system_hint:
        hint_text += f"\nInspection system context: {system_hint}"
    if location_hint:
        hint_text += f"\nLocation context: {location_hint}"

    prompt = _SYSTEM_PROMPT + hint_text

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[prompt, img],
        config=types.GenerateContentConfig(max_output_tokens=8192),
    )
    raw = response.text.strip()

    # Strip markdown fences if model wraps output in ```json ... ```
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return FindingDraft.model_validate_json(raw)
    except Exception as exc:
        raise ValueError(f"Failed to parse Gemini response as FindingDraft: {exc}\nRaw: {raw}") from exc


def classify_photo_from_bytes(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    system_hint: Optional[str] = None,
    location_hint: Optional[str] = None,
) -> FindingDraft:
    """Variant of classify_photo that accepts raw bytes instead of a file path."""
    from google.genai import errors as genai_errors  # local import to avoid top-level dep

    client = _gemini_client()

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    hint_text = ""
    if system_hint:
        hint_text += f"\nInspection system context: {system_hint}"
    if location_hint:
        hint_text += f"\nLocation context: {location_hint}"

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[_SYSTEM_PROMPT + hint_text, image_part],
            config=types.GenerateContentConfig(max_output_tokens=8192),
        )
    except genai_errors.ClientError as exc:
        if exc.code == 429:
            raise RuntimeError(f"Gemini API rate limit exceeded: {exc}") from exc
        raise RuntimeError(f"Gemini API error ({exc.code}): {exc}") from exc

    raw = response.text.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return FindingDraft.model_validate_json(raw)
    except Exception as exc:
        raise ValueError(f"Failed to parse Gemini response as FindingDraft: {exc}\nRaw: {raw}") from exc
