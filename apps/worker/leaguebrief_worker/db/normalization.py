from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from leaguebrief_espn_normalizer import DraftPick, NormalizedSeason
from leaguebrief_fantasypros_adapter import normalize_player_name

from leaguebrief_worker.db.connection import connect
from leaguebrief_worker.normalization import (
    LeagueForNormalization,
    NormalizedSeasonSaveResult,
    RawSnapshotReference,
)


class SqlRawSnapshotNormalizationRepository:
    def __init__(self, connection_factory: Callable[[], Any] = connect) -> None:
        self._connection_factory = connection_factory

    def get_league_for_normalization(self, league_id: str) -> LeagueForNormalization | None:
        with closing(self._connection_factory()) as connection:
            row = _fetchone(
                connection.cursor(),
                """
                SELECT id, scoring_type
                FROM dbo.leagues
                WHERE id = ?
                  AND platform = N'espn'
                """,
                league_id,
            )
        if row is None:
            return None
        return LeagueForNormalization(id=str(row[0]), scoring_type=row[1])

    def list_current_raw_snapshots(
        self,
        league_id: str,
        seasons: Sequence[int] | None,
    ) -> Sequence[RawSnapshotReference]:
        season_filter = ""
        params: list[object] = [league_id]
        if seasons:
            placeholders = ", ".join("?" for _ in seasons)
            season_filter = f"AND season IN ({placeholders})"
            params.extend(seasons)

        with closing(self._connection_factory()) as connection:
            rows = _execute(
                connection.cursor(),
                f"""
                SELECT season, snapshot_type, blob_path
                FROM dbo.raw_snapshots
                WHERE league_id = ?
                  AND is_current = 1
                  AND season IS NOT NULL
                  {season_filter}
                ORDER BY season, snapshot_type, fetched_at DESC
                """,
                *params,
            ).fetchall()
        return [
            RawSnapshotReference(
                season=int(row[0]),
                snapshot_type=row[1],
                blob_path=row[2],
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

    def begin_task(self, job_id: str, task_type: str, season: int, now: datetime) -> str:
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

    def save_normalized_season(
        self,
        league_id: str,
        job_id: str,
        normalized_season: NormalizedSeason,
        fantasypros_ranking_id: str | None,
        now: datetime,
    ) -> NormalizedSeasonSaveResult:
        with closing(self._connection_factory()) as connection:
            try:
                result = self._save_normalized_season_with_connection(
                    connection,
                    league_id,
                    job_id,
                    normalized_season,
                    fantasypros_ranking_id,
                    now,
                )
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def _save_normalized_season_with_connection(
        self,
        connection: Any,
        league_id: str,
        job_id: str,
        season: NormalizedSeason,
        fantasypros_ranking_id: str | None,
        now: datetime,
    ) -> NormalizedSeasonSaveResult:
        cursor = connection.cursor()
        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        season_id = _upsert_season(cursor, league_id, job_id, season, now)
        manager_ids = {
            manager.external_manager_id: _upsert_manager(cursor, league_id, manager)
            for manager in season.managers
        }
        team_ids = {
            team.external_team_id: _upsert_team(cursor, season_id, team, manager_ids)
            for team in season.teams
        }
        _update_season_champion(cursor, season_id, season, team_ids)
        for matchup in season.matchups:
            _upsert_matchup(cursor, season_id, matchup, team_ids)
        for weekly_score in season.weekly_team_scores:
            _upsert_weekly_score(cursor, season_id, weekly_score, team_ids)

        draft_pick_count = 0
        if season.draft is not None:
            draft_id = _upsert_draft(cursor, season_id, season.draft)
            for pick in season.draft.picks:
                if pick.team_external_id not in team_ids:
                    continue
                _upsert_draft_pick(
                    cursor,
                    draft_id,
                    pick,
                    team_ids,
                    fantasypros_ranking_id,
                )
                draft_pick_count += 1

        _upsert_coverage(cursor, season_id, season, fantasypros_ranking_id is not None, now)
        _update_league_import_status(cursor, league_id, now)
        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        return NormalizedSeasonSaveResult(
            season_id=season_id,
            import_status=season.import_status,
            matchup_count=len(season.matchups),
            draft_pick_count=draft_pick_count,
        )

    def _update_task(self, sql: str, *params: object) -> None:
        with closing(self._connection_factory()) as connection:
            try:
                _execute(connection.cursor(), sql, *params)
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def _upsert_season(
    cursor: Any,
    league_id: str,
    job_id: str,
    season: NormalizedSeason,
    now: datetime,
) -> str:
    row = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.seasons WITH (UPDLOCK, HOLDLOCK)
        WHERE league_id = ?
          AND season_year = ?
        """,
        league_id,
        season.season_year,
    )
    if row is not None:
        season_id = str(row[0])
        _execute(
            cursor,
            """
            UPDATE dbo.seasons
            SET settings_json = ?,
                team_count = ?,
                regular_season_weeks = ?,
                playoff_weeks = ?,
                import_status = ?,
                stats_fresh_as_of = ?,
                last_import_job_id = ?
            WHERE id = ?
            """,
            season.settings_json,
            season.team_count,
            season.regular_season_weeks,
            season.playoff_weeks,
            season.import_status,
            now,
            job_id,
            season_id,
        )
        return season_id

    season_id = str(uuid4())
    _execute(
        cursor,
        """
        INSERT INTO dbo.seasons (
            id,
            league_id,
            season_year,
            settings_json,
            team_count,
            regular_season_weeks,
            playoff_weeks,
            import_status,
            stats_fresh_as_of,
            last_import_job_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        season_id,
        league_id,
        season.season_year,
        season.settings_json,
        season.team_count,
        season.regular_season_weeks,
        season.playoff_weeks,
        season.import_status,
        now,
        job_id,
        now,
    )
    return season_id


def _upsert_manager(cursor: Any, league_id: str, manager: Any) -> str:
    row = _fetchone(
        cursor,
        """
        SELECT id, first_seen_season, last_seen_season
        FROM dbo.managers WITH (UPDLOCK, HOLDLOCK)
        WHERE league_id = ?
          AND external_manager_id = ?
        """,
        league_id,
        manager.external_manager_id,
    )
    if row is not None:
        manager_id = str(row[0])
        first_seen = _min_optional_int(row[1], manager.first_seen_season)
        last_seen = _max_optional_int(row[2], manager.last_seen_season)
        _execute(
            cursor,
            """
            UPDATE dbo.managers
            SET display_name = ?,
                normalized_name = ?,
                first_seen_season = ?,
                last_seen_season = ?
            WHERE id = ?
            """,
            manager.display_name,
            manager.normalized_name,
            first_seen,
            last_seen,
            manager_id,
        )
        return manager_id

    manager_id = str(uuid4())
    _execute(
        cursor,
        """
        INSERT INTO dbo.managers (
            id,
            league_id,
            external_manager_id,
            display_name,
            normalized_name,
            first_seen_season,
            last_seen_season
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        manager_id,
        league_id,
        manager.external_manager_id,
        manager.display_name,
        manager.normalized_name,
        manager.first_seen_season,
        manager.last_seen_season,
    )
    return manager_id


def _upsert_team(
    cursor: Any,
    season_id: str,
    team: Any,
    manager_ids: Mapping[str, str],
) -> str:
    manager_id = manager_ids[team.external_manager_id]
    row = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.teams WITH (UPDLOCK, HOLDLOCK)
        WHERE season_id = ?
          AND external_team_id = ?
        """,
        season_id,
        team.external_team_id,
    )
    params = (
        manager_id,
        team.team_name,
        team.abbrev,
        team.wins,
        team.losses,
        team.ties,
        team.points_for,
        team.points_against,
        team.final_standing,
        team.made_playoffs,
        team.is_champion,
    )
    if row is not None:
        team_id = str(row[0])
        _execute(
            cursor,
            """
            UPDATE dbo.teams
            SET manager_id = ?,
                team_name = ?,
                abbrev = ?,
                wins = ?,
                losses = ?,
                ties = ?,
                points_for = ?,
                points_against = ?,
                final_standing = ?,
                made_playoffs = ?,
                is_champion = ?
            WHERE id = ?
            """,
            *params,
            team_id,
        )
        return team_id

    team_id = str(uuid4())
    _execute(
        cursor,
        """
        INSERT INTO dbo.teams (
            id,
            season_id,
            manager_id,
            external_team_id,
            team_name,
            abbrev,
            wins,
            losses,
            ties,
            points_for,
            points_against,
            final_standing,
            made_playoffs,
            is_champion
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        team_id,
        season_id,
        manager_id,
        team.external_team_id,
        team.team_name,
        team.abbrev,
        team.wins,
        team.losses,
        team.ties,
        team.points_for,
        team.points_against,
        team.final_standing,
        team.made_playoffs,
        team.is_champion,
    )
    return team_id


def _update_season_champion(
    cursor: Any,
    season_id: str,
    season: NormalizedSeason,
    team_ids: Mapping[str, str],
) -> None:
    _execute(
        cursor,
        """
        UPDATE dbo.seasons
        SET champion_team_id = ?,
            runner_up_team_id = ?
        WHERE id = ?
        """,
        team_ids.get(season.champion_external_team_id or ""),
        team_ids.get(season.runner_up_external_team_id or ""),
        season_id,
    )


def _upsert_matchup(
    cursor: Any,
    season_id: str,
    matchup: Any,
    team_ids: Mapping[str, str],
) -> None:
    row = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.matchups WITH (UPDLOCK, HOLDLOCK)
        WHERE season_id = ?
          AND source_key = ?
        """,
        season_id,
        matchup.source_key,
    )
    params = (
        matchup.week_number,
        matchup.matchup_type,
        team_ids[matchup.home_external_team_id],
        team_ids[matchup.away_external_team_id],
        matchup.home_score,
        matchup.away_score,
        team_ids.get(matchup.winner_external_team_id or ""),
        matchup.is_complete,
    )
    if row is not None:
        _execute(
            cursor,
            """
            UPDATE dbo.matchups
            SET week_number = ?,
                matchup_type = ?,
                home_team_id = ?,
                away_team_id = ?,
                home_score = ?,
                away_score = ?,
                winner_team_id = ?,
                is_complete = ?
            WHERE id = ?
            """,
            *params,
            str(row[0]),
        )
        return

    _execute(
        cursor,
        """
        INSERT INTO dbo.matchups (
            id,
            season_id,
            week_number,
            matchup_type,
            home_team_id,
            away_team_id,
            home_score,
            away_score,
            winner_team_id,
            is_complete,
            source_key
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        str(uuid4()),
        season_id,
        *params,
        matchup.source_key,
    )


def _upsert_weekly_score(
    cursor: Any,
    season_id: str,
    weekly_score: Any,
    team_ids: Mapping[str, str],
) -> None:
    team_id = team_ids[weekly_score.external_team_id]
    row = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.weekly_team_scores WITH (UPDLOCK, HOLDLOCK)
        WHERE team_id = ?
          AND week_number = ?
        """,
        team_id,
        weekly_score.week_number,
    )
    if row is not None:
        _execute(
            cursor,
            """
            UPDATE dbo.weekly_team_scores
            SET season_id = ?,
                actual_points = ?
            WHERE id = ?
            """,
            season_id,
            weekly_score.actual_points,
            str(row[0]),
        )
        return

    _execute(
        cursor,
        """
        INSERT INTO dbo.weekly_team_scores (
            id,
            season_id,
            team_id,
            week_number,
            actual_points
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        str(uuid4()),
        season_id,
        team_id,
        weekly_score.week_number,
        weekly_score.actual_points,
    )


def _upsert_draft(cursor: Any, season_id: str, draft: Any) -> str:
    row = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.drafts WITH (UPDLOCK, HOLDLOCK)
        WHERE season_id = ?
        """,
        season_id,
    )
    if row is not None:
        draft_id = str(row[0])
        _execute(
            cursor,
            """
            UPDATE dbo.drafts
            SET draft_date = ?,
                draft_type = ?,
                pick_count = ?
            WHERE id = ?
            """,
            draft.draft_date,
            draft.draft_type,
            draft.pick_count,
            draft_id,
        )
        return draft_id

    draft_id = str(uuid4())
    _execute(
        cursor,
        """
        INSERT INTO dbo.drafts (
            id,
            season_id,
            draft_date,
            draft_type,
            pick_count
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        draft_id,
        season_id,
        draft.draft_date,
        draft.draft_type,
        draft.pick_count,
    )
    return draft_id


def _upsert_draft_pick(
    cursor: Any,
    draft_id: str,
    pick: DraftPick,
    team_ids: Mapping[str, str],
    fantasypros_ranking_id: str | None,
) -> None:
    fantasypros_rank_id, fantasypros_adp = _fantasypros_adp_for_pick(
        cursor,
        fantasypros_ranking_id,
        pick,
    )
    reach_value = (
        fantasypros_adp - Decimal(pick.overall_pick) if fantasypros_adp is not None else None
    )
    row = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.draft_picks WITH (UPDLOCK, HOLDLOCK)
        WHERE draft_id = ?
          AND overall_pick = ?
        """,
        draft_id,
        pick.overall_pick,
    )
    params = (
        team_ids[pick.team_external_id],
        pick.round_number,
        pick.round_pick,
        pick.player_name,
        pick.player_external_id,
        pick.position,
        pick.nfl_team,
        fantasypros_rank_id,
        fantasypros_adp,
        reach_value,
    )
    if row is not None:
        _execute(
            cursor,
            """
            UPDATE dbo.draft_picks
            SET team_id = ?,
                round_number = ?,
                round_pick = ?,
                player_name = ?,
                player_external_id = ?,
                position = ?,
                nfl_team = ?,
                fantasypros_rank_id = ?,
                fantasypros_adp = ?,
                reach_value = ?,
                value_delta = NULL
            WHERE id = ?
            """,
            *params,
            str(row[0]),
        )
        return

    _execute(
        cursor,
        """
        INSERT INTO dbo.draft_picks (
            id,
            draft_id,
            team_id,
            overall_pick,
            round_number,
            round_pick,
            player_name,
            player_external_id,
            position,
            nfl_team,
            fantasypros_rank_id,
            fantasypros_adp,
            reach_value,
            value_delta
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        str(uuid4()),
        draft_id,
        team_ids[pick.team_external_id],
        pick.overall_pick,
        pick.round_number,
        pick.round_pick,
        pick.player_name,
        pick.player_external_id,
        pick.position,
        pick.nfl_team,
        fantasypros_rank_id,
        fantasypros_adp,
        reach_value,
    )


def _fantasypros_adp_for_pick(
    cursor: Any,
    fantasypros_ranking_id: str | None,
    pick: DraftPick,
) -> tuple[str | None, Decimal | None]:
    if fantasypros_ranking_id is None:
        return None, None
    normalized_name = normalize_player_name(pick.player_name)
    row = _fetchone(
        cursor,
        """
        SELECT TOP (1)
            rri.id,
            rri.adp_value
        FROM dbo.reference_ranking_items AS rri
        INNER JOIN dbo.player_reference AS pr
            ON pr.id = rri.player_reference_id
        WHERE rri.reference_ranking_id = ?
          AND JSON_VALUE(pr.external_keys_json, '$.fantasypros.normalizedName') = ?
          AND (pr.position = ? OR pr.position IS NULL OR ? IS NULL)
        ORDER BY
            CASE WHEN pr.position = ? THEN 0 ELSE 1 END,
            COALESCE(rri.adp_value, rri.rank_value)
        """,
        fantasypros_ranking_id,
        normalized_name,
        pick.position,
        pick.position,
        pick.position,
    )
    if row is None:
        return None, None
    return str(row[0]), row[1]


def _upsert_coverage(
    cursor: Any,
    season_id: str,
    season: NormalizedSeason,
    has_reference_rankings: bool,
    now: datetime,
) -> None:
    row = _fetchone(
        cursor,
        """
        SELECT id
        FROM dbo.season_data_coverage WITH (UPDLOCK, HOLDLOCK)
        WHERE season_id = ?
        """,
        season_id,
    )
    params = (
        season.coverage.has_draft_data,
        season.coverage.has_matchup_data,
        False,
        season.coverage.has_roster_data,
        has_reference_rankings,
        now,
    )
    if row is not None:
        _execute(
            cursor,
            """
            UPDATE dbo.season_data_coverage
            SET has_draft_data = ?,
                has_matchup_data = ?,
                has_transaction_data = ?,
                has_roster_data = ?,
                has_reference_rankings = ?,
                last_validated_at = ?
            WHERE id = ?
            """,
            *params,
            str(row[0]),
        )
        return

    _execute(
        cursor,
        """
        INSERT INTO dbo.season_data_coverage (
            id,
            season_id,
            has_draft_data,
            has_matchup_data,
            has_transaction_data,
            has_roster_data,
            has_reference_rankings,
            last_validated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        str(uuid4()),
        season_id,
        *params,
    )


def _update_league_import_status(cursor: Any, league_id: str, now: datetime) -> None:
    partial_row = _fetchone(
        cursor,
        """
        SELECT TOP (1) id
        FROM dbo.seasons
        WHERE league_id = ?
          AND import_status <> N'complete'
        """,
        league_id,
    )
    complete_row = _fetchone(
        cursor,
        """
        SELECT TOP (1) id
        FROM dbo.seasons
        WHERE league_id = ?
          AND import_status = N'complete'
        """,
        league_id,
    )
    if partial_row is not None:
        status = "partial"
    elif complete_row is not None:
        status = "complete"
    else:
        status = "not_started"
    _execute(
        cursor,
        """
        UPDATE dbo.leagues
        SET data_completeness_status = ?,
            last_imported_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        status,
        now,
        now,
        league_id,
    )


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


def _min_optional_int(left: int | None, right: int | None) -> int | None:
    values = [value for value in (left, right) if value is not None]
    return min(values) if values else None


def _max_optional_int(left: int | None, right: int | None) -> int | None:
    values = [value for value in (left, right) if value is not None]
    return max(values) if values else None


def _execute(cursor: Any, sql: str, *params: object) -> Any:
    return cursor.execute(sql, *params)


def _fetchone(cursor: Any, sql: str, *params: object) -> Any | None:
    return _execute(cursor, sql, *params).fetchone()
