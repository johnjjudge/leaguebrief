from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from leaguebrief_espn_adapter import (
    EspnAdapterError,
    EspnCredentials,
    EspnFantasyClient,
    EspnNotFoundError,
    EspnSnapshotResponse,
)

from leaguebrief_worker.jobs import ImportJobMessage, WorkerRunResult

ESPN_RAW_INGESTION_JOB_TYPES = {"initial_import", "refresh_current_data"}
MAX_SCORING_PERIODS = 25
DEFAULT_SCORING_PERIODS = 18


class EspnRawIngestionError(RuntimeError):
    """Raised when raw ESPN ingestion cannot complete required work."""


@dataclass(frozen=True)
class LeagueForIngestion:
    id: str
    external_league_id: str
    first_season: int | None
    last_season: int | None
    is_private: bool


@dataclass(frozen=True)
class CredentialSecretReference:
    user_id: str
    key_vault_secret_name_s2: str
    key_vault_secret_name_swid: str
    is_preferred_for_refresh: bool


@dataclass(frozen=True)
class OptionalSnapshotFailure:
    season: int
    snapshot_type: str
    message: str


class RawSnapshotRepository(Protocol):
    def get_league_for_ingestion(self, league_id: str) -> LeagueForIngestion | None:
        ...

    def list_credential_secret_references(
        self,
        league_id: str,
        requested_by_user_id: str,
    ) -> Sequence[CredentialSecretReference]:
        ...

    def append_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        payload: Mapping[str, object] | None,
        now: datetime,
    ) -> None:
        ...

    def begin_task(
        self,
        job_id: str,
        task_type: str,
        season: int,
        now: datetime,
    ) -> str:
        ...

    def complete_task(self, task_id: str, now: datetime) -> None:
        ...

    def fail_task(self, task_id: str, error_message: str, now: datetime) -> None:
        ...

    def save_raw_snapshot(
        self,
        league_id: str,
        season: int,
        snapshot_type: str,
        blob_path: str,
        source_hash: str,
        now: datetime,
    ) -> bool:
        ...


class RawPayloadStore(Protocol):
    def upload_json_bytes(self, blob_path: str, payload: bytes) -> None:
        ...


class SecretReader(Protocol):
    def get_secret(self, name: str) -> str:
        ...


class EspnRawIngestionService:
    def __init__(
        self,
        repository: RawSnapshotRepository,
        blob_store: RawPayloadStore,
        secret_reader: SecretReader,
        client_factory: Callable[[], EspnFantasyClient] = EspnFantasyClient,
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store
        self._secret_reader = secret_reader
        self._client_factory = client_factory

    def run(
        self,
        message: ImportJobMessage,
        now: datetime | None = None,
    ) -> WorkerRunResult:
        if message.job_type not in ESPN_RAW_INGESTION_JOB_TYPES:
            return WorkerRunResult.succeeded()

        timestamp = now or datetime.now(UTC)
        league = self._repository.get_league_for_ingestion(message.league_id)
        if league is None:
            raise EspnRawIngestionError("League not found for ESPN ingestion.")

        credentials = self._load_credentials(message)
        client = self._client_factory()
        seasons = self._resolve_seasons(message, league, client, credentials)

        self._repository.append_event(
            message.job_id,
            "espn_raw_ingestion_started",
            "ESPN raw ingestion started.",
            {"seasons": list(seasons)},
            timestamp,
        )

        optional_failures: list[OptionalSnapshotFailure] = []
        for season in seasons:
            meta = self._fetch_store_required(
                message=message,
                league=league,
                season=season,
                snapshot_type="league_meta",
                task_type="fetch_season",
                fetch=lambda season=season: client.fetch_league_meta(
                    league.external_league_id,
                    season,
                    credentials,
                ),
            )
            self._fetch_store_required(
                message=message,
                league=league,
                season=season,
                snapshot_type="matchups",
                task_type="fetch_matchups",
                fetch=lambda season=season: client.fetch_matchups(
                    league.external_league_id,
                    season,
                    credentials,
                ),
            )
            self._fetch_store_optional(
                message=message,
                league=league,
                season=season,
                snapshot_type="draft",
                task_type="fetch_draft",
                fetch=lambda season=season: client.fetch_draft(
                    league.external_league_id,
                    season,
                    credentials,
                ),
                failures=optional_failures,
            )
            self._fetch_store_optional(
                message=message,
                league=league,
                season=season,
                snapshot_type="transactions",
                task_type="fetch_season",
                fetch=lambda season=season: client.fetch_transactions(
                    league.external_league_id,
                    season,
                    credentials,
                ),
                failures=optional_failures,
            )
            self._fetch_store_optional(
                message=message,
                league=league,
                season=season,
                snapshot_type="rosters",
                task_type="fetch_season",
                fetch=lambda season=season, meta=meta: client.fetch_rosters(
                    league.external_league_id,
                    season,
                    _scoring_period_ids(meta.payload),
                    credentials,
                ),
                failures=optional_failures,
            )

        self._repository.append_event(
            message.job_id,
            "espn_raw_ingestion_finished",
            "ESPN raw ingestion finished.",
            {
                "seasons": list(seasons),
                "optionalFailureCount": len(optional_failures),
            },
            timestamp,
        )

        if optional_failures:
            return WorkerRunResult.partial(
                payload={
                    "optionalFailures": [
                        {
                            "season": failure.season,
                            "snapshotType": failure.snapshot_type,
                            "message": failure.message,
                        }
                        for failure in optional_failures
                    ]
                }
            )
        return WorkerRunResult.succeeded()

    def _load_credentials(self, message: ImportJobMessage) -> EspnCredentials | None:
        references = self._repository.list_credential_secret_references(
            message.league_id,
            message.requested_by_user_id,
        )
        for reference in references:
            espn_s2 = self._secret_reader.get_secret(reference.key_vault_secret_name_s2)
            swid = self._secret_reader.get_secret(reference.key_vault_secret_name_swid)
            return EspnCredentials(espn_s2=espn_s2, swid=swid)
        return None

    def _resolve_seasons(
        self,
        message: ImportJobMessage,
        league: LeagueForIngestion,
        client: EspnFantasyClient,
        credentials: EspnCredentials | None,
    ) -> tuple[int, ...]:
        if message.requested_seasons:
            return tuple(sorted(set(message.requested_seasons)))
        if league.first_season is not None and league.last_season is not None:
            if league.first_season > league.last_season:
                raise EspnRawIngestionError("League season range is invalid.")
            return tuple(range(league.first_season, league.last_season + 1))

        try:
            return client.discover_seasons(league.external_league_id, credentials)
        except EspnAdapterError as exc:
            raise EspnRawIngestionError("Unable to discover ESPN league seasons.") from exc

    def _fetch_store_required(
        self,
        message: ImportJobMessage,
        league: LeagueForIngestion,
        season: int,
        snapshot_type: str,
        task_type: str,
        fetch: Callable[[], EspnSnapshotResponse],
    ) -> EspnSnapshotResponse:
        task_id = self._repository.begin_task(
            message.job_id,
            task_type,
            season,
            datetime.now(UTC),
        )
        try:
            response = fetch()
            self._store_response(league, season, snapshot_type, response)
            self._repository.complete_task(task_id, datetime.now(UTC))
            return response
        except Exception as exc:
            self._repository.fail_task(
                task_id,
                _safe_task_error_message(snapshot_type, required=True),
                datetime.now(UTC),
            )
            raise EspnRawIngestionError(
                f"Failed to fetch required ESPN {snapshot_type} snapshot."
            ) from exc

    def _fetch_store_optional(
        self,
        message: ImportJobMessage,
        league: LeagueForIngestion,
        season: int,
        snapshot_type: str,
        task_type: str,
        fetch: Callable[[], EspnSnapshotResponse],
        failures: list[OptionalSnapshotFailure],
    ) -> None:
        task_id = self._repository.begin_task(
            message.job_id,
            task_type,
            season,
            datetime.now(UTC),
        )
        try:
            response = fetch()
            self._store_response(league, season, snapshot_type, response)
            self._repository.complete_task(task_id, datetime.now(UTC))
        except EspnNotFoundError:
            message_text = _safe_task_error_message(snapshot_type, required=False)
            failures.append(
                OptionalSnapshotFailure(
                    season=season,
                    snapshot_type=snapshot_type,
                    message=message_text,
                )
            )
            self._repository.fail_task(task_id, message_text, datetime.now(UTC))
        except EspnAdapterError:
            message_text = _safe_task_error_message(snapshot_type, required=False)
            failures.append(
                OptionalSnapshotFailure(
                    season=season,
                    snapshot_type=snapshot_type,
                    message=message_text,
                )
            )
            self._repository.fail_task(task_id, message_text, datetime.now(UTC))
            self._repository.append_event(
                message.job_id,
                "espn_optional_snapshot_failed",
                message_text,
                {"season": season, "snapshotType": snapshot_type},
                datetime.now(UTC),
            )
            return
        except Exception:
            message_text = _safe_task_error_message(snapshot_type, required=False)
            failures.append(
                OptionalSnapshotFailure(
                    season=season,
                    snapshot_type=snapshot_type,
                    message=message_text,
                )
            )
            self._repository.fail_task(task_id, message_text, datetime.now(UTC))
            self._repository.append_event(
                message.job_id,
                "espn_optional_snapshot_failed",
                message_text,
                {"season": season, "snapshotType": snapshot_type},
                datetime.now(UTC),
            )
            return

    def _store_response(
        self,
        league: LeagueForIngestion,
        season: int,
        snapshot_type: str,
        response: EspnSnapshotResponse,
    ) -> None:
        payload_bytes = _canonical_json_bytes(response.payload)
        source_hash = hashlib.sha256(payload_bytes).hexdigest()
        blob_path = f"espn/{league.id}/{season}/{snapshot_type}/{source_hash}.json"
        self._blob_store.upload_json_bytes(blob_path, payload_bytes)
        self._repository.save_raw_snapshot(
            league_id=league.id,
            season=season,
            snapshot_type=snapshot_type,
            blob_path=blob_path,
            source_hash=source_hash,
            now=datetime.now(UTC),
        )


def _canonical_json_bytes(payload: Mapping[str, Any] | Sequence[Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _scoring_period_ids(payload: Mapping[str, Any] | Sequence[Any]) -> tuple[int, ...]:
    final_scoring_period = _find_int(payload, ("status", "finalScoringPeriod"))
    if final_scoring_period is None:
        final_scoring_period = _find_int(
            payload,
            ("settings", "scheduleSettings", "matchupPeriodCount"),
        )
    if final_scoring_period is None:
        final_scoring_period = DEFAULT_SCORING_PERIODS

    capped = min(max(final_scoring_period, 1), MAX_SCORING_PERIODS)
    return tuple(range(1, capped + 1))


def _find_int(payload: Mapping[str, Any] | Sequence[Any], path: tuple[str, ...]) -> int | None:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for item in payload:
            if isinstance(item, Mapping):
                value = _find_int(item, path)
                if value is not None:
                    return value
        return None

    current: object = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if isinstance(current, int) and not isinstance(current, bool):
        return current
    return None


def _safe_task_error_message(snapshot_type: str, required: bool) -> str:
    if required:
        return f"Required ESPN {snapshot_type} snapshot failed."
    return f"Optional ESPN {snapshot_type} snapshot was unavailable."
