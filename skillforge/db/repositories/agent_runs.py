"""Persisted LocalHarness results. Separate from evaluation_runs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentRunRecord:
    id: str
    status: str
    final_content: str | None
    steps: int
    tool_errors: int
    tokens: int
    latency_ms: int
    policy_violations: int


def insert_agent_run(conn: sqlite3.Connection, record: AgentRunRecord) -> None:
    conn.execute(
        """
        INSERT INTO agent_runs (
            id, status, final_content, steps, tool_errors, tokens, latency_ms, policy_violations
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.id,
            record.status,
            record.final_content,
            record.steps,
            record.tool_errors,
            record.tokens,
            record.latency_ms,
            record.policy_violations,
        ),
    )


def get_agent_run(conn: sqlite3.Connection, run_id: str) -> AgentRunRecord | None:
    row = conn.execute(
        """
        SELECT id, status, final_content, steps, tool_errors, tokens, latency_ms, policy_violations
        FROM agent_runs
        WHERE id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return AgentRunRecord(
        id=row[0],
        status=row[1],
        final_content=row[2],
        steps=row[3],
        tool_errors=row[4],
        tokens=row[5],
        latency_ms=row[6],
        policy_violations=row[7],
    )
