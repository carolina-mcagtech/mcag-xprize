# app/modules/agent_log/router.py
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent_log import service
from app.modules.agent_log.schemas import AgentExecutionListResponse, AgentExecutionStats
from app.shared.db.session import get_session

router = APIRouter(prefix="/agent-executions", tags=["agent-executions"])


@router.get("", response_model=AgentExecutionListResponse)
async def list_agent_executions(
    agent_name: str | None = Query(None),
    status: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> AgentExecutionListResponse:
    return await service.list_agent_executions(
        session,
        agent_name=agent_name,
        status=status,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=AgentExecutionStats)
async def get_agent_execution_stats(
    session: AsyncSession = Depends(get_session),
) -> AgentExecutionStats:
    return await service.get_agent_execution_stats(session)
