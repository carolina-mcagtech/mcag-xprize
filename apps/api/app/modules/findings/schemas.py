# app/modules/findings/schemas.py
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, model_validator

from app.modules.findings.models import Condition, Section

# Sections where condition is mandatory
_CONDITION_REQUIRED = frozenset({
    Section.FRONT, Section.EXTERIOR, Section.INSULATION, Section.PLUMBING,
    Section.STRUCTURAL, Section.ELECTRICAL, Section.ROOF, Section.KITCHEN,
    Section.INTERIOR, Section.AIR_CONDITIONING,
})

# Sections where condition must be null
_CONDITION_FORBIDDEN = frozenset({
    Section.COMMENTS, Section.COUNTY_INFO, Section.DISCLOSURE,
})
# COST_ESTIMATION is in neither set — condition is optional


class FindingCreate(BaseModel):
    section: Section
    item: str
    condition: Condition | None = None
    observations: str | None = None
    estimated_cost: Decimal | None = None
    sort_order: int = 0

    @model_validator(mode="after")
    def validate_section_rules(self) -> "FindingCreate":
        if self.section in _CONDITION_REQUIRED and self.condition is None:
            raise ValueError(
                f"condition is required for section {self.section.value}"
            )
        if self.section in _CONDITION_FORBIDDEN and self.condition is not None:
            raise ValueError(
                f"condition must be null for section {self.section.value}"
            )
        if self.estimated_cost is not None and self.section != Section.COST_ESTIMATION:
            raise ValueError(
                "estimated_cost is only valid for COST_ESTIMATION section"
            )
        return self


class FindingUpdate(BaseModel):
    item: str | None = None
    condition: Condition | None = None
    observations: str | None = None
    estimated_cost: Decimal | None = None
    sort_order: int | None = None


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    inspection_id: uuid.UUID
    section: Section
    item: str
    condition: Condition | None
    observations: str | None
    estimated_cost: Decimal | None
    sort_order: int
    photos: list[dict] = []
    created_at: datetime
    updated_at: datetime


class PhotoUploadRequest(BaseModel):
    content_type: str


class PhotoUploadResponse(BaseModel):
    upload_url: str
    view_url: str
    key: str
    photo_id: str


class PhotoAddRequest(BaseModel):
    key: str
    view_url: str


class PhotoDeleteRequest(BaseModel):
    key: str


class FindingsBySectionResponse(BaseModel):
    section: str
    findings: list[FindingResponse]
