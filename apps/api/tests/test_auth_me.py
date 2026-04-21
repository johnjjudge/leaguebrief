import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import function_app
from leaguebrief.auth import (
    AuthConflictError,
    AuthenticatedPrincipal,
    AuthenticatedUser,
    ProviderAccountRecord,
    UserDisabledError,
    UserRecord,
    authenticate_current_user,
    parse_client_principal_header,
)


class _Request:
    def __init__(self, headers):
        self.headers = headers


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
            user["display_name"] = principal.display_name or user["display_name"]
            user["profile_image_url"] = principal.profile_image_url or user["profile_image_url"]
            user["updated_at"] = login_at
            user["last_login_at"] = login_at
            provider.update(
                {
                    "email": principal.email,
                    "email_verified": principal.email_verified,
                    "last_login_at": login_at,
                }
            )
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
            if user["status"] == "disabled":
                raise UserDisabledError("User is disabled.")
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

        user["last_login_at"] = login_at
        user["updated_at"] = login_at
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

    def disable_email(self, email):
        for user in self.users.values():
            if user["primary_email"] == email:
                user["status"] = "disabled"

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


def test_parse_google_client_principal():
    principal = parse_client_principal_header(
        {"x-ms-client-principal": _encoded_principal("google", "google-123")}
    )

    assert principal.provider == "google"
    assert principal.raw_provider == "google"
    assert principal.provider_subject == "google-123"
    assert principal.email == "user@example.com"
    assert principal.email_verified is True


def test_parse_microsoft_client_principal():
    principal = parse_client_principal_header(
        {"x-ms-client-principal": _encoded_principal("aad", "aad-123")}
    )

    assert principal.provider == "microsoft"
    assert principal.raw_provider == "aad"
    assert principal.provider_subject == "aad-123"


def test_me_returns_401_for_missing_principal(monkeypatch):
    monkeypatch.setattr(function_app, "get_user_repository", _InMemoryUserRepository)

    response = function_app.me(_Request({}))

    assert response.status_code == 401
    assert json.loads(response.get_body())["error"] == "unauthorized"


def test_me_returns_401_for_malformed_principal(monkeypatch):
    monkeypatch.setattr(function_app, "get_user_repository", _InMemoryUserRepository)

    response = function_app.me(_Request({"x-ms-client-principal": "not base64"}))

    assert response.status_code == 401


def test_me_returns_401_for_unauthenticated_principal(monkeypatch):
    monkeypatch.setattr(function_app, "get_user_repository", _InMemoryUserRepository)

    response = function_app.me(
        _Request(
            {
                "x-ms-client-principal": _encoded_principal(
                    "google", "google-123", roles=["anonymous"]
                )
            }
        )
    )

    assert response.status_code == 401


def test_me_returns_401_for_unknown_provider(monkeypatch):
    monkeypatch.setattr(function_app, "get_user_repository", _InMemoryUserRepository)

    response = function_app.me(
        _Request({"x-ms-client-principal": _encoded_principal("github", "gh-123")})
    )

    assert response.status_code == 401


def test_current_user_is_created_and_provider_account_is_returned():
    repository = _InMemoryUserRepository()
    now = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)

    payload = authenticate_current_user(
        {"x-ms-client-principal": _encoded_principal("google", "google-123")},
        repository,
        now=now,
    )

    assert payload["user"]["primaryEmail"] == "user@example.com"
    assert payload["user"]["status"] == "active"
    assert payload["user"]["lastLoginAt"] == "2026-04-21T12:00:00Z"
    assert payload["authProvider"]["provider"] == "google"
    assert payload["authProvider"]["emailVerified"] is True
    assert len(repository.users) == 1


def test_existing_provider_login_updates_internal_user():
    repository = _InMemoryUserRepository()
    first_login_at = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
    second_login_at = datetime(2026, 4, 21, 13, 0, tzinfo=UTC)

    first_payload = authenticate_current_user(
        {"x-ms-client-principal": _encoded_principal("google", "google-123")},
        repository,
        now=first_login_at,
    )
    second_payload = authenticate_current_user(
        {"x-ms-client-principal": _encoded_principal("google", "google-123")},
        repository,
        now=second_login_at,
    )

    assert second_payload["user"]["id"] == first_payload["user"]["id"]
    assert second_payload["user"]["lastLoginAt"] == "2026-04-21T13:00:00Z"
    assert len(repository.users) == 1
    assert len(repository.provider_accounts) == 1


def test_second_provider_same_email_attaches_to_existing_user():
    repository = _InMemoryUserRepository()
    now = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)

    google_payload = authenticate_current_user(
        {"x-ms-client-principal": _encoded_principal("google", "google-123")},
        repository,
        now=now,
    )
    microsoft_payload = authenticate_current_user(
        {"x-ms-client-principal": _encoded_principal("aad", "aad-123")},
        repository,
        now=now,
    )

    assert microsoft_payload["user"]["id"] == google_payload["user"]["id"]
    assert microsoft_payload["authProvider"]["provider"] == "microsoft"
    assert len(repository.users) == 1
    assert len(repository.provider_accounts) == 2


def test_me_returns_403_for_disabled_user(monkeypatch):
    repository = _InMemoryUserRepository()
    authenticate_current_user(
        {"x-ms-client-principal": _encoded_principal("google", "google-123")},
        repository,
        now=datetime(2026, 4, 21, 12, 0, tzinfo=UTC),
    )
    repository.disable_email("user@example.com")
    monkeypatch.setattr(function_app, "get_user_repository", lambda: repository)

    response = function_app.me(
        _Request({"x-ms-client-principal": _encoded_principal("google", "google-123")})
    )

    assert response.status_code == 403
    assert json.loads(response.get_body())["error"] == "forbidden"


def test_me_returns_200_payload(monkeypatch):
    repository = _InMemoryUserRepository()
    monkeypatch.setattr(function_app, "get_user_repository", lambda: repository)

    response = function_app.me(
        _Request({"x-ms-client-principal": _encoded_principal("google", "google-123")})
    )

    assert response.status_code == 200
    payload = json.loads(response.get_body())
    assert payload["user"]["primaryEmail"] == "user@example.com"
    assert payload["authProvider"]["provider"] == "google"


def _encoded_principal(provider, user_id, roles=None):
    payload = {
        "identityProvider": provider,
        "userId": user_id,
        "userDetails": "User@Example.com",
        "userRoles": roles or ["anonymous", "authenticated"],
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
