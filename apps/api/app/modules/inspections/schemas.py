# app/modules/inspections/schemas.py
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.inspections.models import (
    InspectionStatusEnum,
    InspectionTypeEnum,
    PaymentTimingEnum,
)


class InspectionCreate(BaseModel):
    inspector_id: uuid.UUID | None = None
    scheduled_at: datetime
    property_address: str
    inspection_types: list[InspectionTypeEnum] = Field(..., min_length=1)
    total_fee: Decimal
    payment_timing: PaymentTimingEnum = PaymentTimingEnum.AT_PROPERTY

    year_built: int | None = None
    adj_sqft: int | None = None
    gate_code: str | None = None
    lockbox: str | None = None
    realtor_name: str | None = None
    realtor_cell: str | None = None
    owner_buyer_name: str | None = None
    owner_buyer_cell: str | None = None
    owner_buyer_email: str | None = None
    listing_agent_name: str | None = None
    listing_agent_cell: str | None = None
    additional_notes: str | None = None
    full_report_number: str | None = None
    insurance_report_number: str | None = None

    roof_permit_number: str | None = None
    roof_date: date | None = None
    roof_style: str | None = None
    roof_type: str | None = None

    water_heater_type: str | None = None
    water_heater_location: str | None = None
    water_heater_capacity: str | None = None

    electrical_brand: str | None = None
    electrical_amps: int | None = None
    electrical_location: str | None = None

    hvac_brand: str | None = None
    hvac_age: int | None = None
    hvac_model: str | None = None
    hvac_series: str | None = None

    appliances: dict = Field(default_factory=dict)
    rooms: dict = Field(default_factory=dict)

    num_bedrooms: int = 0
    num_bathrooms: int = 0
    num_half_bathrooms: int = 0

    wind_mit_doors_protected: bool = False
    wind_mit_windows_protected: bool = False


class InspectionStatusTransition(BaseModel):
    status: InspectionStatusEnum


class InspectionUpdate(BaseModel):
    inspector_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    property_address: str | None = None
    inspection_types: list[InspectionTypeEnum] | None = Field(default=None, min_length=1)
    total_fee: Decimal | None = None
    payment_timing: PaymentTimingEnum | None = None

    year_built: int | None = None
    adj_sqft: int | None = None
    gate_code: str | None = None
    lockbox: str | None = None
    realtor_name: str | None = None
    realtor_cell: str | None = None
    owner_buyer_name: str | None = None
    owner_buyer_cell: str | None = None
    owner_buyer_email: str | None = None
    listing_agent_name: str | None = None
    listing_agent_cell: str | None = None
    additional_notes: str | None = None
    full_report_number: str | None = None
    insurance_report_number: str | None = None

    roof_permit_number: str | None = None
    roof_date: date | None = None
    roof_style: str | None = None
    roof_type: str | None = None

    water_heater_type: str | None = None
    water_heater_location: str | None = None
    water_heater_capacity: str | None = None

    electrical_brand: str | None = None
    electrical_amps: int | None = None
    electrical_location: str | None = None

    hvac_brand: str | None = None
    hvac_age: int | None = None
    hvac_model: str | None = None
    hvac_series: str | None = None

    appliances: dict | None = None
    rooms: dict | None = None

    num_bedrooms: int | None = None
    num_bathrooms: int | None = None
    num_half_bathrooms: int | None = None

    wind_mit_doors_protected: bool | None = None
    wind_mit_windows_protected: bool | None = None


# Returned by list endpoints — omits sensitive access codes.
class InspectionListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    inspector_id: uuid.UUID
    status: InspectionStatusEnum
    scheduled_at: datetime
    property_address: str
    inspection_types: list[InspectionTypeEnum]
    total_fee: Decimal
    payment_timing: PaymentTimingEnum
    full_report_number: str | None
    insurance_report_number: str | None
    created_at: datetime
    updated_at: datetime


# Returned by single-record GET and write endpoints — includes sensitive fields.
class InspectionResponse(InspectionListResponse):
    year_built: int | None
    adj_sqft: int | None
    gate_code: str | None
    lockbox: str | None
    realtor_name: str | None
    realtor_cell: str | None
    owner_buyer_name: str | None
    owner_buyer_cell: str | None
    owner_buyer_email: str | None
    listing_agent_name: str | None
    listing_agent_cell: str | None
    additional_notes: str | None

    roof_permit_number: str | None
    roof_date: date | None
    roof_style: str | None
    roof_type: str | None

    water_heater_type: str | None
    water_heater_location: str | None
    water_heater_capacity: str | None

    electrical_brand: str | None
    electrical_amps: int | None
    electrical_location: str | None

    hvac_brand: str | None
    hvac_age: int | None
    hvac_model: str | None
    hvac_series: str | None

    appliances: dict
    rooms: dict

    num_bedrooms: int
    num_bathrooms: int
    num_half_bathrooms: int

    wind_mit_doors_protected: bool
    wind_mit_windows_protected: bool


# ── ADR-024 D4: report snapshots ────────────────────────────────────────────


class ReportSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    inspection_id: uuid.UUID
    published_at: datetime
    published_by: uuid.UUID
    content_hash: str
    snapshot_json: dict
    pdf_s3_key: str | None
    created_at: datetime
    updated_at: datetime


# ── ADR-024 D6: inspector narrative library ─────────────────────────────────


class NarrativeLibraryCreate(BaseModel):
    inspector_id: uuid.UUID
    system: str
    trigger_keywords: list[str] = Field(default_factory=list)
    narrative_text: str


class NarrativeLibraryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    inspector_id: uuid.UUID
    system: str
    trigger_keywords: list[str]
    narrative_text: str
    usage_count: int
    created_at: datetime
    updated_at: datetime
