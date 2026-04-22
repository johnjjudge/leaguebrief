import logging
import os

import azure.functions as func
from leaguebrief_espn_adapter import EspnFantasyClient
from leaguebrief_worker.blobs import AzureBlobRawPayloadStore
from leaguebrief_worker.db.jobs import SqlWorkerJobRepository
from leaguebrief_worker.db.raw_snapshots import SqlRawSnapshotRepository
from leaguebrief_worker.ingestion import (
    ESPN_RAW_INGESTION_JOB_TYPES,
    EspnRawIngestionService,
)
from leaguebrief_worker.jobs import ImportJobMessage, WorkerRunResult, WorkerService
from leaguebrief_worker.secrets import AzureKeyVaultSecretReader

app = func.FunctionApp()


def get_worker_job_repository() -> SqlWorkerJobRepository:
    return SqlWorkerJobRepository()


def get_espn_raw_ingestion_service() -> EspnRawIngestionService:
    return EspnRawIngestionService(
        repository=SqlRawSnapshotRepository(),
        blob_store=AzureBlobRawPayloadStore(),
        secret_reader=AzureKeyVaultSecretReader(),
        client_factory=EspnFantasyClient,
    )


def run_import_job(message: ImportJobMessage) -> WorkerRunResult:
    if message.job_type not in ESPN_RAW_INGESTION_JOB_TYPES:
        return WorkerRunResult.succeeded()
    return get_espn_raw_ingestion_service().run(message)


@app.queue_trigger(
    arg_name="message",
    queue_name="%IMPORT_JOBS_QUEUE_NAME%",
    connection="AzureWebJobsStorage",
)
def import_job_worker(message: func.QueueMessage) -> None:
    environment = os.getenv("LEAGUEBRIEF_ENVIRONMENT", "local")
    message_id = getattr(message, "id", None) or "unknown"
    dequeue_count = _dequeue_count(message)

    logging.info(
        "LeagueBrief worker received import job message.",
        extra={
            "environment": environment,
            "message_id": message_id,
            "dequeue_count": dequeue_count,
            "role": os.getenv("FUNCTION_APP_ROLE", os.getenv("APP_KIND", "worker")),
        },
    )

    WorkerService(get_worker_job_repository(), run_job=run_import_job).process_message(
        message.get_body(),
        dequeue_count=dequeue_count,
    )


def _dequeue_count(message: func.QueueMessage) -> int:
    for attr_name in ("dequeue_count", "dequeueCount"):
        value = getattr(message, attr_name, None)
        if isinstance(value, int) and value > 0:
            return value

    metadata = getattr(message, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("DequeueCount", "dequeueCount", "dequeue_count"):
            value = metadata.get(key)
            if isinstance(value, int) and value > 0:
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)

    return 1
