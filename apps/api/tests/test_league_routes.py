import base64
import json
from datetime import datetime
from uuid import uuid4

import function_app
from leaguebrief.auth import (
    AuthConflictError,
    AuthenticatedPrincipal,
    AuthenticatedUser,
    ProviderAccountRecord,
    UserDisabledError,
    UserRecord,
)
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


class _Request:
    def __init__(self, headers=None, json_body=None, route_params=None):
        self.headers = headers or {}
        self._json_body = json_body
        self.route_params = route_params or {}

    def get_json(self):
        if isinstance(self._json_body, ValueError):
            raise self._json_body
        return self._json_body


class _InMemoryUserRepository:
    def __init__(self):
        self.users = {}
        self.provider_accounts = {}
        self.user_provider_index = {}

    def upsert_from_principal(self, principal: AuthenticatedPrincipal, login_at: datetime):
        provider_key = (principal.provider, principal.provider_subject)
        provider = self.provider_accounts.get(provider_key)
        if provider:
            user = self.users[provider["user_id"]]
            if user["status"] == "disabled":
                raise UserDisabledError("User is disabled.")
            user["updated_at"] = login_at
            user["last_login_at"] = login_at
            provider["last_login_at"] = login_at
            return self._to_authenticated_user(user, provider)

        user = next(
            (
                existing_user
                for existing_user in self.users.values()
                if existing_user["primary_email"] == principal.email
            ),
            None,
        )
        if user:
            existing_provider = self.user_provider_index.get(
                (user["id"], principal.provider)
            )
            if existing_provider:
                raise AuthConflictError("User already has this provider.")
        else:
            user = {
                "id": str(uuid4()),
                "primary_email": principal.email,
                "display_name": principal.display_name,
                "profile_image_url": principal.profile_image_url,
                "status": "active",
                "created_at": login_at,
                "updated_at": login_at,
                "last_login_at": login_at,
            }
            self.users[user["id"]] = user

        provider = {
            "id": str(uuid4()),
            "user_id": user["id"],
            "provider": principal.provider,
            "email": principal.email,
            "email_verified": principal.email_verified,
            "last_login_at": login_at,
        }
        self.provider_accounts[provider_key] = provider
        self.user_provider_index[(user["id"], principal.provider)] = provider_key
        return self._to_authenticated_user(user, provider)

    def _to_authenticated_user(self, user, provider):
        return AuthenticatedUser(
            user=UserRecord(
                id=user["id"],
                primary_email=user["primary_email"],
                display_name=user["display_name"],
                profile_image_url=user["profile_image_url"],
                status=user["status"],
                created_at=user["created_at"],
                updated_at=user["updated_at"],
                last_login_at=user["last_login_at"],
            ),
            provider_account=ProviderAccountRecord(
                id=provider["id"],
                provider=provider["provider"],
                email=provider["email"],
                email_verified=provider["email_verified"],
                last_login_at=provider["last_login_at"],
            ),
        )


class _InMemoryLeagueRepository:
    def __init__(self):
        self.leagues = {}
        self.league_identity_index = {}
        self.user_leagues = {}

    def create_or_attach_league(
        self,
        user_id: str,
        league_input: LeagueInput,
        now: datetime,
    ):
        identity_key = (league_input.platform, league_input.external_league_id)
        league_id = self.league_identity_index.get(identity_key)
        canonical_created = league_id is None
        if league_id is None:
            league_id = str(uuid4())
            self.league_identity_index[identity_key] = league_id
            self.leagues[league_id] = LeagueRecord(
                id=league_id,
                platform=league_input.platform,
                external_league_id=league_input.external_league_id,
                name=league_input.name,
                scoring_type=league_input.scoring_type,
                is_private=league_input.is_private,
                timezone=league_input.timezone,
                first_season=league_input.first_season,
                last_season=league_input.last_season,
                created_by_user_id=user_id,
                data_completeness_status="not_started",
                last_imported_at=None,
                last_computed_at=None,
                last_successful_refresh_at=None,
                created_at=now,
                updated_at=now,
            )

        user_league, user_league_created = self._ensure_user_league(
            user_id=user_id,
            league_id=league_id,
            role="owner" if canonical_created else "viewer",
            now=now,
        )
        return LeagueAttachResult(
            league=self.leagues[league_id],
            user_league=user_league,
            canonical_league_created=canonical_created,
            user_league_created=user_league_created,
        )

    def attach_to_league(
        self,
        user_id: str,
        league_id: str,
        league_identity: LeagueIdentityInput,
        now: datetime,
    ):
        league = self.leagues.get(league_id)
        if league is None:
            raise LeagueNotFoundError("League not found.")
        if (
            league.platform != league_identity.platform
            or league.external_league_id != league_identity.external_league_id
        ):
            raise LeagueAttachMismatchError(
                "League identity does not match the canonical league."
            )

        user_league, user_league_created = self._ensure_user_league(
            user_id=user_id,
            league_id=league_id,
            role="viewer",
            now=now,
        )
        return LeagueAttachResult(
            league=league,
            user_league=user_league,
            canonical_league_created=False,
            user_league_created=user_league_created,
        )

    def list_user_leagues(self, user_id: str):
        memberships = []
        for user_league in self.user_leagues.values():
            if user_league.user_id == user_id:
                memberships.append(
                    LeagueMembership(
                        league=self.leagues[user_league.league_id],
                        user_league=user_league,
                    )
                )
        return memberships

    def get_league(self, league_id: str):
        return self.leagues.get(league_id)

    def get_user_league(self, user_id: str, league_id: str):
        return self.user_leagues.get((user_id, league_id))

    def _ensure_user_league(self, user_id: str, league_id: str, role: str, now: datetime):
        key = (user_id, league_id)
        existing = self.user_leagues.get(key)
        if existing:
            return existing, False

        user_league = UserLeagueRecord(
            id=str(uuid4()),
            user_id=user_id,
            league_id=league_id,
            role=role,
            joined_at=now,
            created_at=now,
        )
        self.user_leagues[key] = user_league
        return user_league, True


def test_two_users_posting_same_espn_league_share_one_canonical_row(monkeypatch):
    user_repository, league_repository = _patch_repositories(monkeypatch)
    league_body = _league_body("12345", name="Home League")

    first_response = function_app.create_league(_request("user-one", league_body))
    second_response = function_app.create_league(_request("user-two", league_body))

    first_payload = json.loads(first_response.get_body())
    second_payload = json.loads(second_response.get_body())
    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_payload["league"]["id"] == second_payload["league"]["id"]
    assert first_payload["canonicalLeagueCreated"] is True
    assert second_payload["canonicalLeagueCreated"] is False
    assert first_payload["userLeague"]["role"] == "owner"
    assert second_payload["userLeague"]["role"] == "viewer"
    assert len(league_repository.leagues) == 1
    assert len(league_repository.user_leagues) == 2
    assert len(user_repository.users) == 2


def test_user_can_belong_to_multiple_leagues(monkeypatch):
    _patch_repositories(monkeypatch)

    first_response = function_app.create_league(
        _request("user-one", _league_body("111", name="Home League"))
    )
    second_response = function_app.create_league(
        _request("user-one", _league_body("222", name="Office League"))
    )
    list_response = function_app.list_leagues(_request("user-one"))

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    payload = json.loads(list_response.get_body())
    assert sorted(item["league"]["externalLeagueId"] for item in payload["leagues"]) == [
        "111",
        "222",
    ]


def test_repeating_create_for_same_user_is_idempotent(monkeypatch):
    _, league_repository = _patch_repositories(monkeypatch)
    request = _request("user-one", _league_body("12345", name="Home League"))

    first_response = function_app.create_league(request)
    second_response = function_app.create_league(request)

    first_payload = json.loads(first_response.get_body())
    second_payload = json.loads(second_response.get_body())
    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_payload["league"]["id"] == first_payload["league"]["id"]
    assert second_payload["canonicalLeagueCreated"] is False
    assert second_payload["userLeagueCreated"] is False
    assert second_payload["userLeague"]["role"] == "owner"
    assert len(league_repository.leagues) == 1
    assert len(league_repository.user_leagues) == 1


def test_list_leagues_returns_only_current_user_memberships(monkeypatch):
    _patch_repositories(monkeypatch)
    function_app.create_league(_request("user-one", _league_body("111", name="Home")))
    function_app.create_league(_request("user-two", _league_body("222", name="Office")))

    response = function_app.list_leagues(_request("user-one"))

    payload = json.loads(response.get_body())
    assert response.status_code == 200
    assert [item["league"]["externalLeagueId"] for item in payload["leagues"]] == ["111"]


def test_get_league_requires_user_league_authorization(monkeypatch):
    _patch_repositories(monkeypatch)
    create_response = function_app.create_league(
        _request("user-one", _league_body("111", name="Home"))
    )
    league_id = json.loads(create_response.get_body())["league"]["id"]

    authorized_response = function_app.get_league(
        _request("user-one", route_params={"leagueId": league_id})
    )
    unauthorized_response = function_app.get_league(
        _request("user-two", route_params={"leagueId": league_id})
    )

    assert authorized_response.status_code == 200
    assert unauthorized_response.status_code == 403
    assert json.loads(unauthorized_response.get_body())["error"] == "forbidden"


def test_attach_requires_matching_platform_and_external_league_id(monkeypatch):
    _patch_repositories(monkeypatch)
    create_response = function_app.create_league(
        _request("user-one", _league_body("111", name="Home"))
    )
    league_id = json.loads(create_response.get_body())["league"]["id"]

    mismatch_response = function_app.attach_league(
        _request(
            "user-two",
            {"platform": "espn", "externalLeagueId": "999"},
            {"leagueId": league_id},
        )
    )
    attach_response = function_app.attach_league(
        _request(
            "user-two",
            {"platform": "espn", "externalLeagueId": "111"},
            {"leagueId": league_id},
        )
    )
    repeat_response = function_app.attach_league(
        _request(
            "user-two",
            {"platform": "espn", "externalLeagueId": "111"},
            {"leagueId": league_id},
        )
    )

    assert mismatch_response.status_code == 403
    assert attach_response.status_code == 201
    assert repeat_response.status_code == 200
    assert json.loads(attach_response.get_body())["userLeague"]["role"] == "viewer"


def test_create_league_rejects_non_espn_platform(monkeypatch):
    _patch_repositories(monkeypatch)

    response = function_app.create_league(
        _request("user-one", {"platform": "yahoo", "externalLeagueId": "1", "name": "No"})
    )

    assert response.status_code == 400
    assert json.loads(response.get_body())["error"] == "bad_request"


def _patch_repositories(monkeypatch):
    user_repository = _InMemoryUserRepository()
    league_repository = _InMemoryLeagueRepository()
    monkeypatch.setattr(function_app, "get_user_repository", lambda: user_repository)
    monkeypatch.setattr(function_app, "get_league_repository", lambda: league_repository)
    return user_repository, league_repository


def _request(user_id, json_body=None, route_params=None):
    return _Request(
        headers={
            "x-ms-client-principal": _encoded_principal(
                "google",
                user_id,
                f"{user_id}@example.com",
            )
        },
        json_body=json_body,
        route_params=route_params,
    )


def _league_body(external_league_id, name):
    return {
        "platform": "espn",
        "externalLeagueId": external_league_id,
        "name": name,
        "scoringType": "ppr",
        "isPrivate": True,
        "timezone": "America/New_York",
        "firstSeason": 2022,
        "lastSeason": 2025,
    }


def _encoded_principal(provider, user_id, email):
    payload = {
        "identityProvider": provider,
        "userId": user_id,
        "userDetails": email,
        "userRoles": ["anonymous", "authenticated"],
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
