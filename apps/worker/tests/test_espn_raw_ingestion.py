from datetime import UTC, datetime
from uuid import uuid4

from leaguebrief_espn_adapter import EspnNotFoundError, EspnSnapshotRequest, EspnSnapshotResponse
from leaguebrief_worker.ingestion import (
    CredentialSecretReference,
    EspnRawIngestionService,
    LeagueForIngestion,
)
from leaguebrief_worker.jobs import ImportJobMessage


class _FakeRepository:
    def __init__(self, league=None, credential_refs=None, current_hashes=None):
        self.league = league or _league()
        self.credential_refs = list(credential_refs or [])
        self.events = []
        self.tasks = {}
        self.snapshots = []
        self.current_hashes = dict(current_hashes or {})

    def get_league_for_ingestion(self, league_id):
        return self.league if league_id == self.league.id else None

    def list_credential_secret_references(self, league_id, requested_by_user_id):
        return self.credential_refs

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

    def save_raw_snapshot(self, league_id, season, snapshot_type, blob_path, source_hash, now):
        key = (league_id, season, snapshot_type)
        if self.current_hashes.get(key) == source_hash:
            return False
        self.current_hashes[key] = source_hash
        self.snapshots.append(
            {
                "league_id": league_id,
                "season": season,
                "snapshot_type": snapshot_type,
                "blob_path": blob_path,
                "source_hash": source_hash,
            }
        )
        return True


class _FakeBlobStore:
    def __init__(self):
        self.uploads = {}

    def upload_json_bytes(self, blob_path, payload):
        self.uploads[blob_path] = payload


class _FakeSecretReader:
    def __init__(self, secrets):
        self.secrets = dict(secrets)
        self.read_names = []

    def get_secret(self, name):
        self.read_names.append(name)
        return self.secrets[name]


class _FakeEspnClient:
    def __init__(self, unavailable=None, discovered_seasons=(2021, 2022)):
        self.unavailable = set(unavailable or [])
        self.discovered_seasons = discovered_seasons
        self.calls = []

    def discover_seasons(self, league_id, credentials):
        self.calls.append(("discover", league_id, credentials.espn_s2 if credentials else None))
        return tuple(self.discovered_seasons)

    def fetch_league_meta(self, league_id, season, credentials):
        self.calls.append(("league_meta", league_id, season, credentials.espn_s2 if credentials else None))
        return _response(league_id, season, "league_meta", {"status": {"finalScoringPeriod": 2}})

    def fetch_matchups(self, league_id, season, credentials):
        self.calls.append(("matchups", league_id, season, credentials.espn_s2 if credentials else None))
        return _response(league_id, season, "matchups", {"schedule": []})

    def fetch_draft(self, league_id, season, credentials):
        self.calls.append(("draft", league_id, season, credentials.espn_s2 if credentials else None))
        if "draft" in self.unavailable:
            raise EspnNotFoundError("not found")
        return _response(league_id, season, "draft", {"draftDetail": {}})

    def fetch_transactions(self, league_id, season, credentials):
        self.calls.append(("transactions", league_id, season, credentials.espn_s2 if credentials else None))
        if "transactions" in self.unavailable:
            raise EspnNotFoundError("not found")
        return _response(league_id, season, "transactions", {"transactions": []})

    def fetch_rosters(self, league_id, season, scoring_period_ids, credentials):
        self.calls.append(
            (
                "rosters",
                league_id,
                season,
                tuple(scoring_period_ids),
                credentials.espn_s2 if credentials else None,
            )
        )
        if "rosters" in self.unavailable:
            raise EspnNotFoundError("not found")
        return _response(
            league_id,
            season,
            "rosters",
            {"scoringPeriods": list(scoring_period_ids)},
        )


def test_ingestion_uses_requested_seasons_credentials_and_persists_raw_snapshots():
    league = _league(first_season=2020, last_season=2024)
    repository = _FakeRepository(
        league=league,
        credential_refs=[
            CredentialSecretReference(
                user_id="user-1",
                key_vault_secret_name_s2="s2-name",
                key_vault_secret_name_swid="swid-name",
                is_preferred_for_refresh=False,
            )
        ],
    )
    blob_store = _FakeBlobStore()
    client = _FakeEspnClient()
    service = EspnRawIngestionService(
        repository=repository,
        blob_store=blob_store,
        secret_reader=_FakeSecretReader({"s2-name": "secret-s2", "swid-name": "{swid}"}),
        client_factory=lambda: client,
    )

    result = service.run(_message(league.id, requested_seasons=(2022,)), now=_now())

    assert not result.partial_success
    assert sorted(snapshot["snapshot_type"] for snapshot in repository.snapshots) == [
        "draft",
        "league_meta",
        "matchups",
        "rosters",
        "transactions",
    ]
    assert set(blob_store.uploads) == {snapshot["blob_path"] for snapshot in repository.snapshots}
    assert all(path.startswith(f"espn/{league.id}/2022/") for path in blob_store.uploads)
    assert ("rosters", "external-123", 2022, (1, 2), "secret-s2") in client.calls
    assert {task["status"] for task in repository.tasks.values()} == {"succeeded"}


def test_ingestion_discovers_seasons_when_league_range_is_missing():
    league = _league(first_season=None, last_season=None)
    repository = _FakeRepository(league=league)
    blob_store = _FakeBlobStore()
    client = _FakeEspnClient(discovered_seasons=(2020,))
    service = EspnRawIngestionService(
        repository=repository,
        blob_store=blob_store,
        secret_reader=_FakeSecretReader({}),
        client_factory=lambda: client,
    )

    service.run(_message(league.id, requested_seasons=None), now=_now())

    assert client.calls[0] == ("discover", "external-123", None)
    assert {snapshot["season"] for snapshot in repository.snapshots} == {2020}


def test_optional_snapshot_failures_return_partial_success():
    league = _league()
    repository = _FakeRepository(league=league)
    blob_store = _FakeBlobStore()
    service = EspnRawIngestionService(
        repository=repository,
        blob_store=blob_store,
        secret_reader=_FakeSecretReader({}),
        client_factory=lambda: _FakeEspnClient(unavailable={"draft", "rosters", "transactions"}),
    )

    result = service.run(_message(league.id, requested_seasons=(2022,)), now=_now())

    assert result.partial_success
    assert result.payload is not None
    assert len(result.payload["optionalFailures"]) == 3
    failed_tasks = [task for task in repository.tasks.values() if task["status"] == "failed"]
    assert len(failed_tasks) == 3
    assert sorted(snapshot["snapshot_type"] for snapshot in repository.snapshots) == [
        "league_meta",
        "matchups",
    ]


def _response(league_id, season, snapshot_type, payload):
    return EspnSnapshotResponse(
        request=EspnSnapshotRequest(
            league_id=league_id,
            season=season,
            snapshot_type=snapshot_type,
        ),
        payload=payload,
        url="https://example.test",
    )


def _league(first_season=2022, last_season=2022):
    return LeagueForIngestion(
        id=str(uuid4()),
        external_league_id="external-123",
        first_season=first_season,
        last_season=last_season,
        is_private=True,
    )


def _message(league_id, requested_seasons):
    return ImportJobMessage(
        schema_version=1,
        job_id=str(uuid4()),
        league_id=league_id,
        requested_by_user_id="user-1",
        job_type="initial_import",
        requested_seasons=requested_seasons,
        enqueued_at="2026-04-22T12:00:00Z",
    )


def _now():
    return datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
