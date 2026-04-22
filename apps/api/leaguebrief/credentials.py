from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID


class CredentialValidationError(ValueError):
    """Raised when a credential request payload is invalid."""


class CredentialSecretStoreError(RuntimeError):
    """Raised when private credential values cannot be stored safely."""


@dataclass(frozen=True)
class EspnCredentialInput:
    espn_s2: str
    swid: str


@dataclass(frozen=True)
class CredentialSecretReferences:
    key_vault_secret_name_s2: str
    key_vault_secret_name_swid: str


@dataclass(frozen=True)
class LeagueCredentialRecord:
    id: str
    league_id: str
    user_id: str
    credential_type: str
    status: str
    is_preferred_for_refresh: bool
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class LeagueCredentialUpsertResult:
    credential: LeagueCredentialRecord
    created: bool


class SecretStore(Protocol):
    def set_secret(self, name: str, value: str) -> None:
        ...


class CredentialRepository(Protocol):
    def require_user_league_access(self, user_id: str, league_id: str) -> None:
        ...

    def upsert_espn_cookie_pair(
        self,
        user_id: str,
        league_id: str,
        secret_references: CredentialSecretReferences,
        now: datetime,
    ) -> LeagueCredentialUpsertResult:
        ...


class CredentialService:
    def __init__(
        self,
        repository: CredentialRepository,
        secret_store: SecretStore,
    ) -> None:
        self._repository = repository
        self._secret_store = secret_store

    def submit_espn_credentials(
        self,
        user_id: str,
        league_id: str,
        payload: Mapping[str, object],
        now: datetime | None = None,
    ) -> dict[str, object]:
        league_id = _validate_uuid(league_id, "leagueId")
        user_id = _validate_uuid(user_id, "userId")
        credential_input = parse_espn_credential_input(payload)
        timestamp = now or datetime.now(UTC)
        secret_references = build_secret_references(league_id, user_id)

        self._repository.require_user_league_access(user_id, league_id)
        try:
            self._secret_store.set_secret(
                secret_references.key_vault_secret_name_s2,
                credential_input.espn_s2,
            )
            self._secret_store.set_secret(
                secret_references.key_vault_secret_name_swid,
                credential_input.swid,
            )
        except Exception as exc:
            raise CredentialSecretStoreError(
                "Failed to store ESPN credential secrets."
            ) from exc

        result = self._repository.upsert_espn_cookie_pair(
            user_id=user_id,
            league_id=league_id,
            secret_references=secret_references,
            now=timestamp,
        )
        return serialize_credential_upsert_result(result)


def parse_espn_credential_input(payload: Mapping[str, object]) -> EspnCredentialInput:
    return EspnCredentialInput(
        espn_s2=_require_one_string(payload, ("espnS2", "espn_s2")),
        swid=_require_one_string(payload, ("swid", "SWID")),
    )


def build_secret_references(league_id: str, user_id: str) -> CredentialSecretReferences:
    return CredentialSecretReferences(
        key_vault_secret_name_s2=f"lb-espn-s2-{league_id}-{user_id}".lower(),
        key_vault_secret_name_swid=f"lb-espn-swid-{league_id}-{user_id}".lower(),
    )


def serialize_credential_upsert_result(
    result: LeagueCredentialUpsertResult,
) -> dict[str, object]:
    return {
        "credential": serialize_credential(result.credential),
        "created": result.created,
    }


def serialize_credential(credential: LeagueCredentialRecord) -> dict[str, object]:
    return {
        "id": credential.id,
        "leagueId": credential.league_id,
        "userId": credential.user_id,
        "credentialType": credential.credential_type,
        "status": credential.status,
        "isPreferredForRefresh": credential.is_preferred_for_refresh,
        "lastVerifiedAt": _isoformat(credential.last_verified_at),
        "createdAt": _isoformat(credential.created_at),
        "updatedAt": _isoformat(credential.updated_at),
    }


def _require_one_string(payload: Mapping[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise CredentialValidationError(f"{keys[0]} is required.")


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise CredentialValidationError(f"{field_name} must be a valid UUID.") from exc


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
