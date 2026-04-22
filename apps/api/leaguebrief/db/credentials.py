from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from typing import Any
from uuid import uuid4

from leaguebrief.credentials import (
    CredentialSecretReferences,
    LeagueCredentialRecord,
    LeagueCredentialUpsertResult,
)
from leaguebrief.db.connection import connect
from leaguebrief.leagues import LeagueAccessDeniedError, LeagueNotFoundError


class SqlCredentialRepository:
    def __init__(self, connection_factory: Callable[[], Any] = connect) -> None:
        self._connection_factory = connection_factory

    def require_user_league_access(self, user_id: str, league_id: str) -> None:
        with closing(self._connection_factory()) as connection:
            _require_authorized_user_league(connection.cursor(), user_id, league_id)

    def upsert_espn_cookie_pair(
        self,
        user_id: str,
        league_id: str,
        secret_references: CredentialSecretReferences,
        now: datetime,
    ) -> LeagueCredentialUpsertResult:
        with closing(self._connection_factory()) as connection:
            try:
                result = self._upsert_with_connection(
                    connection,
                    user_id,
                    league_id,
                    secret_references,
                    now,
                )
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def _upsert_with_connection(
        self,
        connection: Any,
        user_id: str,
        league_id: str,
        secret_references: CredentialSecretReferences,
        now: datetime,
    ) -> LeagueCredentialUpsertResult:
        cursor = connection.cursor()
        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        _require_authorized_user_league(cursor, user_id, league_id)

        existing = _fetch_credential_locked(cursor, user_id, league_id)
        created = existing is None
        if existing is None:
            credential_id = str(uuid4())
            _execute(
                cursor,
                """
                INSERT INTO dbo.league_access_credentials (
                    id,
                    league_id,
                    user_id,
                    credential_type,
                    key_vault_secret_name_s2,
                    key_vault_secret_name_swid,
                    status,
                    is_preferred_for_refresh,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, N'espn_cookie_pair', ?, ?, N'active', 1, ?, ?)
                """,
                credential_id,
                league_id,
                user_id,
                secret_references.key_vault_secret_name_s2,
                secret_references.key_vault_secret_name_swid,
                now,
                now,
            )
        else:
            _execute(
                cursor,
                """
                UPDATE dbo.league_access_credentials
                SET
                    key_vault_secret_name_s2 = ?,
                    key_vault_secret_name_swid = ?,
                    status = N'active',
                    is_preferred_for_refresh = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                secret_references.key_vault_secret_name_s2,
                secret_references.key_vault_secret_name_swid,
                now,
                existing.id,
            )

        _execute(cursor, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        credential = _fetch_credential(cursor, user_id, league_id)
        if credential is None:
            raise RuntimeError("Failed to reload league credential.")
        return LeagueCredentialUpsertResult(credential=credential, created=created)


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


def _fetch_credential_locked(
    cursor: Any,
    user_id: str,
    league_id: str,
) -> LeagueCredentialRecord | None:
    row = _fetchone(
        cursor,
        _credential_select(
            """
            FROM dbo.league_access_credentials WITH (UPDLOCK, HOLDLOCK)
            WHERE user_id = ?
              AND league_id = ?
              AND credential_type = N'espn_cookie_pair'
            """
        ),
        user_id,
        league_id,
    )
    return _credential_from_row(row) if row is not None else None


def _fetch_credential(
    cursor: Any,
    user_id: str,
    league_id: str,
) -> LeagueCredentialRecord | None:
    row = _fetchone(
        cursor,
        _credential_select(
            """
            FROM dbo.league_access_credentials
            WHERE user_id = ?
              AND league_id = ?
              AND credential_type = N'espn_cookie_pair'
            """
        ),
        user_id,
        league_id,
    )
    return _credential_from_row(row) if row is not None else None


def _credential_select(from_clause: str) -> str:
    return (
        """
        SELECT
            id,
            league_id,
            user_id,
            credential_type,
            status,
            is_preferred_for_refresh,
            last_verified_at,
            created_at,
            updated_at
        """
        + from_clause
    )


def _credential_from_row(row: Any) -> LeagueCredentialRecord:
    return LeagueCredentialRecord(
        id=str(row[0]),
        league_id=str(row[1]),
        user_id=str(row[2]),
        credential_type=row[3],
        status=row[4],
        is_preferred_for_refresh=bool(row[5]),
        last_verified_at=row[6],
        created_at=row[7],
        updated_at=row[8],
    )


def _execute(cursor: Any, sql: str, *params: object) -> Any:
    return cursor.execute(sql, *params)


def _fetchone(cursor: Any, sql: str, *params: object) -> Any | None:
    return _execute(cursor, sql, *params).fetchone()
