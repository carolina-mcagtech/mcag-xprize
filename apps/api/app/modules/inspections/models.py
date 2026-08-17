# app/modules/inspections/models.py
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base, TimestampMixin
from app.shared.db.mixins import TenantScopedMixin


class InspectionTypeEnum(str, enum.Enum):
    FULL_INSPECTION = "FULL_INSPECTION"
    WIND_MITIGATION = "WIND_MITIGATION"
    FOUR_POINT = "FOUR_POINT"
    MOLD_INSPECTION = "MOLD_INSPECTION"
    TERMITES = "TERMITES"
    ROOF_CERTIFICATION = "ROOF_CERTIFICATION"
    OPENING_PROTECTION = "OPENING_PROTECTION"
    SEWER_INSPECTION = "SEWER_INSPECTION"
    LEAD_PAINT_INSPECTION = "LEAD_PAINT_INSPECTION"
    WATER_QUALITY_TEST = "WATER_QUALITY_TEST"


class PaymentTimingEnum(str, enum.Enum):
    AT_PROPERTY = "AT_PROPERTY"
    AT_DELIVERY = "AT_DELIVERY"
    AFTER_DELIVERY = "AFTER_DELIVERY"


class InspectionStatusEnum(str, enum.Enum):
    """ADR-024 D1 — strict FSM, no state may be skipped.

    DRAFT -> IN_FIELD -> PENDING_REVIEW -> PUBLISHED -> DELIVERED

    PUBLISHED is write-locked: no field on a published inspection may be
    modified (ADR-024 D1). Amendments require a new revision, not an overwrite.
    """

    DRAFT = "DRAFT"
    IN_FIELD = "IN_FIELD"
    PENDING_REVIEW = "PENDING_REVIEW"
    PUBLISHED = "PUBLISHED"
    DELIVERED = "DELIVERED"


class Inspection(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint(
            "cardinality(inspection_types) >= 1",
            name="ck_inspections_types_nonempty",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # No ForeignKey("inspector_profiles.id") here — deliberately, per ADR-025.
    # A cross-module string FK can raise NoReferencedTableError (via
    # Base.metadata.sorted_tables) if inspector_profiles isn't registered yet.
    # DB-level FK (fk_inspections_inspector_id, ON DELETE RESTRICT) already
    # exists via migration 010.
    inspector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    status: Mapped[InspectionStatusEnum] = mapped_column(
        SAEnum(InspectionStatusEnum, name="inspection_status_enum", create_type=False),
        nullable=False,
        default=InspectionStatusEnum.DRAFT,
        server_default="DRAFT",
    )

    # ── Intake (REBS Ficha card) ─────────────────────────────────────────────
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    property_address: Mapped[str] = mapped_column(String(500), nullable=False)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adj_sqft: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Sensitive access codes — never included in list responses.
    gate_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lockbox: Mapped[str | None] = mapped_column(String(50), nullable=True)

    realtor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    realtor_cell: Mapped[str | None] = mapped_column(String(20), nullable=True)
    owner_buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_buyer_cell: Mapped[str | None] = mapped_column(String(20), nullable=True)
    owner_buyer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    listing_agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    listing_agent_cell: Mapped[str | None] = mapped_column(String(20), nullable=True)
    additional_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    inspection_types: Mapped[list[InspectionTypeEnum]] = mapped_column(
        ARRAY(SAEnum(InspectionTypeEnum, name="inspection_type_enum", create_type=False)),
        nullable=False,
    )

    # ── Financial ─────────────────────────────────────────────────────────────
    total_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_timing: Mapped[PaymentTimingEnum] = mapped_column(
        SAEnum(PaymentTimingEnum, name="payment_timing_enum", create_type=False),
        nullable=False,
        default=PaymentTimingEnum.AT_PROPERTY,
        server_default="AT_PROPERTY",
    )

    # ── Report numbers ────────────────────────────────────────────────────────
    full_report_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    insurance_report_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── Roof (REBS Preinspection sheet) ─────────────────────────────────────────
    roof_permit_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    roof_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    roof_style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    roof_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Water heater ─────────────────────────────────────────────────────────
    water_heater_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    water_heater_location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    water_heater_capacity: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── Electrical ───────────────────────────────────────────────────────────
    electrical_brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    electrical_amps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    electrical_location: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── HVAC ─────────────────────────────────────────────────────────────────
    hvac_brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hvac_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hvac_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hvac_series: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Appliances / rooms (room-by-room, REBS Preinspection sheet) ────────────
    appliances: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    rooms: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    # ── Room counts (drives BEDROOMS / BATHROOMS observation sections) ────────
    num_bedrooms: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    num_bathrooms: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    num_half_bathrooms: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")

    # ── Wind mitigation ──────────────────────────────────────────────────────
    wind_mit_doors_protected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    wind_mit_windows_protected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class ReportSnapshot(Base, TenantScopedMixin, TimestampMixin):
    """ADR-024 D4 component 2 — immutable snapshot created on PUBLISHED transition.

    The delivered PDF is generated from this snapshot, not the live
    inspection record, so a later edit to the inspection cannot alter what
    was already delivered.
    """

    __tablename__ = "report_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    inspection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inspections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # No ForeignKey("inspector_profiles.id") here — deliberately, per ADR-025.
    # DB-level FK (fk_report_snapshots_published_by, ON DELETE RESTRICT)
    # already exists via migration 010.
    published_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pdf_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class InspectorNarrativeLibrary(Base, TenantScopedMixin, TimestampMixin):
    """ADR-024 D6 — inspector's own narrative corpus.

    Phase 4 AI is constrained to retrieval/suggestion from this table, never
    generation from a generic model, so it must exist from Phase 1.
    """

    __tablename__ = "inspector_narrative_library"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # No ForeignKey("inspector_profiles.id") here — deliberately, per ADR-025.
    # DB-level FK (fk_inspector_narrative_library_inspector_id, ON DELETE
    # CASCADE) already exists via migration 010.
    inspector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    system: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    narrative_text: Mapped[str] = mapped_column(Text, nullable=False)
    usage_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
