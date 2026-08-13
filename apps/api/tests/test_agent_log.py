# tests/test_agent_log.py
import logging
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.agent_log.models import AgentExecution
from app.modules.agent_log.service import log_agent_execution


@pytest_asyncio.fixture
async def agent_log_table(db_engine):
    """Safety net: agent_executions is managed outside Alembic (see task spec),
    so a fresh test database won't have it yet.
    """
    async with db_engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_executions (
                id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id      UUID,
                agent_name     TEXT NOT NULL,
                trigger_type   TEXT NOT NULL,
                trigger_ref    TEXT,
                input_summary  JSONB,
                decision       TEXT,
                output_summary JSONB,
                model          TEXT,
                tokens_input   INTEGER,
                tokens_output  INTEGER,
                latency_ms     INTEGER,
                status         TEXT NOT NULL DEFAULT 'success',
                error_message  TEXT,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
    yield
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE agent_executions"))


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def test_success_path_writes_row(agent_log_table, session_factory):
    async with session_factory() as session:
        async with log_agent_execution(
            session,
            agent_name="support",
            trigger_type="user_request",
            trigger_ref="abc-123",
            tenant_id=uuid.uuid4(),
            input_summary={"question": "why is the roof flagged?"},
        ) as entry:
            entry.decision = "answered_from_rag"
            entry.output_summary = {"answer": "because of X"}
            entry.model = "gemini-2.5-flash"
            entry.tokens_input = 42
            entry.tokens_output = 17

        result = await session.execute(
            select(AgentExecution).where(AgentExecution.agent_name == "support")
        )
        row = result.scalar_one()
        assert row.status == "success"
        assert row.trigger_ref == "abc-123"
        assert row.decision == "answered_from_rag"
        assert row.output_summary == {"answer": "because of X"}
        assert row.tokens_input == 42
        assert row.tokens_output == 17
        assert row.latency_ms is not None and row.latency_ms >= 0
        assert row.error_message is None


async def test_exception_path_writes_error_and_reraises(agent_log_table, session_factory):
    async with session_factory() as session:
        with pytest.raises(ValueError, match="boom"):
            async with log_agent_execution(
                session,
                agent_name="support-error",
                trigger_type="user_request",
            ) as entry:
                entry.decision = "should not be persisted as success"
                raise ValueError("boom")

        result = await session.execute(
            select(AgentExecution).where(AgentExecution.agent_name == "support-error")
        )
        row = result.scalar_one()
        assert row.status == "error"
        assert row.error_message == "boom"
        assert row.latency_ms is not None


async def test_logging_failure_does_not_propagate(agent_log_table, session_factory, caplog):
    """If the insert itself fails, log_agent_execution must swallow that error
    (after logging a warning) rather than let it break the caller.
    """
    caplog.set_level(logging.WARNING)

    with patch(
        "app.modules.agent_log.service.get_session_factory",
        side_effect=RuntimeError("db unavailable"),
    ):
        async with session_factory() as session:
            async with log_agent_execution(
                session,
                agent_name="support-logfail",
                trigger_type="user_request",
            ) as entry:
                entry.decision = "answered"
            # Reaching this line means the logging failure above didn't propagate.

    assert "Failed to persist agent execution log" in caplog.text
