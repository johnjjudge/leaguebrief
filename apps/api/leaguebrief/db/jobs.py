from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from typing import Any
from uuid import uuid4

from leaguebrief.db.connection import connect
from leaguebrief.jobs import ImportJobInput, ImportJobRecord
from leaguebrief.leagues import LeagueAccessDeniedError, LeagueNotFoundError


class SqlImportJobRepository:
    def __init__(self, connection_factory: Callable[[], Any] = connect) -> None:
        self._connection_factory = connection_factory

    def create_import_job_for_authorized_user(
        self,
        user_id: str,
        league_id: str,
        job_input: ImportJobInput,
        now: datetime,
    ) -> ImportJobRecord:
        with closing(self._connection_factory()) as connection:
            try:
                job = self._create_with_connection(
                    connection,
                    user_id,
                    league_id,
                    job_input,
                    now,
                )
                connection.commit()
                return job
            except Exception:
                connection.rollback()
                raise

    def mark_job_enqueue_failed(self, job_id: str, error_summary: str, now: datetime) -> None:
        with closing(self._connection_factory()) as connection:
            try:
                cursor = connection.cursor()
                _execute(
                    cursor,
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
                _insert_event(
                    cursor,
                    job_id,
                    "job_enqueue_failed",
                    error_summary,
                    None,
                    now,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _create_with_connection(
        self,
        connection: Any,
        user_id: str,
        league_id: str,
        job_input: ImportJobInput,
        now: datetime,
    ) -> ImportJobRecord:
        cursor = connection.cursor()
        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        _require_authorized_user_league(cursor, user_id, league_id)

        job_id = str(uuid4())
        requested_seasons_json = (
            json.dumps(list(job_input.requested_seasons), separators=(",", ":"))
            if job_input.requested_seasons is not None
            else None
        )
        _execute(
            cursor,
            """
            INSERT INTO dbo.import_jobs (
                id,
                league_id,
                requested_by_user_id,
                job_type,
                status,
                current_phase,
                priority,
                requested_seasons_json,
                created_at
            )
            VALUES (?, ?, ?, ?, N'queued', NULL, ?, ?, ?)
            """,
            job_id,
            league_id,
            user_id,
            job_input.job_type,
            job_input.priority,
            requested_seasons_json,
            now,
        )
        _insert_event(
            cursor,
            job_id,
            "job_queued",
            "Import job queued.",
            {
                "jobType": job_input.job_type,
                "requestedSeasons": list(job_input.requested_seasons)
                if job_input.requested_seasons is not None
                else None,
            },
            now,
        )

        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        job = _fetch_import_job(cursor, job_id)
        if job is None:
            raise RuntimeError("Failed to reload import job.")
        return job


def _require_authorized_user_league(cursor: Any, user_id: str, league_id: str) -> None:
    league_row = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.leagues
        WHERE id = ?
        """,
        league_id,
    )
    if league_row is None:
        raise LeagueNotFoundError("League not found.")

    user_league_row = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.user_leagues WITH (UPDLOCK, HOLDLOCK)
        WHERE user_id = ? AND league_id = ?
        """,
        user_id,
        league_id,
    )
    if user_league_row is None:
        raise LeagueAccessDeniedError("User does not have access to this league.")


def _insert_event(
    cursor: Any,
    job_id: str,
    event_type: str,
    message: str,
    payload: dict[str, object] | None,
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


def _fetch_import_job(cursor: Any, job_id: str) -> ImportJobRecord | None:
    row = _fetchone(
        cursor,
        """
        SELECT
            id,
            league_id,
            requested_by_user_id,
            job_type,
            status,
            current_phase,
            priority,
            requested_seasons_json,
            started_at,
            completed_at,
            last_heartbeat_at,
            error_summary,
            created_at
        FROM dbo.import_jobs
        WHERE id = ?
        """,
        job_id,
    )
    return _import_job_from_row(row) if row is not None else None


def _import_job_from_row(row: Any) -> ImportJobRecord:
    requested_seasons = None
    if row[7] is not None:
        requested_seasons = tuple(json.loads(row[7]))

    return ImportJobRecord(
        id=str(row[0]),
        league_id=str(row[1]),
        requested_by_user_id=str(row[2]),
        job_type=row[3],
        status=row[4],
        current_phase=row[5],
        priority=row[6],
        requested_seasons=requested_seasons,
        started_at=row[8],
        completed_at=row[9],
        last_heartbeat_at=row[10],
        error_summary=row[11],
        created_at=row[12],
    )


def _execute(cursor: Any, sql: str, *params: object) -> Any:
    return cursor.execute(sql, *params)


def _fetchone(cursor: Any, sql: str, *params: object) -> Any | None:
    return _execute(cursor, sql, *params).fetchone()
