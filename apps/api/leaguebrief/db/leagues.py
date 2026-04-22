from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import datetime
from typing import Any
from uuid import uuid4

from leaguebrief.db.connection import connect
from leaguebrief.leagues import (
    LeagueAttachMismatchError,
    LeagueAttachResult,
    LeagueIdentityInput,
    LeagueInput,
    LeagueMembership,
    LeagueNotFoundError,
    LeagueRecord,
    UserLeagueRecord,
)


class SqlLeagueRepository:
    def __init__(self, connection_factory: Callable[[], Any] = connect) -> None:
        self._connection_factory = connection_factory

    def create_or_attach_league(
        self,
        user_id: str,
        league_input: LeagueInput,
        now: datetime,
    ) -> LeagueAttachResult:
        with closing(self._connection_factory()) as connection:
            try:
                result = self._create_or_attach_with_connection(
                    connection, user_id, league_input, now
                )
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def attach_to_league(
        self,
        user_id: str,
        league_id: str,
        league_identity: LeagueIdentityInput,
        now: datetime,
    ) -> LeagueAttachResult:
        with closing(self._connection_factory()) as connection:
            try:
                result = self._attach_with_connection(
                    connection, user_id, league_id, league_identity, now
                )
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def list_user_leagues(self, user_id: str) -> Sequence[LeagueMembership]:
        with closing(self._connection_factory()) as connection:
            rows = _execute(
                connection.cursor(),
                """
                SELECT
                    l.id,
                    l.platform,
                    l.external_league_id,
                    l.name,
                    l.scoring_type,
                    l.is_private,
                    l.timezone,
                    l.first_season,
                    l.last_season,
                    l.created_by_user_id,
                    l.data_completeness_status,
                    l.last_imported_at,
                    l.last_computed_at,
                    l.last_successful_refresh_at,
                    l.created_at,
                    l.updated_at,
                    ul.id,
                    ul.user_id,
                    ul.league_id,
                    ul.role,
                    ul.joined_at,
                    ul.created_at
                FROM dbo.user_leagues AS ul
                INNER JOIN dbo.leagues AS l ON l.id = ul.league_id
                WHERE ul.user_id = ?
                ORDER BY ul.joined_at DESC, l.name ASC
                """,
                user_id,
            ).fetchall()
            return [
                LeagueMembership(
                    league=_league_from_row(row, 0),
                    user_league=_user_league_from_row(row, 16),
                )
                for row in rows
            ]

    def get_league(self, league_id: str) -> LeagueRecord | None:
        with closing(self._connection_factory()) as connection:
            return _fetch_league_by_id(connection.cursor(), league_id)

    def get_user_league(self, user_id: str, league_id: str) -> UserLeagueRecord | None:
        with closing(self._connection_factory()) as connection:
            return _fetch_user_league(connection.cursor(), user_id, league_id)

    def _create_or_attach_with_connection(
        self,
        connection: Any,
        user_id: str,
        league_input: LeagueInput,
        now: datetime,
    ) -> LeagueAttachResult:
        cursor = connection.cursor()
        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")

        league = _fetch_league_by_identity_locked(
            cursor,
            league_input.platform,
            league_input.external_league_id,
        )
        canonical_league_created = league is None
        if league is None:
            league_id = str(uuid4())
            _execute(
                cursor,
                """
                INSERT INTO dbo.leagues (
                    id,
                    platform,
                    external_league_id,
                    name,
                    scoring_type,
                    is_private,
                    timezone,
                    first_season,
                    last_season,
                    created_by_user_id,
                    data_completeness_status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, N'not_started', ?, ?)
                """,
                league_id,
                league_input.platform,
                league_input.external_league_id,
                league_input.name,
                league_input.scoring_type,
                league_input.is_private,
                league_input.timezone,
                league_input.first_season,
                league_input.last_season,
                user_id,
                now,
                now,
            )
            league = _fetch_league_by_id(cursor, league_id)
            if league is None:
                raise RuntimeError("Failed to reload created league.")

        user_league, user_league_created = _ensure_user_league(
            cursor=cursor,
            user_id=user_id,
            league_id=league.id,
            role="owner" if canonical_league_created else "viewer",
            now=now,
        )
        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        return LeagueAttachResult(
            league=league,
            user_league=user_league,
            canonical_league_created=canonical_league_created,
            user_league_created=user_league_created,
        )

    def _attach_with_connection(
        self,
        connection: Any,
        user_id: str,
        league_id: str,
        league_identity: LeagueIdentityInput,
        now: datetime,
    ) -> LeagueAttachResult:
        cursor = connection.cursor()
        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")

        league = _fetch_league_by_id_locked(cursor, league_id)
        if league is None:
            raise LeagueNotFoundError("League not found.")
        if (
            league.platform != league_identity.platform
            or league.external_league_id != league_identity.external_league_id
        ):
            raise LeagueAttachMismatchError(
                "League identity does not match the canonical league."
            )

        user_league, user_league_created = _ensure_user_league(
            cursor=cursor,
            user_id=user_id,
            league_id=league.id,
            role="viewer",
            now=now,
        )
        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        return LeagueAttachResult(
            league=league,
            user_league=user_league,
            canonical_league_created=False,
            user_league_created=user_league_created,
        )


def _ensure_user_league(
    cursor: Any,
    user_id: str,
    league_id: str,
    role: str,
    now: datetime,
) -> tuple[UserLeagueRecord, bool]:
    existing = _fetch_user_league_locked(cursor, user_id, league_id)
    if existing is not None:
        return existing, False

    user_league_id = str(uuid4())
    _execute(
        cursor,
        """
        INSERT INTO dbo.user_leagues (
            id,
            user_id,
            league_id,
            role,
            joined_at,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        user_league_id,
        user_id,
        league_id,
        role,
        now,
        now,
    )
    user_league = _fetch_user_league(cursor, user_id, league_id)
    if user_league is None:
        raise RuntimeError("Failed to reload created user league.")
    return user_league, True


def _fetch_league_by_identity_locked(
    cursor: Any,
    platform: str,
    external_league_id: str,
) -> LeagueRecord | None:
    row = _fetchone(
        cursor,
        _league_select(
            """
            FROM dbo.leagues WITH (UPDLOCK, HOLDLOCK)
            WHERE platform = ? AND external_league_id = ?
            """
        ),
        platform,
        external_league_id,
    )
    return _league_from_row(row) if row is not None else None


def _fetch_league_by_id_locked(cursor: Any, league_id: str) -> LeagueRecord | None:
    row = _fetchone(
        cursor,
        _league_select(
            """
            FROM dbo.leagues WITH (UPDLOCK, HOLDLOCK)
            WHERE id = ?
            """
        ),
        league_id,
    )
    return _league_from_row(row) if row is not None else None


def _fetch_league_by_id(cursor: Any, league_id: str) -> LeagueRecord | None:
    row = _fetchone(
        cursor,
        _league_select(
            """
            FROM dbo.leagues
            WHERE id = ?
            """
        ),
        league_id,
    )
    return _league_from_row(row) if row is not None else None


def _fetch_user_league_locked(
    cursor: Any,
    user_id: str,
    league_id: str,
) -> UserLeagueRecord | None:
    row = _fetchone(
        cursor,
        _user_league_select(
            """
            FROM dbo.user_leagues WITH (UPDLOCK, HOLDLOCK)
            WHERE user_id = ? AND league_id = ?
            """
        ),
        user_id,
        league_id,
    )
    return _user_league_from_row(row) if row is not None else None


def _fetch_user_league(
    cursor: Any,
    user_id: str,
    league_id: str,
) -> UserLeagueRecord | None:
    row = _fetchone(
        cursor,
        _user_league_select(
            """
            FROM dbo.user_leagues
            WHERE user_id = ? AND league_id = ?
            """
        ),
        user_id,
        league_id,
    )
    return _user_league_from_row(row) if row is not None else None


def _league_select(from_clause: str) -> str:
    return (
        """
        SELECT
            id,
            platform,
            external_league_id,
            name,
            scoring_type,
            is_private,
            timezone,
            first_season,
            last_season,
            created_by_user_id,
            data_completeness_status,
            last_imported_at,
            last_computed_at,
            last_successful_refresh_at,
            created_at,
            updated_at
        """
        + from_clause
    )


def _user_league_select(from_clause: str) -> str:
    return (
        """
        SELECT
            id,
            user_id,
            league_id,
            role,
            joined_at,
            created_at
        """
        + from_clause
    )


def _league_from_row(row: Any, offset: int = 0) -> LeagueRecord:
    return LeagueRecord(
        id=str(row[offset]),
        platform=row[offset + 1],
        external_league_id=row[offset + 2],
        name=row[offset + 3],
        scoring_type=row[offset + 4],
        is_private=bool(row[offset + 5]),
        timezone=row[offset + 6],
        first_season=row[offset + 7],
        last_season=row[offset + 8],
        created_by_user_id=str(row[offset + 9]),
        data_completeness_status=row[offset + 10],
        last_imported_at=row[offset + 11],
        last_computed_at=row[offset + 12],
        last_successful_refresh_at=row[offset + 13],
        created_at=row[offset + 14],
        updated_at=row[offset + 15],
    )


def _user_league_from_row(row: Any, offset: int = 0) -> UserLeagueRecord:
    return UserLeagueRecord(
        id=str(row[offset]),
        user_id=str(row[offset + 1]),
        league_id=str(row[offset + 2]),
        role=row[offset + 3],
        joined_at=row[offset + 4],
        created_at=row[offset + 5],
    )


def _execute(cursor: Any, sql: str, *params: object) -> Any:
    return cursor.execute(sql, *params)


def _fetchone(cursor: Any, sql: str, *params: object) -> Any | None:
    return _execute(cursor, sql, *params).fetchone()
