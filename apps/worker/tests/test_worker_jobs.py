import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from leaguebrief_worker.jobs import WorkerJobFailed, WorkerRunResult, WorkerService


class _InMemoryWorkerJobRepository:
    def __init__(self, status="queued"):
        self.status = status
        self.current_phase = None
        self.completed_at = None
        self.error_summary = None
        self.events = []

    def get_job_status(self, job_id: str):
        return self.status

    def append_event(self, job_id, event_type, message, payload, now):
        self.events.append(
            {
                "job_id": job_id,
                "event_type": event_type,
                "message": message,
                "payload": payload,
                "created_at": now,
            }
        )

    def mark_validating(self, job_id: str, now: datetime) -> None:
        self.status = "validating"
        self.current_phase = "validate"

    def mark_running(self, job_id: str, now: datetime) -> None:
        self.status = "running"
        self.current_phase = "fetch"

    def mark_succeeded(self, job_id: str, now: datetime) -> None:
        self.status = "succeeded"
        self.current_phase = "finalize"
        self.completed_at = now
        self.error_summary = None

    def mark_partial_success(self, job_id: str, error_summary: str, now: datetime) -> None:
        self.status = "partial_success"
        self.current_phase = "finalize"
        self.completed_at = now
        self.error_summary = error_summary

    def mark_failed(self, job_id: str, error_summary: str, now: datetime) -> None:
        self.status = "failed"
        self.current_phase = "finalize"
        self.completed_at = now
        self.error_summary = error_summary


def test_worker_transitions_job_through_validating_running_succeeded():
    repository = _InMemoryWorkerJobRepository()
    service = WorkerService(repository)
    message = _message()

    service.process_message(json.dumps(message), dequeue_count=1, now=_now())

    assert repository.status == "succeeded"
    assert repository.current_phase == "finalize"
    assert _event_types(repository) == [
        "job_attempted",
        "job_validating",
        "job_running",
        "job_succeeded",
    ]


def test_partial_run_result_marks_job_partial_success():
    repository = _InMemoryWorkerJobRepository()
    service = WorkerService(repository, run_job=_partial_job)

    service.process_message(json.dumps(_message()), dequeue_count=1, now=_now())

    assert repository.status == "partial_success"
    assert repository.error_summary == "Import job completed with partial success."
    assert _event_types(repository) == [
        "job_attempted",
        "job_validating",
        "job_running",
        "job_partial_success",
    ]


def test_failed_attempt_below_retry_limit_raises_for_queue_retry():
    repository = _InMemoryWorkerJobRepository()
    service = WorkerService(repository, run_job=_failing_job)

    with pytest.raises(WorkerJobFailed):
        service.process_message(json.dumps(_message()), dequeue_count=2, now=_now())

    assert repository.status == "running"
    assert repository.error_summary is None
    assert _event_types(repository) == [
        "job_attempted",
        "job_validating",
        "job_running",
        "job_retry_scheduled",
    ]


def test_third_failed_attempt_marks_job_failed_and_swallows_exception():
    repository = _InMemoryWorkerJobRepository()
    service = WorkerService(repository, run_job=_failing_job)

    service.process_message(json.dumps(_message()), dequeue_count=3, now=_now())

    assert repository.status == "failed"
    assert repository.error_summary == "Import job failed after retry limit."
    assert _event_types(repository) == [
        "job_attempted",
        "job_validating",
        "job_running",
        "job_failed",
    ]


def test_terminal_duplicate_message_is_noop():
    repository = _InMemoryWorkerJobRepository(status="succeeded")
    service = WorkerService(repository)

    service.process_message(json.dumps(_message()), dequeue_count=1, now=_now())

    assert repository.status == "succeeded"
    assert _event_types(repository) == ["job_attempted", "job_skipped"]


def _message():
    return {
        "schemaVersion": 1,
        "jobId": str(uuid4()),
        "leagueId": str(uuid4()),
        "requestedByUserId": str(uuid4()),
        "jobType": "initial_import",
        "requestedSeasons": [2022, 2023],
        "enqueuedAt": "2026-04-22T12:00:00Z",
    }


def _failing_job(message):
    raise RuntimeError("synthetic failure")


def _partial_job(message):
    return WorkerRunResult.partial(payload={"optionalFailureCount": 1})


def _now() -> datetime:
    return datetime(2026, 4, 22, 12, 0, tzinfo=UTC)


def _event_types(repository):
    return [event["event_type"] for event in repository.events]
