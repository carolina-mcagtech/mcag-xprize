# app/modules/agent_log/service.py
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent_log.models import AgentExecution
from app.modules.agent_log.schemas import (
    AgentExecutionListResponse,
    AgentExecutionResponse,
    AgentExecutionStats,
    DailyExecutionCount,
)
from app.shared.db.session import get_session_factory

logger = logging.getLogger(__name__)

_MAX_FIELD_LEN = 4000


def _truncate(value):
    """Recursively cap string leaves so oversized agent payloads don't bloat rows."""
    if isinstance(value, str):
        return value[:_MAX_FIELD_LEN]
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v) for v in value]
    return value


@asynccontextmanager
async def log_agent_execution(
    session: AsyncSession,
    *,
    agent_name: str,
    trigger_type: str,
    trigger_ref: str | None = None,
    tenant_id: uuid.UUID | None = None,
    input_summary: dict | list | None = None,
) -> AsyncGenerator[AgentExecution, None]:
    """Records one agent invocation to agent_executions.

    `session` is only used to fall back to the request's tenant context
    (session.info["tenant_id"]) when `tenant_id` isn't passed explicitly.
    The log row itself is written on its own dedicated session/transaction,
    not on `session` — never on `session`. `session` belongs to a request
    that get_session owns end-to-end (ADR-023): calling commit() on it here
    would end that transaction early and drop the SET LOCAL tenant GUC for
    whatever RLS-scoped work the caller does afterwards. Writing on a
    separate session also means the log survives even when the caller's own
    transaction later rolls back because of the exception being logged here.
    """
    if tenant_id is None:
        tenant_id = session.info.get("tenant_id")

    entry = AgentExecution(
        agent_name=agent_name,
        trigger_type=trigger_type,
        trigger_ref=trigger_ref,
        tenant_id=tenant_id,
        input_summary=_truncate(input_summary),
    )
    start = time.perf_counter()
    try:
        yield entry
    except Exception as exc:
        entry.status = "error"
        entry.error_message = str(exc)[:_MAX_FIELD_LEN]
        entry.latency_ms = round((time.perf_counter() - start) * 1000)
        await _persist(entry)
        raise
    else:
        entry.latency_ms = round((time.perf_counter() - start) * 1000)
        entry.output_summary = _truncate(entry.output_summary)
        await _persist(entry)


async def _persist(entry: AgentExecution) -> None:
    """Insert-and-commit `entry` on its own session. Never raises: a logging
    failure must not break the calling code, so any error here is swallowed
    after being logged as a warning.
    """
    try:
        async with get_session_factory()() as log_session:
            async with log_session.begin():
                log_session.add(entry)
    except Exception:
        logger.warning(
            "Failed to persist agent execution log for agent_name=%s trigger_type=%s",
            entry.agent_name,
            entry.trigger_type,
            exc_info=True,
        )


async def list_agent_executions(
    session: AsyncSession,
    *,
    agent_name: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AgentExecutionListResponse:
    filters = []
    if agent_name is not None:
        filters.append(AgentExecution.agent_name == agent_name)
    if status is not None:
        filters.append(AgentExecution.status == status)
    if since is not None:
        filters.append(AgentExecution.created_at >= since)
    if until is not None:
        filters.append(AgentExecution.created_at <= until)

    count_result = await session.execute(
        select(func.count()).select_from(AgentExecution).where(*filters)
    )
    total = count_result.scalar_one()

    rows_result = await session.execute(
        select(AgentExecution)
        .where(*filters)
        .order_by(AgentExecution.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = rows_result.scalars().all()

    return AgentExecutionListResponse(
        items=[AgentExecutionResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_agent_execution_stats(session: AsyncSession) -> AgentExecutionStats:
    total_result = await session.execute(select(func.count()).select_from(AgentExecution))
    total = total_result.scalar_one()

    by_agent_result = await session.execute(
        select(AgentExecution.agent_name, func.count())
        .group_by(AgentExecution.agent_name)
    )
    by_agent_name = {name: count for name, count in by_agent_result.all()}

    by_status_result = await session.execute(
        select(AgentExecution.status, func.count())
        .group_by(AgentExecution.status)
    )
    by_status = {status: count for status, count in by_status_result.all()}

    totals_result = await session.execute(
        select(
            func.coalesce(func.sum(AgentExecution.tokens_input), 0),
            func.coalesce(func.sum(AgentExecution.tokens_output), 0),
            func.avg(AgentExecution.latency_ms),
            func.min(AgentExecution.created_at),
            func.max(AgentExecution.created_at),
        )
    )
    tokens_input_total, tokens_output_total, avg_latency_ms, first_at, last_at = totals_result.one()

    window_start = datetime.now(timezone.utc) - timedelta(days=29)
    per_day_result = await session.execute(
        select(
            func.date_trunc("day", AgentExecution.created_at).label("day"),
            func.count(),
        )
        .where(AgentExecution.created_at >= window_start)
        .group_by("day")
        .order_by("day")
    )
    counts_by_day = {row.day.date(): row[1] for row in per_day_result.all()}

    today = datetime.now(timezone.utc).date()
    executions_per_day = [
        DailyExecutionCount(day=day, count=counts_by_day.get(day, 0))
        for day in (
            today - timedelta(days=offset)
            for offset in range(29, -1, -1)
        )
    ]

    return AgentExecutionStats(
        total=total,
        by_agent_name=by_agent_name,
        by_status=by_status,
        tokens_input_total=tokens_input_total,
        tokens_output_total=tokens_output_total,
        avg_latency_ms=float(avg_latency_ms) if avg_latency_ms is not None else None,
        first_execution_at=first_at,
        last_execution_at=last_at,
        executions_per_day=executions_per_day,
    )
