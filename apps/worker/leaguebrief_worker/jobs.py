from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}
DEFAULT_MAX_ATTEMPTS = 3


class WorkerMessageError(ValueError):
    """Raised when a worker queue message is invalid."""


class WorkerJobNotFoundError(RuntimeError):
    """Raised when a queue message references an unknown job."""


class WorkerJobFailed(RuntimeError):
    """Raised when a recoverable worker attempt fails and should be retried."""


@dataclass(frozen=True)
class ImportJobMessage:
    schema_version: int
    job_id: str
    league_id: str
    requested_by_user_id: str
    job_type: str
    requested_seasons: tuple[int, ...] | None
    enqueued_at: str


class WorkerJobRepository(Protocol):
    def get_job_status(self, job_id: str) -> str | None:
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

    def mark_validating(self, job_id: str, now: datetime) -> None:
        ...

    def mark_running(self, job_id: str, now: datetime) -> None:
        ...

    def mark_succeeded(self, job_id: str, now: datetime) -> None:
        ...

    def mark_failed(self, job_id: str, error_summary: str, now: datetime) -> None:
        ...


class WorkerService:
    def __init__(
        self,
        repository: WorkerJobRepository,
        run_job: Callable[[ImportJobMessage], None] | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._repository = repository
        self._run_job = run_job or _noop_run_job
        self._max_attempts = max_attempts

    def process_message(
        self,
        message_body: str | bytes,
        dequeue_count: int,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        job_message = parse_import_job_message(message_body)
        status = self._repository.get_job_status(job_message.job_id)
        if status is None:
            raise WorkerJobNotFoundError("Import job not found.")

        self._repository.append_event(
            job_message.job_id,
            "job_attempted",
            "Worker attempt started.",
            {"dequeueCount": dequeue_count},
            timestamp,
        )

        if status in TERMINAL_JOB_STATUSES:
            self._repository.append_event(
                job_message.job_id,
                "job_skipped",
                "Import job is already terminal.",
                {"status": status, "dequeueCount": dequeue_count},
                timestamp,
            )
            return

        try:
            self._repository.mark_validating(job_message.job_id, timestamp)
            self._repository.append_event(
                job_message.job_id,
                "job_validating",
                "Import job validation started.",
                None,
                timestamp,
            )
            self._repository.mark_running(job_message.job_id, timestamp)
            self._repository.append_event(
                job_message.job_id,
                "job_running",
                "Import job running.",
                None,
                timestamp,
            )
            self._run_job(job_message)
            self._repository.mark_succeeded(job_message.job_id, timestamp)
            self._repository.append_event(
                job_message.job_id,
                "job_succeeded",
                "Import job succeeded.",
                None,
                timestamp,
            )
        except Exception as exc:
            if dequeue_count >= self._max_attempts:
                self._repository.mark_failed(
                    job_message.job_id,
                    "Import job failed after retry limit.",
                    timestamp,
                )
                self._repository.append_event(
                    job_message.job_id,
                    "job_failed",
                    "Import job failed after retry limit.",
                    {"dequeueCount": dequeue_count},
                    timestamp,
                )
                return

            self._repository.append_event(
                job_message.job_id,
                "job_retry_scheduled",
                "Import job attempt failed and will be retried.",
                {"dequeueCount": dequeue_count},
                timestamp,
            )
            raise WorkerJobFailed("Import job attempt failed and should be retried.") from exc


def parse_import_job_message(message_body: str | bytes) -> ImportJobMessage:
    if isinstance(message_body, bytes):
        message_body = message_body.decode("utf-8")
    try:
        payload = json.loads(message_body)
    except json.JSONDecodeError as exc:
        raise WorkerMessageError("Import job message must be valid JSON.") from exc

    if not isinstance(payload, dict):
        raise WorkerMessageError("Import job message must be a JSON object.")

    schema_version = payload.get("schemaVersion")
    if schema_version != 1:
        raise WorkerMessageError("Import job message schemaVersion is unsupported.")

    return ImportJobMessage(
        schema_version=schema_version,
        job_id=_require_uuid(payload, "jobId"),
        league_id=_require_uuid(payload, "leagueId"),
        requested_by_user_id=_require_uuid(payload, "requestedByUserId"),
        job_type=_require_string(payload, "jobType"),
        requested_seasons=_parse_requested_seasons(payload.get("requestedSeasons")),
        enqueued_at=_require_string(payload, "enqueuedAt"),
    )


def _require_uuid(payload: Mapping[str, object], key: str) -> str:
    value = _require_string(payload, key)
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise WorkerMessageError(f"{key} must be a valid UUID.") from exc


def _require_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WorkerMessageError(f"{key} is required.")
    return value.strip()


def _parse_requested_seasons(value: object) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise WorkerMessageError("requestedSeasons must be a list or null.")
    seasons: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise WorkerMessageError("requestedSeasons must contain years.")
        seasons.append(item)
    return tuple(seasons)


def _noop_run_job(message: ImportJobMessage) -> None:
    return None
