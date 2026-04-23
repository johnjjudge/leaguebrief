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
from leaguebrief.credentials import (
    CredentialSecretReferences,
    LeagueCredentialRecord,
    LeagueCredentialUpsertResult,
)
from leaguebrief.jobs import ImportJobInput, ImportJobRecord
from leaguebrief.leagues import (
    LeagueAccessDeniedError,
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


class _InMemoryCredentialRepository:
    def __init__(self, league_repository):
        self.league_repository = league_repository
        self.credentials = {}
        self.secret_references = {}

    def require_user_league_access(self, user_id: str, league_id: str) -> None:
        if self.league_repository.get_league(league_id) is None:
            raise LeagueNotFoundError("League not found.")
        if self.league_repository.get_user_league(user_id, league_id) is None:
            raise LeagueAccessDeniedError("User does not have access to this league.")

    def upsert_espn_cookie_pair(
        self,
        user_id: str,
        league_id: str,
        secret_references: CredentialSecretReferences,
        now: datetime,
    ):
        self.require_user_league_access(user_id, league_id)

        key = (user_id, league_id)
        created = key not in self.credentials
        if created:
            credential = LeagueCredentialRecord(
                id=str(uuid4()),
                league_id=league_id,
                user_id=user_id,
                credential_type="espn_cookie_pair",
                status="active",
                is_preferred_for_refresh=True,
                last_verified_at=None,
                created_at=now,
                updated_at=now,
            )
        else:
            existing = self.credentials[key]
            credential = LeagueCredentialRecord(
                id=existing.id,
                league_id=existing.league_id,
                user_id=existing.user_id,
                credential_type=existing.credential_type,
                status="active",
                is_preferred_for_refresh=True,
                last_verified_at=existing.last_verified_at,
                created_at=existing.created_at,
                updated_at=now,
            )

        self.credentials[key] = credential
        self.secret_references[key] = secret_references
        return LeagueCredentialUpsertResult(credential=credential, created=created)


class _InMemorySecretStore:
    def __init__(self):
        self.secrets = {}

    def set_secret(self, name: str, value: str) -> None:
        self.secrets[name] = value


class _InMemoryImportJobRepository:
    def __init__(self, league_repository):
        self.league_repository = league_repository
        self.jobs = {}
        self.events = []

    def create_import_job_for_authorized_user(
        self,
        user_id: str,
        league_id: str,
        job_input: ImportJobInput,
        now: datetime,
    ):
        if self.league_repository.get_league(league_id) is None:
            raise LeagueNotFoundError("League not found.")
        if self.league_repository.get_user_league(user_id, league_id) is None:
            raise LeagueAccessDeniedError("User does not have access to this league.")

        job = ImportJobRecord(
            id=str(uuid4()),
            league_id=league_id,
            requested_by_user_id=user_id,
            job_type=job_input.job_type,
            status="queued",
            current_phase=None,
            priority=job_input.priority,
            requested_seasons=job_input.requested_seasons,
            started_at=None,
            completed_at=None,
            last_heartbeat_at=None,
            error_summary=None,
            created_at=now,
        )
        self.jobs[job.id] = job
        self.events.append((job.id, "job_queued"))
        return job

    def mark_job_enqueue_failed(self, job_id: str, error_summary: str, now: datetime):
        job = self.jobs[job_id]
        self.jobs[job_id] = ImportJobRecord(
            id=job.id,
            league_id=job.league_id,
            requested_by_user_id=job.requested_by_user_id,
            job_type=job.job_type,
            status="failed",
            current_phase="finalize",
            priority=job.priority,
            requested_seasons=job.requested_seasons,
            started_at=job.started_at,
            completed_at=now,
            last_heartbeat_at=now,
            error_summary=error_summary,
            created_at=job.created_at,
        )
        self.events.append((job_id, "job_enqueue_failed"))


class _InMemoryImportJobQueue:
    def __init__(self):
        self.messages = []

    def enqueue(self, message: str) -> None:
        self.messages.append(json.loads(message))


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


def test_submit_credentials_stores_secret_values_outside_sql_repository(monkeypatch):
    _, league_repository = _patch_repositories(monkeypatch)
    credential_repository, secret_store = _patch_credential_dependencies(
        monkeypatch,
        league_repository,
    )
    create_response = function_app.create_league(
        _request("user-one", _league_body("111", name="Private League"))
    )
    league_id = json.loads(create_response.get_body())["league"]["id"]

    response = function_app.submit_league_credentials(
        _request(
            "user-one",
            {"espnS2": "raw-s2-cookie", "SWID": "{raw-swid-cookie}"},
            {"leagueId": league_id},
        )
    )

    payload = json.loads(response.get_body())
    assert response.status_code == 201
    assert payload["credential"]["leagueId"] == league_id
    assert "raw-s2-cookie" not in response.get_body().decode("utf-8")
    assert "{raw-swid-cookie}" not in response.get_body().decode("utf-8")
    assert set(secret_store.secrets.values()) == {"raw-s2-cookie", "{raw-swid-cookie}"}
    references = next(iter(credential_repository.secret_references.values()))
    assert references.key_vault_secret_name_s2 in secret_store.secrets
    assert references.key_vault_secret_name_swid in secret_store.secrets
    assert references.key_vault_secret_name_s2 != "raw-s2-cookie"
    assert references.key_vault_secret_name_swid != "{raw-swid-cookie}"


def test_submit_credentials_requires_user_league_authorization(monkeypatch):
    _, league_repository = _patch_repositories(monkeypatch)
    _patch_credential_dependencies(monkeypatch, league_repository)
    create_response = function_app.create_league(
        _request("user-one", _league_body("111", name="Private League"))
    )
    league_id = json.loads(create_response.get_body())["league"]["id"]

    response = function_app.submit_league_credentials(
        _request(
            "user-two",
            {"espn_s2": "raw-s2-cookie", "swid": "{raw-swid-cookie}"},
            {"leagueId": league_id},
        )
    )

    assert response.status_code == 403
    assert json.loads(response.get_body())["error"] == "forbidden"


def test_create_import_creates_job_and_queue_message(monkeypatch):
    _, league_repository = _patch_repositories(monkeypatch)
    job_repository, job_queue = _patch_import_job_dependencies(monkeypatch, league_repository)
    create_response = function_app.create_league(
        _request("user-one", _league_body("111", name="Private League"))
    )
    league_id = json.loads(create_response.get_body())["league"]["id"]

    response = function_app.create_import(
        _request(
            "user-one",
            {
                "jobType": "refresh_current_data",
                "requestedSeasons": [2022, 2023],
                "priority": 3,
            },
            {"leagueId": league_id},
        )
    )

    payload = json.loads(response.get_body())
    assert response.status_code == 202
    assert payload["job"]["status"] == "queued"
    assert payload["job"]["jobType"] == "refresh_current_data"
    assert payload["job"]["requestedSeasons"] == [2022, 2023]
    assert len(job_repository.jobs) == 1
    assert len(job_queue.messages) == 1
    assert job_queue.messages[0]["schemaVersion"] == 1
    assert job_queue.messages[0]["jobId"] == payload["job"]["id"]
    assert job_queue.messages[0]["leagueId"] == league_id
    assert "raw-s2" not in json.dumps(job_queue.messages[0])
    assert "key_vault" not in json.dumps(job_queue.messages[0])


def test_create_import_rejects_unsupported_job_type(monkeypatch):
    _, league_repository = _patch_repositories(monkeypatch)
    _patch_import_job_dependencies(monkeypatch, league_repository)
    create_response = function_app.create_league(
        _request("user-one", _league_body("111", name="Private League"))
    )
    league_id = json.loads(create_response.get_body())["league"]["id"]

    response = function_app.create_import(
        _request("user-one", {"jobType": "sync_everything"}, {"leagueId": league_id})
    )

    assert response.status_code == 400
    assert json.loads(response.get_body())["error"] == "bad_request"


def test_create_import_rejects_pre_2015_requested_season(monkeypatch):
    _, league_repository = _patch_repositories(monkeypatch)
    _patch_import_job_dependencies(monkeypatch, league_repository)
    create_response = function_app.create_league(
        _request("user-one", _league_body("111", name="Private League"))
    )
    league_id = json.loads(create_response.get_body())["league"]["id"]

    response = function_app.create_import(
        _request(
            "user-one",
            {"jobType": "initial_import", "requestedSeasons": [2014]},
            {"leagueId": league_id},
        )
    )

    assert response.status_code == 400
    assert json.loads(response.get_body())["message"] == "requestedSeasons must be 2015 or later."


def test_create_import_requires_user_league_authorization(monkeypatch):
    _, league_repository = _patch_repositories(monkeypatch)
    _patch_import_job_dependencies(monkeypatch, league_repository)
    create_response = function_app.create_league(
        _request("user-one", _league_body("111", name="Private League"))
    )
    league_id = json.loads(create_response.get_body())["league"]["id"]

    response = function_app.create_import(
        _request("user-two", {"jobType": "initial_import"}, {"leagueId": league_id})
    )

    assert response.status_code == 403
    assert json.loads(response.get_body())["error"] == "forbidden"


def test_create_league_rejects_non_espn_platform(monkeypatch):
    _patch_repositories(monkeypatch)

    response = function_app.create_league(
        _request("user-one", {"platform": "yahoo", "externalLeagueId": "1", "name": "No"})
    )

    assert response.status_code == 400
    assert json.loads(response.get_body())["error"] == "bad_request"


def test_create_league_rejects_pre_2015_season(monkeypatch):
    _patch_repositories(monkeypatch)
    body = _league_body("111", name="Old League")
    body["firstSeason"] = 2014

    response = function_app.create_league(_request("user-one", body))

    assert response.status_code == 400
    assert json.loads(response.get_body())["message"] == "firstSeason must be 2015 or later."


def _patch_repositories(monkeypatch):
    user_repository = _InMemoryUserRepository()
    league_repository = _InMemoryLeagueRepository()
    monkeypatch.setattr(function_app, "get_user_repository", lambda: user_repository)
    monkeypatch.setattr(function_app, "get_league_repository", lambda: league_repository)
    return user_repository, league_repository


def _patch_credential_dependencies(monkeypatch, league_repository):
    credential_repository = _InMemoryCredentialRepository(league_repository)
    secret_store = _InMemorySecretStore()
    monkeypatch.setattr(
        function_app,
        "get_credential_repository",
        lambda: credential_repository,
    )
    monkeypatch.setattr(function_app, "get_secret_store", lambda: secret_store)
    return credential_repository, secret_store


def _patch_import_job_dependencies(monkeypatch, league_repository):
    job_repository = _InMemoryImportJobRepository(league_repository)
    job_queue = _InMemoryImportJobQueue()
    monkeypatch.setattr(function_app, "get_import_job_repository", lambda: job_repository)
    monkeypatch.setattr(function_app, "get_import_job_queue", lambda: job_queue)
    return job_repository, job_queue


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
