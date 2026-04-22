from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from datetime import datetime
from typing import Any
from uuid import uuid4

from leaguebrief_worker.db.connection import connect
from leaguebrief_worker.ingestion import CredentialSecretReference, LeagueForIngestion


class SqlRawSnapshotRepository:
    def __init__(self, connection_factory: Callable[[], Any] = connect) -> None:
        self._connection_factory = connection_factory

    def get_league_for_ingestion(self, league_id: str) -> LeagueForIngestion | None:
        with closing(self._connection_factory()) as connection:
            row = _fetchone(
                connection.cursor(),
                """
                SELECT
                    id,
                    external_league_id,
                    first_season,
                    last_season,
                    is_private
                FROM dbo.leagues
                WHERE id = ?
                  AND platform = N'espn'
                """,
                league_id,
            )
        if row is None:
            return None
        return LeagueForIngestion(
            id=str(row[0]),
            external_league_id=str(row[1]),
            first_season=row[2],
            last_season=row[3],
            is_private=bool(row[4]),
        )

    def list_credential_secret_references(
        self,
        league_id: str,
        requested_by_user_id: str,
    ) -> Sequence[CredentialSecretReference]:
        with closing(self._connection_factory()) as connection:
            rows = _execute(
                connection.cursor(),
                """
                SELECT
                    user_id,
                    key_vault_secret_name_s2,
                    key_vault_secret_name_swid,
                    is_preferred_for_refresh
                FROM dbo.league_access_credentials
                WHERE league_id = ?
                  AND credential_type = N'espn_cookie_pair'
                  AND status = N'active'
                  AND (user_id = ? OR is_preferred_for_refresh = 1)
                ORDER BY
                    CASE
                        WHEN user_id = ? THEN 0
                        WHEN is_preferred_for_refresh = 1 THEN 1
                        ELSE 2
                    END,
                    updated_at DESC
                """,
                league_id,
                requested_by_user_id,
                requested_by_user_id,
            ).fetchall()
        return [
            CredentialSecretReference(
                user_id=str(row[0]),
                key_vault_secret_name_s2=row[1],
                key_vault_secret_name_swid=row[2],
                is_preferred_for_refresh=bool(row[3]),
            )
            for row in rows
        ]

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

    def begin_task(
        self,
        job_id: str,
        task_type: str,
        season: int,
        now: datetime,
    ) -> str:
        task_id = str(uuid4())
        with closing(self._connection_factory()) as connection:
            try:
                cursor = connection.cursor()
                attempt_count = _next_attempt_count(cursor, job_id, task_type, season)
                _execute(
                    cursor,
                    """
                    INSERT INTO dbo.job_tasks (
                        id,
                        job_id,
                        task_type,
                        season,
                        status,
                        attempt_count,
                        started_at
                    )
                    VALUES (?, ?, ?, ?, N'running', ?, ?)
                    """,
                    task_id,
                    job_id,
                    task_type,
                    season,
                    attempt_count,
                    now,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return task_id

    def complete_task(self, task_id: str, now: datetime) -> None:
        self._update_task(
            """
            UPDATE dbo.job_tasks
            SET status = N'succeeded',
                completed_at = ?,
                error_message = NULL
            WHERE id = ?
            """,
            now,
            task_id,
        )

    def fail_task(self, task_id: str, error_message: str, now: datetime) -> None:
        self._update_task(
            """
            UPDATE dbo.job_tasks
            SET status = N'failed',
                completed_at = ?,
                error_message = ?
            WHERE id = ?
            """,
            now,
            error_message,
            task_id,
        )

    def save_raw_snapshot(
        self,
        league_id: str,
        season: int,
        snapshot_type: str,
        blob_path: str,
        source_hash: str,
        now: datetime,
    ) -> bool:
        with closing(self._connection_factory()) as connection:
            try:
                inserted = self._save_raw_snapshot_with_connection(
                    connection,
                    league_id,
                    season,
                    snapshot_type,
                    blob_path,
                    source_hash,
                    now,
                )
                connection.commit()
                return inserted
            except Exception:
                connection.rollback()
                raise

    def _save_raw_snapshot_with_connection(
        self,
        connection: Any,
        league_id: str,
        season: int,
        snapshot_type: str,
        blob_path: str,
        source_hash: str,
        now: datetime,
    ) -> bool:
        cursor = connection.cursor()
        current = _fetchone(
            cursor,
            """
            SELECT TOP (1) source_hash
            FROM dbo.raw_snapshots WITH (UPDLOCK, HOLDLOCK)
            WHERE league_id = ?
              AND season = ?
              AND snapshot_type = ?
              AND is_current = 1
            ORDER BY fetched_at DESC
            """,
            league_id,
            season,
            snapshot_type,
        )
        if current is not None and current[0] == source_hash:
            return False

        _execute(
            cursor,
            """
            UPDATE dbo.raw_snapshots
            SET is_current = 0
            WHERE league_id = ?
              AND season = ?
              AND snapshot_type = ?
              AND is_current = 1
            """,
            league_id,
            season,
            snapshot_type,
        )
        _execute(
            cursor,
            """
            INSERT INTO dbo.raw_snapshots (
                id,
                league_id,
                season,
                snapshot_type,
                blob_path,
                source_hash,
                is_current,
                fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            str(uuid4()),
            league_id,
            season,
            snapshot_type,
            blob_path,
            source_hash,
            now,
        )
        return True

    def _update_task(self, sql: str, *params: object) -> None:
        with closing(self._connection_factory()) as connection:
            try:
                _execute(connection.cursor(), sql, *params)
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def _next_attempt_count(cursor: Any, job_id: str, task_type: str, season: int) -> int:
    row = _fetchone(
        cursor,
        """
        SELECT COALESCE(MAX(attempt_count), 0)
        FROM dbo.job_tasks
        WHERE job_id = ?
          AND task_type = ?
          AND season = ?
        """,
        job_id,
        task_type,
        season,
    )
    return int(row[0] or 0) + 1 if row is not None else 1


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
