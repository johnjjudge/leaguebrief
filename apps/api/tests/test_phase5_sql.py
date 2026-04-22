from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from leaguebrief.credentials import CredentialService
from leaguebrief.db.credentials import SqlCredentialRepository
from leaguebrief.db.jobs import SqlImportJobRepository
from leaguebrief.db.leagues import SqlLeagueRepository
from leaguebrief.jobs import ImportJobInput
from leaguebrief.leagues import LeagueAccessDeniedError, LeagueInput

pytestmark = pytest.mark.sql_integration


class _InMemorySecretStore:
    def __init__(self):
        self.secrets = {}

    def set_secret(self, name: str, value: str) -> None:
        self.secrets[name] = value


def test_live_sql_credentials_store_only_secret_references(live_sql_database):
    user_id = str(uuid4())
    live_sql_database.seed_user(user_id, _email("credential-owner"))
    league = _create_league(live_sql_database, user_id)
    secret_store = _InMemorySecretStore()
    service = CredentialService(
        repository=SqlCredentialRepository(live_sql_database.connection_factory),
        secret_store=secret_store,
    )

    service.submit_espn_credentials(
        user_id,
        league.id,
        {"espnS2": "raw-s2-cookie", "SWID": "{raw-swid-cookie}"},
        _now(),
    )

    assert set(secret_store.secrets.values()) == {"raw-s2-cookie", "{raw-swid-cookie}"}
    assert (
        live_sql_database.scalar(
            """
            SELECT COUNT(*)
            FROM dbo.league_access_credentials
            WHERE league_id = ?
              AND user_id = ?
              AND (
                  key_vault_secret_name_s2 IN (?, ?)
                  OR key_vault_secret_name_swid IN (?, ?)
              )
            """,
            league.id,
            user_id,
            "raw-s2-cookie",
            "{raw-swid-cookie}",
            "raw-s2-cookie",
            "{raw-swid-cookie}",
        )
        == 0
    )
    assert (
        live_sql_database.scalar(
            """
            SELECT COUNT(*)
            FROM dbo.league_access_credentials
            WHERE league_id = ?
              AND user_id = ?
              AND key_vault_secret_name_s2 LIKE N'lb-espn-s2-%'
              AND key_vault_secret_name_swid LIKE N'lb-espn-swid-%'
            """,
            league.id,
            user_id,
        )
        == 1
    )


def test_live_sql_credentials_require_user_league_access_before_secret_write(
    live_sql_database,
):
    owner_id = str(uuid4())
    unauthorized_id = str(uuid4())
    live_sql_database.seed_user(owner_id, _email("credential-owner"))
    live_sql_database.seed_user(unauthorized_id, _email("credential-viewer"))
    league = _create_league(live_sql_database, owner_id)
    secret_store = _InMemorySecretStore()
    service = CredentialService(
        repository=SqlCredentialRepository(live_sql_database.connection_factory),
        secret_store=secret_store,
    )

    with pytest.raises(LeagueAccessDeniedError):
        service.submit_espn_credentials(
            unauthorized_id,
            league.id,
            {"espn_s2": "raw-s2-cookie", "swid": "{raw-swid-cookie}"},
            _now(),
        )

    assert secret_store.secrets == {}
    assert (
        live_sql_database.scalar(
            """
            SELECT COUNT(*)
            FROM dbo.league_access_credentials
            WHERE league_id = ?
              AND user_id = ?
            """,
            league.id,
            unauthorized_id,
        )
        == 0
    )


def test_live_sql_import_job_creation_inserts_job_and_event(live_sql_database):
    user_id = str(uuid4())
    live_sql_database.seed_user(user_id, _email("job-owner"))
    league = _create_league(live_sql_database, user_id)
    repository = SqlImportJobRepository(live_sql_database.connection_factory)

    job = repository.create_import_job_for_authorized_user(
        user_id,
        league.id,
        ImportJobInput(
            job_type="initial_import",
            requested_seasons=(2022, 2023),
            priority=5,
        ),
        _now(),
    )

    assert job.status == "queued"
    assert job.requested_seasons == (2022, 2023)
    assert (
        live_sql_database.scalar(
            """
            SELECT COUNT(*)
            FROM dbo.import_jobs
            WHERE id = ?
              AND league_id = ?
              AND requested_by_user_id = ?
            """,
            job.id,
            league.id,
            user_id,
        )
        == 1
    )
    assert (
        live_sql_database.scalar(
            """
            SELECT COUNT(*)
            FROM dbo.job_events
            WHERE job_id = ?
              AND event_type = N'job_queued'
            """,
            job.id,
        )
        == 1
    )


def test_live_sql_import_job_creation_requires_user_league_access(live_sql_database):
    owner_id = str(uuid4())
    unauthorized_id = str(uuid4())
    live_sql_database.seed_user(owner_id, _email("job-owner"))
    live_sql_database.seed_user(unauthorized_id, _email("job-viewer"))
    league = _create_league(live_sql_database, owner_id)
    repository = SqlImportJobRepository(live_sql_database.connection_factory)

    with pytest.raises(LeagueAccessDeniedError):
        repository.create_import_job_for_authorized_user(
            unauthorized_id,
            league.id,
            ImportJobInput(
                job_type="initial_import",
                requested_seasons=None,
                priority=0,
            ),
            _now(),
        )

    assert (
        live_sql_database.scalar(
            """
            SELECT COUNT(*)
            FROM dbo.import_jobs
            WHERE league_id = ?
              AND requested_by_user_id = ?
            """,
            league.id,
            unauthorized_id,
        )
        == 0
    )


def _create_league(live_sql_database, user_id: str):
    repository = SqlLeagueRepository(live_sql_database.connection_factory)
    result = repository.create_or_attach_league(
        user_id,
        LeagueInput(
            platform="espn",
            external_league_id=f"phase5-{uuid4().hex}",
            name="Phase 5 League",
            scoring_type="ppr",
            is_private=True,
            timezone="America/New_York",
            first_season=2022,
            last_season=2025,
        ),
        _now(),
    )
    return result.league


def _now() -> datetime:
    return datetime(2026, 4, 22, 12, 0, tzinfo=UTC)


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}@example.com"
