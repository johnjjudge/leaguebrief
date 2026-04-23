from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from leaguebrief_espn_normalizer import normalize_espn_season

from leaguebrief_worker.fantasypros import FantasyProsRankingSelection
from leaguebrief_worker.jobs import ImportJobMessage, WorkerRunResult

NORMALIZE_RAW_SNAPSHOTS_JOB_TYPES = {"normalize_raw_snapshots"}
REQUIRED_SNAPSHOT_TYPES = {"league_meta", "matchups"}
OPTIONAL_SNAPSHOT_TYPES = {"draft", "rosters"}


class RawSnapshotNormalizationError(RuntimeError):
    """Raised when raw ESPN snapshots cannot be normalized."""


@dataclass(frozen=True)
class LeagueForNormalization:
    id: str
    scoring_type: str | None


@dataclass(frozen=True)
class RawSnapshotReference:
    season: int
    snapshot_type: str
    blob_path: str


@dataclass(frozen=True)
class NormalizedSeasonSaveResult:
    season_id: str
    import_status: str
    matchup_count: int
    draft_pick_count: int


class RawSnapshotNormalizationRepository(Protocol):
    def get_league_for_normalization(self, league_id: str) -> LeagueForNormalization | None:
        ...

    def list_current_raw_snapshots(
        self,
        league_id: str,
        seasons: Sequence[int] | None,
    ) -> Sequence[RawSnapshotReference]:
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

    def begin_task(self, job_id: str, task_type: str, season: int, now: datetime) -> str:
        ...

    def complete_task(self, task_id: str, now: datetime) -> None:
        ...

    def fail_task(self, task_id: str, error_message: str, now: datetime) -> None:
        ...

    def save_normalized_season(
        self,
        league_id: str,
        job_id: str,
        normalized_season: object,
        fantasypros_ranking_id: str | None,
        now: datetime,
    ) -> NormalizedSeasonSaveResult:
        ...


class RawPayloadReader(Protocol):
    def download_json_bytes(self, blob_path: str) -> bytes:
        ...


class FantasyProsRankingSelector(Protocol):
    def select_adp_ranking(
        self,
        season: int,
        scoring: str | None,
    ) -> FantasyProsRankingSelection | None:
        ...


class RawSnapshotNormalizationService:
    def __init__(
        self,
        repository: RawSnapshotNormalizationRepository,
        blob_store: RawPayloadReader,
        fantasypros_selector: FantasyProsRankingSelector,
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store
        self._fantasypros_selector = fantasypros_selector

    def run(
        self,
        message: ImportJobMessage,
        now: datetime | None = None,
    ) -> WorkerRunResult:
        if message.job_type not in NORMALIZE_RAW_SNAPSHOTS_JOB_TYPES:
            return WorkerRunResult.succeeded()

        timestamp = now or datetime.now(UTC)
        league = self._repository.get_league_for_normalization(message.league_id)
        if league is None:
            raise RawSnapshotNormalizationError("League not found for normalization.")

        snapshots = self._repository.list_current_raw_snapshots(
            message.league_id,
            message.requested_seasons,
        )
        snapshots_by_season = _group_snapshots_by_season(snapshots)
        seasons = _resolve_seasons(message.requested_seasons, snapshots_by_season)

        self._repository.append_event(
            message.job_id,
            "raw_snapshot_normalization_started",
            "Raw snapshot normalization started.",
            {"seasons": list(seasons)},
            timestamp,
        )

        results: list[NormalizedSeasonSaveResult] = []
        for season in seasons:
            task_id = self._repository.begin_task(
                message.job_id,
                "normalize_season",
                season,
                datetime.now(UTC),
            )
            try:
                season_snapshots = snapshots_by_season.get(season, {})
                _require_snapshots(season, season_snapshots)
                payloads = {
                    snapshot_type: _load_json_payload(self._blob_store, reference.blob_path)
                    for snapshot_type, reference in season_snapshots.items()
                }
                normalized = normalize_espn_season(
                    season=season,
                    league_meta=payloads["league_meta"],
                    matchups=payloads["matchups"],
                    draft=payloads.get("draft"),
                    rosters=payloads.get("rosters"),
                )
                ranking = self._fantasypros_selector.select_adp_ranking(
                    season,
                    league.scoring_type,
                )
                result = self._repository.save_normalized_season(
                    league_id=message.league_id,
                    job_id=message.job_id,
                    normalized_season=normalized,
                    fantasypros_ranking_id=ranking.ranking_id if ranking else None,
                    now=datetime.now(UTC),
                )
                results.append(result)
                self._repository.complete_task(task_id, datetime.now(UTC))
                self._repository.append_event(
                    message.job_id,
                    "raw_snapshot_season_normalized",
                    "Raw snapshot season normalized.",
                    {
                        "season": season,
                        "status": result.import_status,
                        "matchupCount": result.matchup_count,
                        "draftPickCount": result.draft_pick_count,
                        "hasFantasyProsRanking": ranking is not None,
                        "skippedMatchupCount": normalized.skipped_matchup_count,
                    },
                    datetime.now(UTC),
                )
            except Exception as exc:
                self._repository.fail_task(
                    task_id,
                    "Raw snapshot season normalization failed.",
                    datetime.now(UTC),
                )
                raise RawSnapshotNormalizationError(
                    "Raw snapshot normalization failed."
                ) from exc

        self._repository.append_event(
            message.job_id,
            "raw_snapshot_normalization_finished",
            "Raw snapshot normalization finished.",
            {
                "seasonCount": len(results),
                "seasons": [result.import_status for result in results],
            },
            datetime.now(UTC),
        )
        return WorkerRunResult.succeeded()


def _group_snapshots_by_season(
    snapshots: Sequence[RawSnapshotReference],
) -> dict[int, dict[str, RawSnapshotReference]]:
    grouped: dict[int, dict[str, RawSnapshotReference]] = {}
    for snapshot in snapshots:
        grouped.setdefault(snapshot.season, {}).setdefault(snapshot.snapshot_type, snapshot)
    return grouped


def _resolve_seasons(
    requested_seasons: Sequence[int] | None,
    snapshots_by_season: Mapping[int, Mapping[str, RawSnapshotReference]],
) -> tuple[int, ...]:
    if requested_seasons:
        return tuple(sorted(set(requested_seasons)))
    seasons = tuple(sorted(snapshots_by_season))
    if not seasons:
        raise RawSnapshotNormalizationError("No current raw snapshots were found.")
    return seasons


def _require_snapshots(
    season: int,
    snapshots: Mapping[str, RawSnapshotReference],
) -> None:
    missing = sorted(REQUIRED_SNAPSHOT_TYPES - set(snapshots))
    if missing:
        raise RawSnapshotNormalizationError(
            f"Season {season} is missing required raw snapshots: {', '.join(missing)}."
        )


def _load_json_payload(blob_store: RawPayloadReader, blob_path: str) -> object:
    try:
        payload = json.loads(blob_store.download_json_bytes(blob_path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RawSnapshotNormalizationError("Raw snapshot blob did not contain JSON.") from exc
    if not isinstance(payload, (dict, list)):
        raise RawSnapshotNormalizationError("Raw snapshot JSON must be an object or array.")
    return payload
