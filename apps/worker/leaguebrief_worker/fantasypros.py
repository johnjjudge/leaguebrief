from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from leaguebrief_fantasypros_adapter import (
    FANTASYPROS_MIN_SEASON,
    FantasyProsCsvError,
    ParsedFantasyProsAdp,
    discover_adp_files,
    parse_adp_csv,
)

from leaguebrief_worker.jobs import ImportJobMessage, WorkerRunResult

FANTASYPROS_INGESTION_JOB_TYPES = {"ingest_fantasypros"}
FANTASYPROS_SOURCE_DIR_ENV = "FANTASYPROS_ADPREFERENCES_DIR"


class FantasyProsIngestionError(RuntimeError):
    """Raised when FantasyPros reference ingestion cannot complete."""


@dataclass(frozen=True)
class FantasyProsReferenceImportResult:
    reference_file_id: str
    ranking_id: str
    inserted: bool
    item_count: int


@dataclass(frozen=True)
class FantasyProsRankingSelection:
    ranking_id: str
    season: int
    scoring: str
    published_label: str


@dataclass(frozen=True)
class FantasyProsFileFailure:
    filename: str
    season: int | None
    scoring: str | None
    message: str


class FantasyProsReferenceRepository(Protocol):
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

    def import_adp_file(
        self,
        parsed: ParsedFantasyProsAdp,
        now: datetime,
    ) -> FantasyProsReferenceImportResult:
        ...


class FantasyProsIngestionService:
    def __init__(
        self,
        repository: FantasyProsReferenceRepository,
        source_dir: str | Path | None = None,
    ) -> None:
        self._repository = repository
        self._source_dir = Path(source_dir) if source_dir is not None else _default_source_dir()

    def run(
        self,
        message: ImportJobMessage,
        now: datetime | None = None,
    ) -> WorkerRunResult:
        if message.job_type not in FANTASYPROS_INGESTION_JOB_TYPES:
            return WorkerRunResult.succeeded()

        timestamp = now or datetime.now(UTC)
        references = discover_adp_files(self._source_dir)
        if not references:
            raise FantasyProsIngestionError("No FantasyPros ADP reference files were found.")

        self._repository.append_event(
            message.job_id,
            "fantasypros_ingestion_started",
            "FantasyPros reference ingestion started.",
            {
                "sourceDir": str(self._source_dir),
                "fileCount": len(references),
                "minimumSeason": FANTASYPROS_MIN_SEASON,
            },
            timestamp,
        )

        inserted_files = 0
        skipped_files = 0
        item_count = 0
        failures: list[FantasyProsFileFailure] = []

        for reference in references:
            task_id = self._repository.begin_task(
                message.job_id,
                "normalize_season",
                reference.season,
                datetime.now(UTC),
            )
            try:
                parsed = parse_adp_csv(reference.path)
                result = self._repository.import_adp_file(parsed, datetime.now(UTC))
                if result.inserted:
                    inserted_files += 1
                else:
                    skipped_files += 1
                item_count += result.item_count
                self._repository.complete_task(task_id, datetime.now(UTC))
                self._repository.append_event(
                    message.job_id,
                    "fantasypros_reference_file_ingested",
                    "FantasyPros reference file ingested.",
                    {
                        "filename": reference.path.name,
                        "season": reference.season,
                        "scoring": reference.scoring,
                        "inserted": result.inserted,
                        "itemCount": result.item_count,
                    },
                    datetime.now(UTC),
                )
            except FantasyProsCsvError:
                message_text = _safe_failure_message(reference.path.name)
                failures.append(
                    FantasyProsFileFailure(
                        filename=reference.path.name,
                        season=reference.season,
                        scoring=reference.scoring,
                        message=message_text,
                    )
                )
                self._repository.fail_task(task_id, message_text, datetime.now(UTC))
                self._repository.append_event(
                    message.job_id,
                    "fantasypros_reference_file_failed",
                    message_text,
                    {
                        "filename": reference.path.name,
                        "season": reference.season,
                        "scoring": reference.scoring,
                    },
                    datetime.now(UTC),
                )
                continue
            except Exception as exc:
                message_text = _safe_failure_message(reference.path.name)
                self._repository.fail_task(task_id, message_text, datetime.now(UTC))
                self._repository.append_event(
                    message.job_id,
                    "fantasypros_reference_file_failed",
                    message_text,
                    {
                        "filename": reference.path.name,
                        "season": reference.season,
                        "scoring": reference.scoring,
                    },
                    datetime.now(UTC),
                )
                raise FantasyProsIngestionError(
                    "FantasyPros reference ingestion failed."
                ) from exc

        self._repository.append_event(
            message.job_id,
            "fantasypros_ingestion_finished",
            "FantasyPros reference ingestion finished.",
            {
                "fileCount": len(references),
                "insertedFiles": inserted_files,
                "skippedFiles": skipped_files,
                "itemCount": item_count,
                "failureCount": len(failures),
            },
            datetime.now(UTC),
        )

        if failures and inserted_files == 0 and skipped_files == 0:
            raise FantasyProsIngestionError("FantasyPros reference ingestion failed for all files.")
        if failures:
            return WorkerRunResult.partial(
                "FantasyPros reference ingestion completed with partial success.",
                payload={
                    "insertedFiles": inserted_files,
                    "skippedFiles": skipped_files,
                    "itemCount": item_count,
                    "failures": [
                        {
                            "filename": failure.filename,
                            "season": failure.season,
                            "scoring": failure.scoring,
                            "message": failure.message,
                        }
                        for failure in failures
                    ],
                },
            )
        return WorkerRunResult.succeeded()


def _default_source_dir() -> Path:
    override = os.getenv(FANTASYPROS_SOURCE_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "adpreferences"


def _safe_failure_message(filename: str) -> str:
    return f"FantasyPros reference file could not be ingested: {filename}"
