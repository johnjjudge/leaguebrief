from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

SUPPORTED_LEAGUE_PLATFORMS = {"espn"}
MIN_SUPPORTED_LEAGUE_SEASON = 2015


class LeagueValidationError(ValueError):
    """Raised when a league request payload is invalid."""


class LeagueNotFoundError(RuntimeError):
    """Raised when a canonical league does not exist."""


class LeagueAccessDeniedError(RuntimeError):
    """Raised when a user is not attached to a league."""


class LeagueAttachMismatchError(RuntimeError):
    """Raised when attach proof does not match the canonical league."""


@dataclass(frozen=True)
class LeagueInput:
    platform: str
    external_league_id: str
    name: str
    scoring_type: str | None
    is_private: bool
    timezone: str | None
    first_season: int | None
    last_season: int | None


@dataclass(frozen=True)
class LeagueIdentityInput:
    platform: str
    external_league_id: str


@dataclass(frozen=True)
class LeagueRecord:
    id: str
    platform: str
    external_league_id: str
    name: str
    scoring_type: str | None
    is_private: bool
    timezone: str | None
    first_season: int | None
    last_season: int | None
    created_by_user_id: str
    data_completeness_status: str
    last_imported_at: datetime | None
    last_computed_at: datetime | None
    last_successful_refresh_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserLeagueRecord:
    id: str
    user_id: str
    league_id: str
    role: str
    joined_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class LeagueMembership:
    league: LeagueRecord
    user_league: UserLeagueRecord


@dataclass(frozen=True)
class LeagueAttachResult:
    league: LeagueRecord
    user_league: UserLeagueRecord
    canonical_league_created: bool
    user_league_created: bool


class LeagueRepository(Protocol):
    def create_or_attach_league(
        self,
        user_id: str,
        league_input: LeagueInput,
        now: datetime,
    ) -> LeagueAttachResult:
        ...

    def attach_to_league(
        self,
        user_id: str,
        league_id: str,
        league_identity: LeagueIdentityInput,
        now: datetime,
    ) -> LeagueAttachResult:
        ...

    def list_user_leagues(self, user_id: str) -> Sequence[LeagueMembership]:
        ...

    def get_league(self, league_id: str) -> LeagueRecord | None:
        ...

    def get_user_league(self, user_id: str, league_id: str) -> UserLeagueRecord | None:
        ...


class LeagueService:
    def __init__(self, repository: LeagueRepository) -> None:
        self._repository = repository

    def create_or_attach_league(
        self,
        user_id: str,
        payload: Mapping[str, object],
        now: datetime | None = None,
    ) -> dict[str, object]:
        result = self._repository.create_or_attach_league(
            user_id=user_id,
            league_input=parse_league_input(payload),
            now=now or datetime.now(UTC),
        )
        return serialize_attach_result(result)

    def attach_to_league(
        self,
        user_id: str,
        league_id: str,
        payload: Mapping[str, object],
        now: datetime | None = None,
    ) -> dict[str, object]:
        league_id = _validate_league_id(league_id)
        result = self._repository.attach_to_league(
            user_id=user_id,
            league_id=league_id,
            league_identity=parse_league_identity_input(payload),
            now=now or datetime.now(UTC),
        )
        return serialize_attach_result(result)

    def list_user_leagues(self, user_id: str) -> dict[str, object]:
        memberships = self._repository.list_user_leagues(user_id)
        return {
            "leagues": [
                serialize_league_membership(membership) for membership in memberships
            ]
        }

    def get_authorized_league(self, user_id: str, league_id: str) -> dict[str, object]:
        league_id = _validate_league_id(league_id)
        league = self._repository.get_league(league_id)
        if league is None:
            raise LeagueNotFoundError("League not found.")

        user_league = self._repository.get_user_league(user_id, league_id)
        if user_league is None:
            raise LeagueAccessDeniedError("User does not have access to this league.")

        return serialize_league_membership(
            LeagueMembership(league=league, user_league=user_league)
        )


def parse_league_input(payload: Mapping[str, object]) -> LeagueInput:
    platform = _require_string(payload, "platform").lower()
    _validate_platform(platform)

    external_league_id = _require_string(payload, "externalLeagueId")
    name = _require_string(payload, "name")
    first_season = _optional_int(payload.get("firstSeason"), "firstSeason")
    last_season = _optional_int(payload.get("lastSeason"), "lastSeason")
    _validate_season_range(first_season, last_season)

    return LeagueInput(
        platform=platform,
        external_league_id=external_league_id,
        name=name,
        scoring_type=_optional_string(payload.get("scoringType")),
        is_private=_optional_bool(payload.get("isPrivate"), "isPrivate") or False,
        timezone=_optional_string(payload.get("timezone")),
        first_season=first_season,
        last_season=last_season,
    )


def parse_league_identity_input(payload: Mapping[str, object]) -> LeagueIdentityInput:
    platform = _require_string(payload, "platform").lower()
    _validate_platform(platform)
    return LeagueIdentityInput(
        platform=platform,
        external_league_id=_require_string(payload, "externalLeagueId"),
    )


def serialize_attach_result(result: LeagueAttachResult) -> dict[str, object]:
    return {
        "league": serialize_league(result.league),
        "userLeague": serialize_user_league(result.user_league),
        "canonicalLeagueCreated": result.canonical_league_created,
        "userLeagueCreated": result.user_league_created,
    }


def serialize_league_membership(membership: LeagueMembership) -> dict[str, object]:
    return {
        "league": serialize_league(membership.league),
        "userLeague": serialize_user_league(membership.user_league),
    }


def serialize_league(league: LeagueRecord) -> dict[str, object]:
    return {
        "id": league.id,
        "platform": league.platform,
        "externalLeagueId": league.external_league_id,
        "name": league.name,
        "scoringType": league.scoring_type,
        "isPrivate": league.is_private,
        "timezone": league.timezone,
        "firstSeason": league.first_season,
        "lastSeason": league.last_season,
        "createdByUserId": league.created_by_user_id,
        "dataCompletenessStatus": league.data_completeness_status,
        "lastImportedAt": _isoformat(league.last_imported_at),
        "lastComputedAt": _isoformat(league.last_computed_at),
        "lastSuccessfulRefreshAt": _isoformat(league.last_successful_refresh_at),
        "createdAt": _isoformat(league.created_at),
        "updatedAt": _isoformat(league.updated_at),
    }


def serialize_user_league(user_league: UserLeagueRecord) -> dict[str, object]:
    return {
        "id": user_league.id,
        "userId": user_league.user_id,
        "leagueId": user_league.league_id,
        "role": user_league.role,
        "joinedAt": _isoformat(user_league.joined_at),
        "createdAt": _isoformat(user_league.created_at),
    }


def _validate_platform(platform: str) -> None:
    if platform not in SUPPORTED_LEAGUE_PLATFORMS:
        raise LeagueValidationError("Only ESPN leagues are supported.")


def _validate_season_range(first_season: int | None, last_season: int | None) -> None:
    if first_season is not None and first_season < MIN_SUPPORTED_LEAGUE_SEASON:
        raise LeagueValidationError("firstSeason must be 2015 or later.")
    if last_season is not None and last_season < MIN_SUPPORTED_LEAGUE_SEASON:
        raise LeagueValidationError("lastSeason must be 2015 or later.")
    if first_season is not None and last_season is not None and first_season > last_season:
        raise LeagueValidationError("firstSeason cannot be after lastSeason.")


def _validate_league_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise LeagueValidationError("leagueId must be a valid UUID.") from exc


def _require_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LeagueValidationError(f"{key} is required.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is None:
        return None
    raise LeagueValidationError("Optional text fields must be strings.")


def _optional_bool(value: object, key: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise LeagueValidationError(f"{key} must be a boolean.")


def _optional_int(value: object, key: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise LeagueValidationError(f"{key} must be an integer.")
    return value


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
