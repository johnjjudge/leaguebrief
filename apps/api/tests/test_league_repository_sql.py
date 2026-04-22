from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from leaguebrief.db.leagues import SqlLeagueRepository
from leaguebrief.leagues import (
    LeagueAttachMismatchError,
    LeagueIdentityInput,
    LeagueInput,
)

pytestmark = pytest.mark.sql_integration


def test_live_sql_create_or_attach_maps_two_users_to_one_canonical_league(
    live_sql_database,
):
    user_one = str(uuid4())
    user_two = str(uuid4())
    live_sql_database.seed_user(user_one, _email("user-one"))
    live_sql_database.seed_user(user_two, _email("user-two"))
    repository = SqlLeagueRepository(live_sql_database.connection_factory)
    league_input = _league_input("12345", name="Home League")
    now = _now()

    first_result = repository.create_or_attach_league(user_one, league_input, now)
    second_result = repository.create_or_attach_league(user_two, league_input, now)

    assert first_result.canonical_league_created is True
    assert first_result.user_league_created is True
    assert first_result.user_league.role == "owner"
    assert second_result.canonical_league_created is False
    assert second_result.user_league_created is True
    assert second_result.user_league.role == "viewer"
    assert second_result.league.id == first_result.league.id
    assert _league_count(live_sql_database, "12345") == 1
    assert _user_league_count(live_sql_database, first_result.league.id) == 2


def test_live_sql_repeated_create_is_idempotent_and_preserves_owner_role(
    live_sql_database,
):
    user_id = str(uuid4())
    live_sql_database.seed_user(user_id, _email("owner"))
    repository = SqlLeagueRepository(live_sql_database.connection_factory)
    league_input = _league_input("owner-league", name="Owner League")

    first_result = repository.create_or_attach_league(user_id, league_input, _now())
    second_result = repository.create_or_attach_league(user_id, league_input, _now())

    assert first_result.canonical_league_created is True
    assert first_result.user_league_created is True
    assert second_result.canonical_league_created is False
    assert second_result.user_league_created is False
    assert second_result.league.id == first_result.league.id
    assert second_result.user_league.id == first_result.user_league.id
    assert second_result.user_league.role == "owner"
    assert _league_count(live_sql_database, "owner-league") == 1
    assert _user_league_count(live_sql_database, first_result.league.id) == 1


def test_live_sql_user_can_belong_to_multiple_leagues_and_read_memberships(
    live_sql_database,
):
    user_id = str(uuid4())
    live_sql_database.seed_user(user_id, _email("multi"))
    repository = SqlLeagueRepository(live_sql_database.connection_factory)

    first_result = repository.create_or_attach_league(
        user_id, _league_input("111", name="Alpha League"), _now()
    )
    second_result = repository.create_or_attach_league(
        user_id, _league_input("222", name="Beta League"), _now()
    )

    memberships = repository.list_user_leagues(user_id)
    assert sorted(membership.league.external_league_id for membership in memberships) == [
        "111",
        "222",
    ]
    assert repository.get_league(first_result.league.id).id == first_result.league.id
    assert repository.get_user_league(user_id, second_result.league.id).role == "owner"
    assert repository.get_user_league(str(uuid4()), second_result.league.id) is None


def test_live_sql_attach_by_id_requires_matching_platform_and_external_id(
    live_sql_database,
):
    owner_id = str(uuid4())
    viewer_id = str(uuid4())
    live_sql_database.seed_user(owner_id, _email("owner"))
    live_sql_database.seed_user(viewer_id, _email("viewer"))
    repository = SqlLeagueRepository(live_sql_database.connection_factory)
    created = repository.create_or_attach_league(
        owner_id,
        _league_input("secure-league", name="Secure League"),
        _now(),
    )

    with pytest.raises(LeagueAttachMismatchError):
        repository.attach_to_league(
            viewer_id,
            created.league.id,
            LeagueIdentityInput(platform="espn", external_league_id="wrong-league"),
            _now(),
        )

    attached = repository.attach_to_league(
        viewer_id,
        created.league.id,
        LeagueIdentityInput(platform="espn", external_league_id="secure-league"),
        _now(),
    )
    repeated = repository.attach_to_league(
        viewer_id,
        created.league.id,
        LeagueIdentityInput(platform="espn", external_league_id="secure-league"),
        _now(),
    )

    assert attached.user_league_created is True
    assert attached.user_league.role == "viewer"
    assert repeated.user_league_created is False
    assert repeated.user_league.id == attached.user_league.id
    assert _user_league_count(live_sql_database, created.league.id) == 2


def test_live_sql_create_failure_rolls_back_partial_work(live_sql_database):
    repository = SqlLeagueRepository(live_sql_database.connection_factory)
    missing_user_id = str(uuid4())

    with pytest.raises(Exception):
        repository.create_or_attach_league(
            missing_user_id,
            _league_input("rollback-league", name="Rollback League"),
            _now(),
        )

    assert _league_count(live_sql_database, "rollback-league") == 0


def _league_input(external_league_id: str, name: str) -> LeagueInput:
    return LeagueInput(
        platform="espn",
        external_league_id=external_league_id,
        name=name,
        scoring_type="ppr",
        is_private=True,
        timezone="America/New_York",
        first_season=2022,
        last_season=2025,
    )


def _now() -> datetime:
    return datetime(2026, 4, 22, 12, 0, tzinfo=UTC)


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}@example.com"


def _league_count(live_sql_database, external_league_id: str) -> int:
    return int(
        live_sql_database.scalar(
            """
            SELECT COUNT(*)
            FROM dbo.leagues
            WHERE platform = N'espn' AND external_league_id = ?
            """,
            external_league_id,
        )
    )


def _user_league_count(live_sql_database, league_id: str) -> int:
    return int(
        live_sql_database.scalar(
            """
            SELECT COUNT(*)
            FROM dbo.user_leagues
            WHERE league_id = ?
            """,
            league_id,
        )
    )
