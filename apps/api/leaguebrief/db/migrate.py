from __future__ import annotations

import argparse
import hashlib
import re
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from leaguebrief.db.connection import connect

MIGRATION_FILE_RE = re.compile(
    r"^(?P<version>\d{4,})_(?P<description>[a-z0-9_]+)\.sql$"
)
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class MigrationError(RuntimeError):
    """Raised when migrations cannot be applied safely."""


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    path: Path
    checksum: str
    sql: str


@dataclass(frozen=True)
class MigrationRunResult:
    applied: tuple[str, ...]
    skipped: tuple[str, ...]


def discover_migrations(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    if not migrations_dir.exists():
        raise MigrationError(f"Migrations directory does not exist: {migrations_dir}")

    migrations: list[Migration] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        match = MIGRATION_FILE_RE.match(path.name)
        if not match:
            raise MigrationError(f"Invalid migration filename: {path.name}")
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=match.group("version"),
                description=match.group("description"),
                path=path,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
            )
        )

    duplicate_versions = _duplicates([migration.version for migration in migrations])
    if duplicate_versions:
        raise MigrationError(
            "Duplicate migration versions: " + ", ".join(duplicate_versions)
        )

    return migrations


def apply_migrations(connection: Any, migrations: Sequence[Migration]) -> MigrationRunResult:
    cursor = connection.cursor()
    ensure_schema_migrations(cursor)
    connection.commit()
    applied = _applied_migrations(cursor)

    applied_versions: list[str] = []
    skipped_versions: list[str] = []

    for migration in migrations:
        existing_checksum = applied.get(migration.version)
        if existing_checksum:
            if existing_checksum != migration.checksum:
                raise MigrationError(
                    f"Applied migration {migration.version} checksum does not match."
                )
            skipped_versions.append(migration.version)
            continue

        try:
            for batch in split_sql_batches(migration.sql):
                cursor.execute(batch)
            cursor.execute(
                """
                INSERT INTO dbo.schema_migrations (version, description, checksum)
                VALUES (?, ?, ?)
                """,
                migration.version,
                migration.description,
                migration.checksum,
            )
            connection.commit()
            applied_versions.append(migration.version)
        except Exception:
            connection.rollback()
            raise

    return MigrationRunResult(
        applied=tuple(applied_versions),
        skipped=tuple(skipped_versions),
    )


def run_migrations(
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    connection: Any | None = None,
) -> MigrationRunResult:
    migrations = discover_migrations(migrations_dir)
    if connection is not None:
        return apply_migrations(connection, migrations)

    with closing(connect()) as sql_connection:
        return apply_migrations(sql_connection, migrations)


def ensure_schema_migrations(cursor: Any) -> None:
    cursor.execute(
        """
        IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.schema_migrations (
                version NVARCHAR(32) NOT NULL
                    CONSTRAINT PK_schema_migrations PRIMARY KEY,
                description NVARCHAR(200) NOT NULL,
                checksum CHAR(64) NOT NULL,
                applied_at DATETIME2(3) NOT NULL
                    CONSTRAINT DF_schema_migrations_applied_at DEFAULT SYSUTCDATETIME()
            );
        END
        """
    )


def split_sql_batches(sql: str) -> list[str]:
    batches: list[str] = []
    current_lines: list[str] = []
    for line in sql.splitlines():
        if line.strip().upper() == "GO":
            batch = "\n".join(current_lines).strip()
            if batch:
                batches.append(batch)
            current_lines = []
            continue
        current_lines.append(line)

    final_batch = "\n".join(current_lines).strip()
    if final_batch:
        batches.append(final_batch)
    return batches


def _applied_migrations(cursor: Any) -> dict[str, str]:
    rows = cursor.execute(
        """
        SELECT version, checksum
        FROM dbo.schema_migrations
        """
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply LeagueBrief SQL migrations.")
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help="Directory containing ordered .sql migration files.",
    )
    args = parser.parse_args()
    result = run_migrations(args.migrations_dir)
    print(
        "Applied migrations: "
        + (", ".join(result.applied) if result.applied else "none")
    )
    print(
        "Skipped migrations: "
        + (", ".join(result.skipped) if result.skipped else "none")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
