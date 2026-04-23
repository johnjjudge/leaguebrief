from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import datetime
from typing import Any
from uuid import uuid4

from leaguebrief_fantasypros_adapter import ParsedFantasyProsAdp

from leaguebrief_worker.db.connection import connect
from leaguebrief_worker.fantasypros import (
    FantasyProsRankingSelection,
    FantasyProsReferenceImportResult,
)


class SqlFantasyProsReferenceRepository:
    def __init__(self, connection_factory: Callable[[], Any] = connect) -> None:
        self._connection_factory = connection_factory

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

    def import_adp_file(
        self,
        parsed: ParsedFantasyProsAdp,
        now: datetime,
    ) -> FantasyProsReferenceImportResult:
        with closing(self._connection_factory()) as connection:
            try:
                result = self._import_adp_file_with_connection(connection, parsed, now)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def select_adp_ranking(
        self,
        season: int,
        scoring: str | None,
    ) -> FantasyProsRankingSelection | None:
        with closing(self._connection_factory()) as connection:
            cursor = connection.cursor()
            for candidate_scoring in _candidate_scoring_values(scoring):
                row = _fetchone(
                    cursor,
                    """
                    SELECT TOP (1)
                        id,
                        season,
                        scoring,
                        published_label
                    FROM dbo.reference_rankings
                    WHERE season = ?
                      AND source = N'fantasypros'
                      AND ranking_type = N'adp'
                      AND [format] = N'overall'
                      AND scoring = ?
                    ORDER BY created_at DESC
                    """,
                    season,
                    candidate_scoring,
                )
                if row is not None:
                    return FantasyProsRankingSelection(
                        ranking_id=str(row[0]),
                        season=int(row[1]),
                        scoring=row[2],
                        published_label=row[3],
                    )
        return None

    def _import_adp_file_with_connection(
        self,
        connection: Any,
        parsed: ParsedFantasyProsAdp,
        now: datetime,
    ) -> FantasyProsReferenceImportResult:
        cursor = connection.cursor()
        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        reference_file_id = _ensure_reference_file(cursor, parsed, now)
        ranking_id = _ensure_reference_ranking(cursor, parsed, now)
        existing_item_count = _count_ranking_items(cursor, ranking_id)
        if existing_item_count > 0:
            _execute(cursor, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            return FantasyProsReferenceImportResult(
                reference_file_id=reference_file_id,
                ranking_id=ranking_id,
                inserted=False,
                item_count=existing_item_count,
            )

        for item in parsed.items:
            player_reference_id = _upsert_player_reference(cursor, item)
            _insert_ranking_item(cursor, ranking_id, player_reference_id, item)

        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        return FantasyProsReferenceImportResult(
            reference_file_id=reference_file_id,
            ranking_id=ranking_id,
            inserted=True,
            item_count=len(parsed.items),
        )

    def _update_task(self, sql: str, *params: object) -> None:
        with closing(self._connection_factory()) as connection:
            try:
                _execute(connection.cursor(), sql, *params)
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def _ensure_reference_file(cursor: Any, parsed: ParsedFantasyProsAdp, now: datetime) -> str:
    existing = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.reference_files WITH (UPDLOCK, HOLDLOCK)
        WHERE source = ?
          AND season = ?
          AND file_type = ?
          AND version_label = ?
        """,
        parsed.source,
        parsed.reference.season,
        parsed.file_type,
        parsed.version_label,
    )
    if existing is not None:
        return str(existing[0])

    reference_file_id = str(uuid4())
    _execute(
        cursor,
        """
        INSERT INTO dbo.reference_files (
            id,
            source,
            season,
            file_type,
            blob_path,
            version_label,
            ingested_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        reference_file_id,
        parsed.source,
        parsed.reference.season,
        parsed.file_type,
        parsed.reference.package_relative_path,
        parsed.version_label,
        now,
    )
    return reference_file_id


def _ensure_reference_ranking(cursor: Any, parsed: ParsedFantasyProsAdp, now: datetime) -> str:
    existing = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.reference_rankings WITH (UPDLOCK, HOLDLOCK)
        WHERE season = ?
          AND source = ?
          AND ranking_type = ?
          AND [format] = ?
          AND scoring = ?
          AND published_label = ?
        """,
        parsed.reference.season,
        parsed.source,
        parsed.ranking_type,
        parsed.ranking_format,
        parsed.reference.scoring,
        parsed.published_label,
    )
    if existing is not None:
        return str(existing[0])

    ranking_id = str(uuid4())
    _execute(
        cursor,
        """
        INSERT INTO dbo.reference_rankings (
            id,
            season,
            source,
            ranking_type,
            [format],
            scoring,
            published_label,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ranking_id,
        parsed.reference.season,
        parsed.source,
        parsed.ranking_type,
        parsed.ranking_format,
        parsed.reference.scoring,
        parsed.published_label,
        now,
    )
    return ranking_id


def _count_ranking_items(cursor: Any, ranking_id: str) -> int:
    row = _fetchone(
        cursor,
        """
        SELECT COUNT_BIG(*)
        FROM dbo.reference_ranking_items WITH (UPDLOCK, HOLDLOCK)
        WHERE reference_ranking_id = ?
        """,
        ranking_id,
    )
    return int(row[0] or 0) if row is not None else 0


def _upsert_player_reference(cursor: Any, item: Any) -> str:
    row = _fetchone(
        cursor,
        """
        SELECT TOP (1)
            id,
            nfl_team,
            external_keys_json
        FROM dbo.player_reference WITH (UPDLOCK, HOLDLOCK)
        WHERE (position = ? OR (position IS NULL AND ? IS NULL))
          AND JSON_VALUE(external_keys_json, '$.fantasypros.normalizedName') = ?
        ORDER BY canonical_player_name ASC
        """,
        item.base_position,
        item.base_position,
        item.normalized_player_name,
    )
    if row is not None:
        player_reference_id = str(row[0])
        external_keys_json = _build_external_keys(row[2], item)
        _execute(
            cursor,
            """
            UPDATE dbo.player_reference
            SET nfl_team = COALESCE(nfl_team, ?),
                external_keys_json = ?
            WHERE id = ?
            """,
            item.raw_team,
            external_keys_json,
            player_reference_id,
        )
        return player_reference_id

    player_reference_id = str(uuid4())
    _execute(
        cursor,
        """
        INSERT INTO dbo.player_reference (
            id,
            canonical_player_name,
            position,
            nfl_team,
            external_keys_json
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        player_reference_id,
        item.raw_player_name,
        item.base_position,
        item.raw_team,
        _build_external_keys(None, item),
    )
    return player_reference_id


def _insert_ranking_item(
    cursor: Any,
    ranking_id: str,
    player_reference_id: str,
    item: Any,
) -> None:
    _execute(
        cursor,
        """
        INSERT INTO dbo.reference_ranking_items (
            id,
            reference_ranking_id,
            player_reference_id,
            rank_value,
            adp_value,
            position_rank,
            raw_player_name,
            raw_team,
            raw_position
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        str(uuid4()),
        ranking_id,
        player_reference_id,
        item.rank_value,
        item.adp_value,
        item.position_rank,
        item.raw_player_name,
        item.raw_team,
        item.raw_position,
    )


def _build_external_keys(existing_json: str | None, item: Any) -> str:
    payload: dict[str, Any]
    if existing_json:
        try:
            loaded = json.loads(existing_json)
            payload = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}

    fantasypros = payload.get("fantasypros")
    if not isinstance(fantasypros, dict):
        fantasypros = {}
    fantasypros["normalizedName"] = item.normalized_player_name
    aliases = fantasypros.get("aliases")
    alias_values = {str(alias) for alias in aliases} if isinstance(aliases, list) else set()
    alias_values.add(item.raw_player_name)
    fantasypros["aliases"] = sorted(alias_values)
    payload["fantasypros"] = fantasypros
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _candidate_scoring_values(scoring: str | None) -> tuple[str, ...]:
    requested_scoring = _normalize_scoring(scoring)
    if requested_scoring == "half_ppr":
        return ("half_ppr", "ppr")
    return (requested_scoring,)


def _normalize_scoring(scoring: str | None) -> str:
    if scoring is None:
        return "standard"
    value = scoring.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "std": "standard",
        "standard": "standard",
        "non_ppr": "standard",
        "half": "half_ppr",
        "half_ppr": "half_ppr",
        "0.5_ppr": "half_ppr",
        "ppr": "ppr",
        "full_ppr": "ppr",
    }
    return aliases.get(value, value)


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
