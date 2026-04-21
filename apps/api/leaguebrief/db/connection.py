from __future__ import annotations

import os
from collections.abc import Mapping

DEFAULT_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"


class DatabaseConfigurationError(RuntimeError):
    """Raised when database connection settings are incomplete."""


def build_connection_string(env: Mapping[str, str] | None = None) -> str:
    values = env or os.environ
    explicit_connection_string = values.get("SQL_CONNECTION_STRING")
    if explicit_connection_string:
        return explicit_connection_string

    server_fqdn = values.get("SQL_SERVER_FQDN")
    database_name = values.get("SQL_DATABASE_NAME")
    admin_login = values.get("SQL_ADMIN_LOGIN")
    admin_password = values.get("SQL_ADMIN_PASSWORD")

    missing = [
        name
        for name, value in (
            ("SQL_SERVER_FQDN", server_fqdn),
            ("SQL_DATABASE_NAME", database_name),
            ("SQL_ADMIN_LOGIN", admin_login),
            ("SQL_ADMIN_PASSWORD", admin_password),
        )
        if not value
    ]
    if missing:
        raise DatabaseConfigurationError(
            "Missing SQL connection settings: " + ", ".join(missing)
        )

    driver = values.get("SQL_ODBC_DRIVER", DEFAULT_ODBC_DRIVER)
    return (
        f"Driver={{{driver}}};"
        f"Server=tcp:{server_fqdn},1433;"
        f"Database={database_name};"
        f"Uid={admin_login};"
        f"Pwd={admin_password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )


def connect(connection_string: str | None = None):
    try:
        import pyodbc
    except ImportError as exc:
        raise DatabaseConfigurationError(
            "pyodbc is required for SQL access. Install apps/api/requirements.txt."
        ) from exc

    return pyodbc.connect(connection_string or build_connection_string())
