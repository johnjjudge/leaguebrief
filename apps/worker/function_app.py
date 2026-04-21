import logging
import os

import azure.functions as func

app = func.FunctionApp()


@app.queue_trigger(
    arg_name="message",
    queue_name="%IMPORT_JOBS_QUEUE_NAME%",
    connection="AzureWebJobsStorage",
)
def import_job_placeholder(message: func.QueueMessage) -> None:
    environment = os.getenv("LEAGUEBRIEF_ENVIRONMENT", "local")
    message_id = getattr(message, "id", None) or "unknown"

    logging.info(
        "LeagueBrief worker placeholder received import job message.",
        extra={
            "environment": environment,
            "message_id": message_id,
            "role": os.getenv("FUNCTION_APP_ROLE", os.getenv("APP_KIND", "worker")),
        },
    )
