# app/modules/findings/models.py
import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Enum as SAEnum,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base, TimestampMixin
from app.shared.db.mixins import TenantScopedMixin


class Section(str, enum.Enum):
    FRONT = "FRONT"
    EXTERIOR = "EXTERIOR"
    INSULATION = "INSULATION"
    PLUMBING = "PLUMBING"
    STRUCTURAL = "STRUCTURAL"
    ELECTRICAL = "ELECTRICAL"
    ROOF = "ROOF"
    KITCHEN = "KITCHEN"
    INTERIOR = "INTERIOR"
    AIR_CONDITIONING = "AIR_CONDITIONING"
    COMMENTS = "COMMENTS"
    COST_ESTIMATION = "COST_ESTIMATION"
    COUNTY_INFO = "COUNTY_INFO"
    BEDROOMS = "BEDROOMS"
    BATHROOMS = "BATHROOMS"
    DISCLOSURE = "DISCLOSURE"


class Condition(str, enum.Enum):
    GOOD = "GOOD"
    MARGINAL = "MARGINAL"
    DEFECTIVE = "DEFECTIVE"
    N_A = "N_A"


class Finding(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint(
            "estimated_cost IS NULL OR section = 'COST_ESTIMATION'",
            name="ck_findings_estimated_cost_section",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # No ForeignKey("inspections.id") here — deliberately, per ADR-025.
    # findings and inspections are different modules; a declarative cross-module
    # string FK can raise NoReferencedTableError depending on import order.
    # DB-level FK (fk_findings_inspection_id, ON DELETE CASCADE) already exists
    # via migration 007.
    inspection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    section: Mapped[Section] = mapped_column(
        SAEnum(Section, name="section_enum", create_type=False),
        nullable=False,
    )
    item: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[Condition | None] = mapped_column(
        SAEnum(Condition, name="condition_enum", create_type=False),
        nullable=True,
    )
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    photos: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
