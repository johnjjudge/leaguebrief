from __future__ import annotations

import os
from collections.abc import Mapping


class QueueConfigurationError(RuntimeError):
    """Raised when a queue client cannot be configured."""


class AzureStorageImportJobQueue:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        values = env or os.environ
        connection_string = values.get("AzureWebJobsStorage")
        queue_name = values.get("IMPORT_JOBS_QUEUE_NAME")
        missing = [
            name
            for name, value in (
                ("AzureWebJobsStorage", connection_string),
                ("IMPORT_JOBS_QUEUE_NAME", queue_name),
            )
            if not value
        ]
        if missing:
            raise QueueConfigurationError(
                "Missing queue settings: " + ", ".join(missing)
            )

        try:
            from azure.storage.queue import QueueClient
        except ImportError as exc:
            raise QueueConfigurationError(
                "azure-storage-queue is required for import job enqueueing."
            ) from exc

        self._client = QueueClient.from_connection_string(
            conn_str=connection_string,
            queue_name=queue_name,
        )

    def enqueue(self, message: str) -> None:
        self._client.send_message(message)
