import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from leaguebrief_worker.db.normalization import SqlRawSnapshotNormalizationRepository
from leaguebrief_worker.jobs import ImportJobMessage
from leaguebrief_worker.normalization import (
    LeagueForNormalization,
    NormalizedSeasonSaveResult,
    RawSnapshotNormalizationError,
    RawSnapshotNormalizationService,
    RawSnapshotReference,
)


class _FakeRepository:
    def __init__(self, snapshots):
        self.league = LeagueForNormalization(id=str(uuid4()), scoring_type="half_ppr")
        self.snapshots = list(snapshots)
        self.events = []
        self.tasks = {}
        self.saved = {}

    def get_league_for_normalization(self, league_id):
        return self.league

    def list_current_raw_snapshots(self, league_id, seasons):
        if seasons is None:
            return self.snapshots
        return [snapshot for snapshot in self.snapshots if snapshot.season in set(seasons)]

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

    def begin_task(self, job_id, task_type, season, now):
        task_id = str(uuid4())
        self.tasks[task_id] = {
            "job_id": job_id,
            "task_type": task_type,
            "season": season,
            "status": "running",
        }
        return task_id

    def complete_task(self, task_id, now):
        self.tasks[task_id]["status"] = "succeeded"

    def fail_task(self, task_id, error_message, now):
        self.tasks[task_id]["status"] = "failed"
        self.tasks[task_id]["error_message"] = error_message

    def save_normalized_season(
        self,
        league_id,
        job_id,
        normalized_season,
        fantasypros_ranking_id,
        now,
    ):
        self.saved[normalized_season.season_year] = {
            "season": normalized_season,
            "fantasypros_ranking_id": fantasypros_ranking_id,
        }
        return NormalizedSeasonSaveResult(
            season_id=f"season-{normalized_season.season_year}",
            import_status=normalized_season.import_status,
            matchup_count=len(normalized_season.matchups),
            draft_pick_count=len(normalized_season.draft.picks)
            if normalized_season.draft is not None
            else 0,
        )


class _FakeBlobStore:
    def __init__(self, payloads):
        self.payloads = dict(payloads)

    def download_json_bytes(self, blob_path):
        return json.dumps(self.payloads[blob_path]).encode("utf-8")


class _FakeFantasyProsSelector:
    def __init__(self):
        self.calls = []

    def select_adp_ranking(self, season, scoring):
        from leaguebrief_worker.fantasypros import FantasyProsRankingSelection

        self.calls.append((season, scoring))
        return FantasyProsRankingSelection(
            ranking_id=f"ranking-{season}",
            season=season,
            scoring="ppr",
            published_label="fixture",
        )


class _FakeSqlConnection:
    def __init__(self):
        self.executed = []
        self.cursor_instance = _FakeSqlCursor(self)

    def cursor(self):
        return self.cursor_instance

    def close(self):
        pass


class _FakeSqlCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def execute(self, sql, *params):
        normalized_sql = " ".join(sql.split())
        self.connection.executed.append((normalized_sql, params))
        if normalized_sql.startswith("SELECT id, scoring_type FROM dbo.leagues"):
            self.rows = [("league-1", "ppr")]
        elif normalized_sql.startswith("SELECT season, snapshot_type, blob_path"):
            self.rows = [
                (2024, "league_meta", "meta-path"),
                (2024, "matchups", "matchups-path"),
            ]
        else:
            self.rows = []
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def test_normalization_service_resolves_requested_seasons_and_saves():
    snapshots, payloads = _snapshots_and_payloads((2024, 2025))
    repository = _FakeRepository(snapshots)
    selector = _FakeFantasyProsSelector()
    service = RawSnapshotNormalizationService(
        repository=repository,
        blob_store=_FakeBlobStore(payloads),
        fantasypros_selector=selector,
    )

    result = service.run(_message(requested_seasons=(2025,)), now=_now())

    assert not result.partial_success
    assert set(repository.saved) == {2025}
    assert repository.saved[2025]["fantasypros_ranking_id"] == "ranking-2025"
    assert selector.calls == [(2025, "half_ppr")]
    assert {task["status"] for task in repository.tasks.values()} == {"succeeded"}
    assert repository.events[-1]["event_type"] == "raw_snapshot_normalization_finished"


def test_normalization_service_uses_all_snapshot_seasons_when_none_requested():
    snapshots, payloads = _snapshots_and_payloads((2024, 2025))
    repository = _FakeRepository(snapshots)
    service = RawSnapshotNormalizationService(
        repository=repository,
        blob_store=_FakeBlobStore(payloads),
        fantasypros_selector=_FakeFantasyProsSelector(),
    )

    service.run(_message(requested_seasons=None), now=_now())

    assert set(repository.saved) == {2024, 2025}


def test_normalization_service_fails_when_required_snapshot_is_missing():
    snapshots, payloads = _snapshots_and_payloads((2024,))
    snapshots = [
        snapshot for snapshot in snapshots if snapshot.snapshot_type != "matchups"
    ]
    repository = _FakeRepository(snapshots)
    service = RawSnapshotNormalizationService(
        repository=repository,
        blob_store=_FakeBlobStore(payloads),
        fantasypros_selector=_FakeFantasyProsSelector(),
    )

    with pytest.raises(RawSnapshotNormalizationError):
        service.run(_message(requested_seasons=(2024,)), now=_now())

    assert {task["status"] for task in repository.tasks.values()} == {"failed"}


def test_normalization_service_rerun_updates_same_saved_season():
    snapshots, payloads = _snapshots_and_payloads((2024,))
    repository = _FakeRepository(snapshots)
    service = RawSnapshotNormalizationService(
        repository=repository,
        blob_store=_FakeBlobStore(payloads),
        fantasypros_selector=_FakeFantasyProsSelector(),
    )

    service.run(_message(requested_seasons=(2024,)), now=_now())
    service.run(_message(requested_seasons=(2024,)), now=_now())

    assert set(repository.saved) == {2024}
    assert len([task for task in repository.tasks.values() if task["season"] == 2024]) == 2


def test_sql_normalization_repository_reads_league_and_current_snapshots():
    connection = _FakeSqlConnection()
    repository = SqlRawSnapshotNormalizationRepository(connection_factory=lambda: connection)

    league = repository.get_league_for_normalization("league-1")
    snapshots = repository.list_current_raw_snapshots("league-1", (2024,))

    assert league == LeagueForNormalization(id="league-1", scoring_type="ppr")
    assert snapshots == [
        RawSnapshotReference(2024, "league_meta", "meta-path"),
        RawSnapshotReference(2024, "matchups", "matchups-path"),
    ]
    snapshot_sql, snapshot_params = connection.executed[-1]
    assert "season IN (?)" in snapshot_sql
    assert snapshot_params == ("league-1", 2024)


def _snapshots_and_payloads(seasons):
    snapshots = []
    payloads = {}
    for season in seasons:
        for snapshot_type, payload in {
            "league_meta": _league_meta(season),
            "matchups": _matchups(),
            "draft": _draft(),
            "rosters": _rosters(season),
        }.items():
            blob_path = f"espn/league/{season}/{snapshot_type}/hash.json"
            snapshots.append(
                RawSnapshotReference(
                    season=season,
                    snapshot_type=snapshot_type,
                    blob_path=blob_path,
                )
            )
            payloads[blob_path] = payload
    return snapshots, payloads


def _league_meta(season):
    return {
        "seasonId": season,
        "settings": {"size": 2, "scheduleSettings": {"matchupPeriodCount": 14}},
        "status": {"finalScoringPeriod": 17},
        "members": [{"id": "owner-1", "displayName": "Alice"}],
        "teams": [
            {
                "id": 1,
                "owners": ["owner-1"],
                "location": "Alpha",
                "nickname": "Dogs",
                "record": {"overall": {"wins": 1, "losses": 0, "ties": 0}},
                "rankCalculatedFinal": 1,
            },
            {
                "id": 2,
                "owners": ["owner-2"],
                "location": "Beta",
                "nickname": "Cats",
                "record": {"overall": {"wins": 0, "losses": 1, "ties": 0}},
                "rankCalculatedFinal": 2,
            },
        ],
    }


def _matchups():
    return {
        "schedule": [
            {
                "id": "matchup-1",
                "matchupPeriodId": 1,
                "home": {"teamId": 1, "totalPoints": 100},
                "away": {"teamId": 2, "totalPoints": 90},
                "winner": "HOME",
            }
        ]
    }


def _draft():
    return {
        "draftDetail": {
            "picks": [
                {
                    "overallPickNumber": 1,
                    "teamId": 1,
                    "playerPoolEntry": {
                        "player": {"fullName": "Christian McCaffrey", "defaultPositionId": 2}
                    },
                }
            ]
        }
    }


def _rosters(season):
    return {
        "leagueId": "123",
        "season": season,
        "snapshotType": "rosters",
        "scoringPeriods": [{"scoringPeriodId": 1, "payload": {"teams": []}}],
    }


def _message(requested_seasons):
    return ImportJobMessage(
        schema_version=1,
        job_id=str(uuid4()),
        league_id=str(uuid4()),
        requested_by_user_id=str(uuid4()),
        job_type="normalize_raw_snapshots",
        requested_seasons=requested_seasons,
        enqueued_at="2026-04-22T12:00:00Z",
    )


def _now():
    return datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
