from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from typing import Any
from uuid import uuid4

from leaguebrief.auth import (
    AuthConflictError,
    AuthenticatedPrincipal,
    AuthenticatedUser,
    ProviderAccountRecord,
    UserDisabledError,
    UserRecord,
)
from leaguebrief.db.connection import connect


class SqlUserRepository:
    def __init__(self, connection_factory: Callable[[], Any] = connect) -> None:
        self._connection_factory = connection_factory

    def upsert_from_principal(
        self, principal: AuthenticatedPrincipal, login_at: datetime
    ) -> AuthenticatedUser:
        with closing(self._connection_factory()) as connection:
            try:
                result = self._upsert_with_connection(connection, principal, login_at)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def _upsert_with_connection(
        self,
        connection: Any,
        principal: AuthenticatedPrincipal,
        login_at: datetime,
    ) -> AuthenticatedUser:
        cursor = connection.cursor()

        provider_row = _fetchone(
            cursor,
            """
            SELECT
                u.id,
                u.primary_email,
                u.display_name,
                u.profile_image_url,
                u.status,
                u.created_at,
                u.updated_at,
                u.last_login_at,
                apa.id,
                apa.provider,
                apa.email,
                apa.email_verified,
                apa.last_login_at
            FROM dbo.auth_provider_accounts AS apa
            INNER JOIN dbo.users AS u ON u.id = apa.user_id
            WHERE apa.provider = ? AND apa.provider_subject = ?
            """,
            principal.provider,
            principal.provider_subject,
        )
        if provider_row:
            user_id = str(provider_row[0])
            if provider_row[4] == "disabled":
                raise UserDisabledError("User is disabled.")

            _execute(
                cursor,
                """
                UPDATE dbo.users
                SET
                    display_name = COALESCE(?, display_name),
                    profile_image_url = COALESCE(?, profile_image_url),
                    updated_at = ?,
                    last_login_at = ?
                WHERE id = ?
                """,
                principal.display_name,
                principal.profile_image_url,
                login_at,
                login_at,
                user_id,
            )
            _execute(
                cursor,
                """
                UPDATE dbo.auth_provider_accounts
                SET
                    email = ?,
                    email_verified = ?,
                    display_name = ?,
                    profile_image_url = ?,
                    last_login_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                principal.email,
                principal.email_verified,
                principal.display_name,
                principal.profile_image_url,
                login_at,
                login_at,
                str(provider_row[8]),
            )
            refreshed = _fetch_user_and_provider(cursor, str(provider_row[8]))
            if refreshed is None:
                raise RuntimeError("Failed to reload authenticated user.")
            return refreshed

        user_row = _fetchone(
            cursor,
            """
            SELECT id, status
            FROM dbo.users
            WHERE primary_email = ?
            """,
            principal.email,
        )
        if user_row:
            user_id = str(user_row[0])
            if user_row[1] == "disabled":
                raise UserDisabledError("User is disabled.")

            existing_provider = _fetchone(
                cursor,
                """
                SELECT id
                FROM dbo.auth_provider_accounts
                WHERE user_id = ? AND provider = ?
                """,
                user_id,
                principal.provider,
            )
            if existing_provider:
                raise AuthConflictError(
                    "User already has an account for this identity provider."
                )

            provider_account_id = str(uuid4())
            _insert_provider_account(cursor, provider_account_id, user_id, principal, login_at)
            _execute(
                cursor,
                """
                UPDATE dbo.users
                SET
                    display_name = COALESCE(display_name, ?),
                    profile_image_url = COALESCE(profile_image_url, ?),
                    updated_at = ?,
                    last_login_at = ?
                WHERE id = ?
                """,
                principal.display_name,
                principal.profile_image_url,
                login_at,
                login_at,
                user_id,
            )
            refreshed = _fetch_user_and_provider(cursor, provider_account_id)
            if refreshed is None:
                raise RuntimeError("Failed to reload authenticated user.")
            return refreshed

        user_id = str(uuid4())
        provider_account_id = str(uuid4())
        _execute(
            cursor,
            """
            INSERT INTO dbo.users (
                id,
                primary_email,
                display_name,
                profile_image_url,
                status,
                created_at,
                updated_at,
                last_login_at
            )
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            user_id,
            principal.email,
            principal.display_name,
            principal.profile_image_url,
            login_at,
            login_at,
            login_at,
        )
        _insert_provider_account(cursor, provider_account_id, user_id, principal, login_at)
        refreshed = _fetch_user_and_provider(cursor, provider_account_id)
        if refreshed is None:
            raise RuntimeError("Failed to reload authenticated user.")
        return refreshed


def _insert_provider_account(
    cursor: Any,
    provider_account_id: str,
    user_id: str,
    principal: AuthenticatedPrincipal,
    login_at: datetime,
) -> None:
    _execute(
        cursor,
        """
        INSERT INTO dbo.auth_provider_accounts (
            id,
            user_id,
            provider,
            provider_subject,
            email,
            email_verified,
            display_name,
            profile_image_url,
            last_login_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        provider_account_id,
        user_id,
        principal.provider,
        principal.provider_subject,
        principal.email,
        principal.email_verified,
        principal.display_name,
        principal.profile_image_url,
        login_at,
        login_at,
        login_at,
    )


def _fetch_user_and_provider(cursor: Any, provider_account_id: str) -> AuthenticatedUser | None:
    row = _fetchone(
        cursor,
        """
        SELECT
            u.id,
            u.primary_email,
            u.display_name,
            u.profile_image_url,
            u.status,
            u.created_at,
            u.updated_at,
            u.last_login_at,
            apa.id,
            apa.provider,
            apa.email,
            apa.email_verified,
            apa.last_login_at
        FROM dbo.auth_provider_accounts AS apa
        INNER JOIN dbo.users AS u ON u.id = apa.user_id
        WHERE apa.id = ?
        """,
        provider_account_id,
    )
    if row is None:
        return None

    return AuthenticatedUser(
        user=UserRecord(
            id=str(row[0]),
            primary_email=row[1],
            display_name=row[2],
            profile_image_url=row[3],
            status=row[4],
            created_at=row[5],
            updated_at=row[6],
            last_login_at=row[7],
        ),
        provider_account=ProviderAccountRecord(
            id=str(row[8]),
            provider=row[9],
            email=row[10],
            email_verified=bool(row[11]),
            last_login_at=row[12],
        ),
    )


def _execute(cursor: Any, sql: str, *params: object) -> Any:
    return cursor.execute(sql, *params)


def _fetchone(cursor: Any, sql: str, *params: object) -> Any | None:
    return _execute(cursor, sql, *params).fetchone()
