# app/modules/agent_log/schemas.py
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class AgentExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    agent_name: str
    trigger_type: str
    trigger_ref: str | None
    input_summary: dict | list | None
    decision: str | None
    output_summary: dict | list | None
    model: str | None
    tokens_input: int | None
    tokens_output: int | None
    latency_ms: int | None
    status: str
    error_message: str | None
    created_at: datetime


class AgentExecutionListResponse(BaseModel):
    items: list[AgentExecutionResponse]
    total: int
    limit: int
    offset: int


class DailyExecutionCount(BaseModel):
    day: date
    count: int


class AgentExecutionStats(BaseModel):
    total: int
    by_agent_name: dict[str, int]
    by_status: dict[str, int]
    tokens_input_total: int
    tokens_output_total: int
    avg_latency_ms: float | None
    first_execution_at: datetime | None
    last_execution_at: datetime | None
    executions_per_day: list[DailyExecutionCount]
