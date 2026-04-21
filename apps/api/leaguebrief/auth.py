from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SUPPORTED_PROVIDERS = {
    "google": "google",
    "aad": "microsoft",
    "azureactivedirectory": "microsoft",
}


class AuthenticationError(RuntimeError):
    """Raised when a request does not contain a valid authenticated principal."""


class UserDisabledError(RuntimeError):
    """Raised when the authenticated principal maps to a disabled internal user."""


class AuthConflictError(RuntimeError):
    """Raised when a principal cannot be safely linked to an internal user."""


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    provider: str
    raw_provider: str
    provider_subject: str
    email: str
    email_verified: bool
    display_name: str | None
    profile_image_url: str | None


@dataclass(frozen=True)
class UserRecord:
    id: str
    primary_email: str
    display_name: str | None
    profile_image_url: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


@dataclass(frozen=True)
class ProviderAccountRecord:
    id: str
    provider: str
    email: str
    email_verified: bool
    last_login_at: datetime | None


@dataclass(frozen=True)
class AuthenticatedUser:
    user: UserRecord
    provider_account: ProviderAccountRecord


class UserRepository(Protocol):
    def upsert_from_principal(
        self, principal: AuthenticatedPrincipal, login_at: datetime
    ) -> AuthenticatedUser:
        ...


def parse_client_principal_header(
    headers: Mapping[str, str] | object,
) -> AuthenticatedPrincipal:
    header_value = _get_header(headers, "x-ms-client-principal")
    if not header_value:
        raise AuthenticationError("Missing Static Web Apps client principal.")

    try:
        padded = header_value + ("=" * (-len(header_value) % 4))
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
        payload = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthenticationError("Invalid Static Web Apps client principal.") from exc

    raw_provider = _require_string(payload, "identityProvider")
    provider = SUPPORTED_PROVIDERS.get(raw_provider.lower())
    if not provider:
        raise AuthenticationError("Unsupported identity provider.")

    roles = _string_sequence(payload.get("userRoles"))
    if "authenticated" not in {role.lower() for role in roles}:
        raise AuthenticationError("Principal is not authenticated.")

    provider_subject = _require_string(payload, "userId")
    email = _require_string(payload, "userDetails").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthenticationError("Authenticated principal does not include an email.")

    display_name = _optional_string(payload.get("displayName")) or email
    profile_image_url = _optional_string(payload.get("profileImageUrl"))

    return AuthenticatedPrincipal(
        provider=provider,
        raw_provider=raw_provider,
        provider_subject=provider_subject,
        email=email,
        email_verified=True,
        display_name=display_name,
        profile_image_url=profile_image_url,
    )


def authenticate_current_user(
    headers: Mapping[str, str] | object,
    repository: UserRepository,
    now: datetime | None = None,
) -> dict[str, object]:
    principal = parse_client_principal_header(headers)
    login_at = now or datetime.now(UTC)
    authenticated_user = repository.upsert_from_principal(principal, login_at)
    return serialize_authenticated_user(authenticated_user)


def serialize_authenticated_user(authenticated_user: AuthenticatedUser) -> dict[str, object]:
    user = authenticated_user.user
    provider_account = authenticated_user.provider_account
    return {
        "user": {
            "id": user.id,
            "primaryEmail": user.primary_email,
            "displayName": user.display_name,
            "profileImageUrl": user.profile_image_url,
            "status": user.status,
            "createdAt": _isoformat(user.created_at),
            "updatedAt": _isoformat(user.updated_at),
            "lastLoginAt": _isoformat(user.last_login_at),
        },
        "authProvider": {
            "id": provider_account.id,
            "provider": provider_account.provider,
            "email": provider_account.email,
            "emailVerified": provider_account.email_verified,
            "lastLoginAt": _isoformat(provider_account.last_login_at),
        },
    }


def _get_header(headers: Mapping[str, str] | object, name: str) -> str | None:
    if hasattr(headers, "get"):
        value = headers.get(name)  # type: ignore[attr-defined]
        if value is None:
            value = headers.get(name.upper())  # type: ignore[attr-defined]
        if value is not None:
            return str(value)

    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if key.lower() == name:
                return str(value)

    return None


def _require_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AuthenticationError(f"Missing {key} in client principal.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_sequence(value: object) -> Sequence[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
