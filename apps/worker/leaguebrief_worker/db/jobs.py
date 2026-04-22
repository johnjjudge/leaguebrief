from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import datetime
from typing import Any

from leaguebrief_worker.db.connection import connect


class SqlWorkerJobRepository:
    def __init__(self, connection_factory: Callable[[], Any] = connect) -> None:
        self._connection_factory = connection_factory

    def get_job_status(self, job_id: str) -> str | None:
        with closing(self._connection_factory()) as connection:
            row = _fetchone(
                connection.cursor(),
                """
                SELECT status
                FROM dbo.import_jobs
                WHERE id = ?
                """,
                job_id,
            )
            return row[0] if row else None

    def append_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        payload: Mapping[str, object] | None,
        now: datetime,
    ) -> None:
        with closing(self._connection_factory()) as connection:
            try:
                _insert_event(connection.cursor(), job_id, event_type, message, payload, now)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def mark_validating(self, job_id: str, now: datetime) -> None:
        self._update_job(
            """
            UPDATE dbo.import_jobs
            SET
                status = N'validating',
                current_phase = N'validate',
                started_at = COALESCE(started_at, ?),
                last_heartbeat_at = ?
            WHERE id = ?
              AND status NOT IN (N'succeeded', N'failed', N'cancelled')
            """,
            now,
            now,
            job_id,
        )

    def mark_running(self, job_id: str, now: datetime) -> None:
        self._update_job(
            """
            UPDATE dbo.import_jobs
            SET
                status = N'running',
                current_phase = N'finalize',
                started_at = COALESCE(started_at, ?),
                last_heartbeat_at = ?
            WHERE id = ?
              AND status NOT IN (N'succeeded', N'failed', N'cancelled')
            """,
            now,
            now,
            job_id,
        )

    def mark_succeeded(self, job_id: str, now: datetime) -> None:
        self._update_job(
            """
            UPDATE dbo.import_jobs
            SET
                status = N'succeeded',
                current_phase = N'finalize',
                completed_at = ?,
                last_heartbeat_at = ?,
                error_summary = NULL
            WHERE id = ?
              AND status NOT IN (N'succeeded', N'failed', N'cancelled')
            """,
            now,
            now,
            job_id,
        )

    def mark_failed(self, job_id: str, error_summary: str, now: datetime) -> None:
        self._update_job(
            """
            UPDATE dbo.import_jobs
            SET
                status = N'failed',
                current_phase = N'finalize',
                completed_at = ?,
                last_heartbeat_at = ?,
                error_summary = ?
            WHERE id = ?
              AND status NOT IN (N'succeeded', N'failed', N'cancelled')
            """,
            now,
            now,
            error_summary,
            job_id,
        )

    def _update_job(self, sql: str, *params: object) -> None:
        with closing(self._connection_factory()) as connection:
            try:
                _execute(connection.cursor(), sql, *params)
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def _insert_event(
    cursor: Any,
    job_id: str,
    event_type: str,
    message: str,
    payload: Mapping[str, object] | None,
    now: datetime,
) -> None:
    _execute(
        cursor,
        """
        INSERT INTO dbo.job_events (
            job_id,
            event_type,
            message,
            payload_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        job_id,
        event_type,
        message,
        json.dumps(payload, separators=(",", ":")) if payload is not None else None,
        now,
    )


def _execute(cursor: Any, sql: str, *params: object) -> Any:
    return cursor.execute(sql, *params)


def _fetchone(cursor: Any, sql: str, *params: object) -> Any | None:
    return _execute(cursor, sql, *params).fetchone()
