import logging
import os

import azure.functions as func
from leaguebrief_worker.db.jobs import SqlWorkerJobRepository
from leaguebrief_worker.jobs import WorkerService

app = func.FunctionApp()


def get_worker_job_repository() -> SqlWorkerJobRepository:
    return SqlWorkerJobRepository()


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

    WorkerService(get_worker_job_repository()).process_message(
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
