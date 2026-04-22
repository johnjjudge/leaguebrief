from __future__ import annotations

import gc
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from leaguebrief.db.migrate import run_migrations

DEFAULT_TEST_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"
LIVE_SQL_REQUIRED_ENV = (
    "LEAGUEBRIEF_TEST_SQL_SERVER_FQDN",
    "LEAGUEBRIEF_TEST_SQL_ADMIN_LOGIN",
    "LEAGUEBRIEF_TEST_SQL_ADMIN_PASSWORD",
)
DISPOSABLE_DATABASE_RE = re.compile(r"^lbtest_[0-9a-f]{32}$")


@dataclass
class LiveSqlDatabase:
    database_name: str
    connection_string: _ConnectionString
    pyodbc_module: Any
    connections: list[Any] = field(default_factory=list)

    def connect(self) -> Any:
        connection = self.pyodbc_module.connect(str(self.connection_string))
        self.connections.append(connection)
        return connection

    def connection_factory(self) -> Any:
        return self.connect()

    def seed_user(self, user_id: str, email: str) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        with self.managed_connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO dbo.users (
                    id,
                    primary_email,
                    display_name,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, N'active', ?, ?)
                """,
                user_id,
                email,
                email,
                now,
                now,
            )
            connection.commit()

    def scalar(self, sql: str, *params: object) -> Any:
        with self.managed_connection() as connection:
            row = connection.cursor().execute(sql, *params).fetchone()
        return row[0] if row else None

    def close_connections(self) -> None:
        for connection in self.connections:
            try:
                connection.close()
            except Exception:
                pass
        self.connections.clear()

    def managed_connection(self) -> _ManagedConnection:
        return _ManagedConnection(self.connect())


@dataclass
class _ManagedConnection:
    connection: Any

    def __enter__(self) -> Any:
        return self.connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if exc_type is not None:
                self.connection.rollback()
        finally:
            self.connection.close()


@dataclass(frozen=True)
class _ConnectionString:
    value: str

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return "<redacted SQL connection string>"


@pytest.fixture(scope="session")
def live_sql_database() -> LiveSqlDatabase:
    skip_reason = _live_sql_skip_reason()
    if skip_reason:
        pytest.skip(skip_reason)

    pyodbc = pytest.importorskip("pyodbc")
    original_pooling = pyodbc.pooling
    pyodbc.pooling = False

    database_name = f"lbtest_{uuid4().hex}"
    master_connection_string = _build_test_connection_string("master")
    test_connection_string = _build_test_connection_string(database_name)
    database = LiveSqlDatabase(
        database_name=database_name,
        connection_string=test_connection_string,
        pyodbc_module=pyodbc,
    )
    database_created = False

    try:
        _create_database(pyodbc, master_connection_string, database_name)
        database_created = True
        with database.managed_connection() as connection:
            run_migrations(connection=connection)
        yield database
    finally:
        try:
            database.close_connections()
            if database_created:
                _drop_database(pyodbc, master_connection_string, database_name)
        finally:
            pyodbc.pooling = original_pooling
            gc.collect()


def _live_sql_skip_reason() -> str | None:
    if os.getenv("LEAGUEBRIEF_RUN_LIVE_SQL_TESTS") != "1":
        return "Set LEAGUEBRIEF_RUN_LIVE_SQL_TESTS=1 to run live SQL tests."

    missing = [name for name in LIVE_SQL_REQUIRED_ENV if not os.getenv(name)]
    if missing:
        return "Missing live SQL test settings: " + ", ".join(missing)

    return None


def _build_test_connection_string(database_name: str) -> _ConnectionString:
    driver = os.getenv("LEAGUEBRIEF_TEST_SQL_ODBC_DRIVER", DEFAULT_TEST_ODBC_DRIVER)
    server_fqdn = os.environ["LEAGUEBRIEF_TEST_SQL_SERVER_FQDN"]
    login = os.environ["LEAGUEBRIEF_TEST_SQL_ADMIN_LOGIN"]
    password = os.environ["LEAGUEBRIEF_TEST_SQL_ADMIN_PASSWORD"]
    return _ConnectionString(
        (
            f"Driver={{{driver}}};"
            f"Server=tcp:{server_fqdn},1433;"
            f"Database={database_name};"
            f"Uid={login};"
            f"Pwd={password};"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
            "Connection Timeout=30;"
        )
    )


def _create_database(
    pyodbc: Any, master_connection_string: _ConnectionString, database_name: str
) -> None:
    _ensure_disposable_database_name(database_name)
    connection = pyodbc.connect(str(master_connection_string), autocommit=True)
    try:
        connection.cursor().execute(f"CREATE DATABASE {_quote_identifier(database_name)}")
    finally:
        connection.close()


def _drop_database(
    pyodbc: Any, master_connection_string: _ConnectionString, database_name: str
) -> None:
    _ensure_disposable_database_name(database_name)
    connection = pyodbc.connect(str(master_connection_string), autocommit=True)
    try:
        cursor = connection.cursor()
        _kill_database_sessions(cursor, database_name)
        try:
            cursor.execute(
                f"ALTER DATABASE {_quote_identifier(database_name)} "
                "SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
            )
        except Exception:
            # Azure SQL cleanup usually succeeds after KILL; not every SQL target
            # supports SINGLE_USER for database teardown.
            pass
        cursor.execute(f"DROP DATABASE {_quote_identifier(database_name)}")
    except Exception as exc:
        raise RuntimeError(
            "Failed to drop disposable SQL database "
            f"{database_name}; remove it manually."
        ) from exc
    finally:
        connection.close()


def _kill_database_sessions(cursor: Any, database_name: str) -> None:
    cursor.execute(
        """
        DECLARE @database_id INT = DB_ID(?);
        IF @database_id IS NOT NULL
        BEGIN
            DECLARE @kill_sql NVARCHAR(MAX) = N'';
            SELECT @kill_sql = @kill_sql
                + N'KILL ' + CONVERT(NVARCHAR(20), session_id) + N';'
            FROM sys.dm_exec_sessions
            WHERE database_id = @database_id
              AND session_id <> @@SPID;
            EXEC sp_executesql @kill_sql;
        END
        """,
        database_name,
    )


def _quote_identifier(database_name: str) -> str:
    _ensure_disposable_database_name(database_name)
    return f"[{database_name}]"


def _ensure_disposable_database_name(database_name: str) -> None:
    if not DISPOSABLE_DATABASE_RE.match(database_name):
        raise ValueError(f"Refusing to manage non-disposable database: {database_name}")


__all__ = ["LiveSqlDatabase"]
