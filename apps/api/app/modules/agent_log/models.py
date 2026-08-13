# app/modules/agent_log/models.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class AgentExecution(Base):
    """Evidence log of every AI agent invocation. Deliberately has no RLS —
    it is a cross-tenant audit trail (see app/modules/agent_log/service.py).
    Table is managed outside Alembic; this model must mirror it exactly.
    """

    __tablename__ = "agent_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_summary: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="success", server_default="success"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
