from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

SUPPORTED_IMPORT_JOB_TYPES = {
    "initial_import",
    "attach_existing_league",
    "refresh_current_data",
    "recompute_metrics",
    "ingest_fantasypros",
}
MAX_REASONABLE_PRIORITY = 100
MIN_REASONABLE_PRIORITY = -100
MIN_SUPPORTED_IMPORT_SEASON = 2015


class ImportJobValidationError(ValueError):
    """Raised when an import job request payload is invalid."""


class ImportJobQueueError(RuntimeError):
    """Raised when a queued import job cannot be enqueued."""


@dataclass(frozen=True)
class ImportJobInput:
    job_type: str
    requested_seasons: tuple[int, ...] | None
    priority: int


@dataclass(frozen=True)
class ImportJobRecord:
    id: str
    league_id: str
    requested_by_user_id: str
    job_type: str
    status: str
    current_phase: str | None
    priority: int
    requested_seasons: tuple[int, ...] | None
    started_at: datetime | None
    completed_at: datetime | None
    last_heartbeat_at: datetime | None
    error_summary: str | None
    created_at: datetime


class ImportJobRepository(Protocol):
    def create_import_job_for_authorized_user(
        self,
        user_id: str,
        league_id: str,
        job_input: ImportJobInput,
        now: datetime,
    ) -> ImportJobRecord:
        ...

    def mark_job_enqueue_failed(self, job_id: str, error_summary: str, now: datetime) -> None:
        ...


class ImportJobQueue(Protocol):
    def enqueue(self, message: str) -> None:
        ...


class ImportJobService:
    def __init__(
        self,
        repository: ImportJobRepository,
        queue: ImportJobQueue,
    ) -> None:
        self._repository = repository
        self._queue = queue

    def create_import(
        self,
        user_id: str,
        league_id: str,
        payload: Mapping[str, object],
        now: datetime | None = None,
    ) -> dict[str, object]:
        league_id = _validate_uuid(league_id, "leagueId")
        user_id = _validate_uuid(user_id, "userId")
        timestamp = now or datetime.now(UTC)
        job_input = parse_import_job_input(payload)
        job = self._repository.create_import_job_for_authorized_user(
            user_id=user_id,
            league_id=league_id,
            job_input=job_input,
            now=timestamp,
        )

        message = serialize_import_job_queue_message(
            job=job,
            requested_seasons=job_input.requested_seasons,
            enqueued_at=timestamp,
        )
        try:
            self._queue.enqueue(message)
        except Exception as exc:
            self._repository.mark_job_enqueue_failed(
                job.id,
                "Failed to enqueue import job.",
                datetime.now(UTC),
            )
            raise ImportJobQueueError("Failed to enqueue import job.") from exc

        return {"job": serialize_import_job(job)}


def parse_import_job_input(payload: Mapping[str, object]) -> ImportJobInput:
    job_type = _optional_string(payload.get("jobType")) or "initial_import"
    if job_type not in SUPPORTED_IMPORT_JOB_TYPES:
        raise ImportJobValidationError("jobType is not supported.")

    return ImportJobInput(
        job_type=job_type,
        requested_seasons=_parse_requested_seasons(payload.get("requestedSeasons")),
        priority=_parse_priority(payload.get("priority")),
    )


def serialize_import_job_queue_message(
    job: ImportJobRecord,
    requested_seasons: tuple[int, ...] | None,
    enqueued_at: datetime,
) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "jobId": job.id,
            "leagueId": job.league_id,
            "requestedByUserId": job.requested_by_user_id,
            "jobType": job.job_type,
            "requestedSeasons": list(requested_seasons) if requested_seasons is not None else None,
            "enqueuedAt": _isoformat(enqueued_at),
        },
        separators=(",", ":"),
    )


def serialize_import_job(job: ImportJobRecord) -> dict[str, object]:
    return {
        "id": job.id,
        "leagueId": job.league_id,
        "requestedByUserId": job.requested_by_user_id,
        "jobType": job.job_type,
        "status": job.status,
        "currentPhase": job.current_phase,
        "priority": job.priority,
        "requestedSeasons": list(job.requested_seasons) if job.requested_seasons is not None else None,
        "startedAt": _isoformat(job.started_at),
        "completedAt": _isoformat(job.completed_at),
        "lastHeartbeatAt": _isoformat(job.last_heartbeat_at),
        "errorSummary": job.error_summary,
        "createdAt": _isoformat(job.created_at),
    }


def _parse_requested_seasons(value: object) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ImportJobValidationError("requestedSeasons must be a list of years.")

    seasons: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ImportJobValidationError("requestedSeasons must contain only years.")
        if item < MIN_SUPPORTED_IMPORT_SEASON:
            raise ImportJobValidationError("requestedSeasons must be 2015 or later.")
        seasons.append(item)
    return tuple(seasons)


def _parse_priority(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImportJobValidationError("priority must be an integer.")
    if value < MIN_REASONABLE_PRIORITY or value > MAX_REASONABLE_PRIORITY:
        raise ImportJobValidationError("priority is outside the supported range.")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ImportJobValidationError("jobType must be a non-empty string.")
    return value.strip()


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ImportJobValidationError(f"{field_name} must be a valid UUID.") from exc


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
