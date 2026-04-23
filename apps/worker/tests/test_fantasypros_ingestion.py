import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from leaguebrief_fantasypros_adapter import discover_adp_files, parse_adp_csv
from leaguebrief_worker.db.references import SqlFantasyProsReferenceRepository
from leaguebrief_worker.fantasypros import FantasyProsIngestionService
from leaguebrief_worker.jobs import ImportJobMessage


class _FakeFantasyProsRepository:
    def __init__(self):
        self.events = []
        self.tasks = {}
        self.imports = {}
        self.results = []

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

    def import_adp_file(self, parsed, now):
        from leaguebrief_worker.fantasypros import FantasyProsReferenceImportResult

        key = (parsed.reference.season, parsed.reference.scoring, parsed.source_hash)
        inserted = key not in self.imports
        if inserted:
            self.imports[key] = {
                "reference_file_id": str(uuid4()),
                "ranking_id": str(uuid4()),
                "item_count": len(parsed.items),
            }
        stored = self.imports[key]
        result = FantasyProsReferenceImportResult(
            reference_file_id=stored["reference_file_id"],
            ranking_id=stored["ranking_id"],
            inserted=inserted,
            item_count=stored["item_count"],
        )
        self.results.append(result)
        return result


class _FakeConnection:
    def __init__(self):
        self.reference_files = []
        self.reference_rankings = []
        self.reference_ranking_items = []
        self.player_reference = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class _FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.row = None

    def execute(self, sql, *params):
        compact_sql = " ".join(sql.split())
        self.row = None
        if compact_sql.startswith("SET TRANSACTION ISOLATION LEVEL"):
            return self
        if compact_sql.startswith("SELECT id FROM dbo.reference_files"):
            self.row = _find_reference_file(self.connection.reference_files, params)
            return self
        if compact_sql.startswith("INSERT INTO dbo.reference_files"):
            self.connection.reference_files.append(
                {
                    "id": params[0],
                    "source": params[1],
                    "season": params[2],
                    "file_type": params[3],
                    "blob_path": params[4],
                    "version_label": params[5],
                }
            )
            return self
        if compact_sql.startswith("SELECT id FROM dbo.reference_rankings"):
            self.row = _find_reference_ranking(self.connection.reference_rankings, params)
            return self
        if compact_sql.startswith("INSERT INTO dbo.reference_rankings"):
            self.connection.reference_rankings.append(
                {
                    "id": params[0],
                    "season": params[1],
                    "source": params[2],
                    "ranking_type": params[3],
                    "format": params[4],
                    "scoring": params[5],
                    "published_label": params[6],
                }
            )
            return self
        if compact_sql.startswith("SELECT COUNT_BIG(*) FROM dbo.reference_ranking_items"):
            ranking_id = params[0]
            count = sum(
                1
                for item in self.connection.reference_ranking_items
                if item["reference_ranking_id"] == ranking_id
            )
            self.row = (count,)
            return self
        if compact_sql.startswith("SELECT TOP (1) id, nfl_team, external_keys_json"):
            self.row = _find_player(self.connection.player_reference, params[0], params[2])
            return self
        if compact_sql.startswith("INSERT INTO dbo.player_reference"):
            self.connection.player_reference.append(
                {
                    "id": params[0],
                    "canonical_player_name": params[1],
                    "position": params[2],
                    "nfl_team": params[3],
                    "external_keys_json": params[4],
                }
            )
            return self
        if compact_sql.startswith("UPDATE dbo.player_reference"):
            for player in self.connection.player_reference:
                if player["id"] == params[2]:
                    player["nfl_team"] = player["nfl_team"] or params[0]
                    player["external_keys_json"] = params[1]
            return self
        if compact_sql.startswith("INSERT INTO dbo.reference_ranking_items"):
            self.connection.reference_ranking_items.append(
                {
                    "id": params[0],
                    "reference_ranking_id": params[1],
                    "player_reference_id": params[2],
                    "rank_value": params[3],
                    "adp_value": params[4],
                    "position_rank": params[5],
                    "raw_player_name": params[6],
                    "raw_team": params[7],
                    "raw_position": params[8],
                }
            )
            return self
        if compact_sql.startswith("SELECT TOP (1) id, season, scoring, published_label"):
            self.row = _select_ranking(self.connection.reference_rankings, params[0], params[1])
            return self
        raise AssertionError(f"Unexpected SQL: {compact_sql}")

    def fetchone(self):
        return self.row


def test_packaged_fantasypros_csvs_parse_successfully():
    source_dir = Path(__file__).resolve().parents[1] / "adpreferences"
    references = discover_adp_files(source_dir)

    parsed = [parse_adp_csv(reference.path) for reference in references]

    assert len(parsed) == 30
    assert all(file.items for file in parsed)
    assert {file.reference.season for file in parsed} == set(range(2015, 2026))


def test_fantasypros_ingestion_service_imports_and_skips_same_hash(tmp_path):
    _write_csv(
        tmp_path / "FantasyPros_2024_Overall_ADP_Rankings-PPR.csv",
        [
            '"Rank","Player","Team","Bye","POS","ESPN","AVG"',
            '"1","Christian McCaffrey","SF","9","RB1","2.0","1.3"',
        ],
    )
    repository = _FakeFantasyProsRepository()
    service = FantasyProsIngestionService(repository=repository, source_dir=tmp_path)

    first_result = service.run(_message(job_type="ingest_fantasypros"), now=_now())
    second_result = service.run(_message(job_type="ingest_fantasypros"), now=_now())

    assert not first_result.partial_success
    assert not second_result.partial_success
    assert [result.inserted for result in repository.results] == [True, False]
    assert {task["status"] for task in repository.tasks.values()} == {"succeeded"}
    assert repository.events[-1]["payload"]["skippedFiles"] == 1


def test_sql_reference_repository_import_is_idempotent_and_reuses_player(tmp_path):
    ppr_path = tmp_path / "FantasyPros_2024_Overall_ADP_Rankings-PPR.csv"
    standard_path = tmp_path / "FantasyPros_2024_Overall_ADP_Rankings-STD.csv"
    _write_csv(
        ppr_path,
        [
            '"Rank","Player","Team","Bye","POS","ESPN","AVG"',
            '"20","Michael Pittman Jr.","IND","14","WR11","22.0","24.2"',
        ],
    )
    _write_csv(
        standard_path,
        [
            '"Rank","Player","Team","Bye","POS","AVG"',
            '"30","Michael Pittman","IND","14","WR14","31.5"',
        ],
    )
    connection = _FakeConnection()
    repository = SqlFantasyProsReferenceRepository(connection_factory=lambda: connection)

    first = repository.import_adp_file(parse_adp_csv(ppr_path), _now())
    second = repository.import_adp_file(parse_adp_csv(ppr_path), _now())
    third = repository.import_adp_file(parse_adp_csv(standard_path), _now())

    assert first.inserted
    assert not second.inserted
    assert third.inserted
    assert len(connection.reference_files) == 2
    assert len(connection.reference_rankings) == 2
    assert len(connection.reference_ranking_items) == 2
    assert len(connection.player_reference) == 1
    assert connection.reference_files[0]["blob_path"].startswith("adpreferences/")
    external_keys = json.loads(connection.player_reference[0]["external_keys_json"])
    assert external_keys["fantasypros"]["normalizedName"] == "michael pittman"
    assert external_keys["fantasypros"]["aliases"] == [
        "Michael Pittman",
        "Michael Pittman Jr.",
    ]


def test_sql_reference_selector_falls_back_from_half_ppr_to_ppr():
    connection = _FakeConnection()
    connection.reference_rankings.append(
        {
            "id": "ranking-1",
            "season": 2017,
            "source": "fantasypros",
            "ranking_type": "adp",
            "format": "overall",
            "scoring": "ppr",
            "published_label": "ppr",
        }
    )
    repository = SqlFantasyProsReferenceRepository(connection_factory=lambda: connection)

    selected = repository.select_adp_ranking(2017, "half_ppr")

    assert selected is not None
    assert selected.ranking_id == "ranking-1"
    assert selected.scoring == "ppr"


def _find_reference_file(rows, params):
    source, season, file_type, version_label = params
    for row in rows:
        if (
            row["source"] == source
            and row["season"] == season
            and row["file_type"] == file_type
            and row["version_label"] == version_label
        ):
            return (row["id"],)
    return None


def _find_reference_ranking(rows, params):
    season, source, ranking_type, ranking_format, scoring, published_label = params
    for row in rows:
        if (
            row["season"] == season
            and row["source"] == source
            and row["ranking_type"] == ranking_type
            and row["format"] == ranking_format
            and row["scoring"] == scoring
            and row["published_label"] == published_label
        ):
            return (row["id"],)
    return None


def _find_player(rows, position, normalized_name):
    for row in rows:
        external_keys = json.loads(row["external_keys_json"])
        if (
            row["position"] == position
            and external_keys["fantasypros"]["normalizedName"] == normalized_name
        ):
            return (row["id"], row["nfl_team"], row["external_keys_json"])
    return None


def _select_ranking(rows, season, scoring):
    for row in rows:
        if (
            row["season"] == season
            and row["source"] == "fantasypros"
            and row["ranking_type"] == "adp"
            and row["format"] == "overall"
            and row["scoring"] == scoring
        ):
            return (row["id"], row["season"], row["scoring"], row["published_label"])
    return None


def _write_csv(path, lines):
    path.write_text("\n".join(lines), encoding="utf-8")


def _message(job_type):
    return ImportJobMessage(
        schema_version=1,
        job_id=str(uuid4()),
        league_id=str(uuid4()),
        requested_by_user_id=str(uuid4()),
        job_type=job_type,
        requested_seasons=None,
        enqueued_at="2026-04-22T12:00:00Z",
    )


def _now():
    return datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
