from pathlib import Path

import pytest
from leaguebrief.db.migrate import (
    DEFAULT_MIGRATIONS_DIR,
    Migration,
    apply_migrations,
    discover_migrations,
    split_sql_batches,
)


class _FakeConnection:
    def __init__(self, applied=None):
        self.applied = dict(applied or {})
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.cursor_instance = _FakeCursor(self)

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def execute(self, sql, *params):
        normalized = " ".join(sql.split())
        self.connection.executed.append((normalized, params))
        if "SELECT version, checksum FROM dbo.schema_migrations" in normalized:
            self.rows = list(self.connection.applied.items())
        elif normalized.startswith("INSERT INTO dbo.schema_migrations"):
            self.connection.applied[params[0]] = params[2]
            self.rows = []
        else:
            self.rows = []
        return self

    def fetchall(self):
        return self.rows


def test_discover_migrations_finds_mvp_schema():
    migrations = discover_migrations()

    assert [migration.version for migration in migrations] == ["0001"]
    assert migrations[0].description == "mvp_schema"
    assert migrations[0].path.name == "0001_mvp_schema.sql"
    assert len(migrations[0].checksum) == 64


def test_split_sql_batches_uses_go_separator():
    assert split_sql_batches("SELECT 1\nGO\n\nSELECT 2\n") == ["SELECT 1", "SELECT 2"]


def test_apply_migrations_records_new_migration_and_skips_existing():
    migration = Migration(
        version="0001",
        description="test",
        path=Path("0001_test.sql"),
        checksum="a" * 64,
        sql="SELECT 1",
    )
    connection = _FakeConnection()

    first_result = apply_migrations(connection, [migration])
    second_result = apply_migrations(connection, [migration])

    assert first_result.applied == ("0001",)
    assert first_result.skipped == ()
    assert second_result.applied == ()
    assert second_result.skipped == ("0001",)
    assert connection.applied["0001"] == "a" * 64
    assert connection.rollbacks == 0


def test_mvp_schema_contains_required_tables_and_constraints():
    migration_sql = (DEFAULT_MIGRATIONS_DIR / "0001_mvp_schema.sql").read_text(
        encoding="utf-8"
    )

    for table_name in [
        "users",
        "auth_provider_accounts",
        "leagues",
        "user_leagues",
        "league_access_credentials",
        "import_jobs",
        "job_tasks",
        "job_events",
        "raw_snapshots",
        "reference_files",
        "seasons",
        "season_data_coverage",
        "managers",
        "teams",
        "matchups",
        "weekly_team_scores",
        "drafts",
        "draft_picks",
        "transactions",
        "player_reference",
        "reference_rankings",
        "reference_ranking_items",
        "metric_definitions",
        "league_metrics",
        "manager_metrics",
        "team_metrics",
    ]:
        assert f"CREATE TABLE dbo.{table_name}" in migration_sql

    assert "UX_leagues_platform_external_league_id" in migration_sql
    assert "ON dbo.leagues (platform, external_league_id)" in migration_sql
    assert "UX_auth_provider_accounts_provider_subject" in migration_sql
    assert "UX_auth_provider_accounts_user_provider" in migration_sql
    assert "UX_users_primary_email" in migration_sql
    assert "UX_user_leagues_user_league" in migration_sql
    assert "UX_metric_definitions_name_version" in migration_sql


@pytest.mark.sql_integration
def test_live_sql_migrations_run_successfully(live_sql_database):
    with live_sql_database.managed_connection() as connection:
        cursor = connection.cursor()
        applied_rows = cursor.execute(
            """
            SELECT version
            FROM dbo.schema_migrations
            WHERE version = N'0001'
            """
        ).fetchall()
        rows = cursor.execute(
            """
            SELECT name
            FROM sys.indexes
            WHERE name IN (
                'UX_leagues_platform_external_league_id',
                'UX_auth_provider_accounts_provider_subject'
            )
            """
        ).fetchall()
        assert {row[0] for row in rows} == {
            "UX_leagues_platform_external_league_id",
            "UX_auth_provider_accounts_provider_subject",
        }
        assert [row[0] for row in applied_rows] == ["0001"]
