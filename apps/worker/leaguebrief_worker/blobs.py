from __future__ import annotations

import os
from collections.abc import Mapping


class RawBlobStoreConfigurationError(RuntimeError):
    """Raised when raw blob storage cannot be configured."""


class AzureBlobRawPayloadStore:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        values = env or os.environ
        connection_string = values.get("AzureWebJobsStorage")
        container_name = values.get("STORAGE_RAW_ESPN_CONTAINER")
        missing = [
            name
            for name, value in (
                ("AzureWebJobsStorage", connection_string),
                ("STORAGE_RAW_ESPN_CONTAINER", container_name),
            )
            if not value
        ]
        if missing:
            raise RawBlobStoreConfigurationError(
                "Missing raw blob storage settings: " + ", ".join(missing)
            )

        try:
            from azure.storage.blob import BlobServiceClient, ContentSettings
        except ImportError as exc:
            raise RawBlobStoreConfigurationError(
                "azure-storage-blob is required for raw ESPN payload storage."
            ) from exc

        self._content_settings_factory = ContentSettings
        self._client = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container_name

    def upload_json_bytes(self, blob_path: str, payload: bytes) -> None:
        blob_client = self._client.get_blob_client(
            container=self._container_name,
            blob=blob_path,
        )
        blob_client.upload_blob(
            payload,
            overwrite=True,
            content_settings=self._content_settings_factory(
                content_type="application/json; charset=utf-8"
            ),
        )

    def download_json_bytes(self, blob_path: str) -> bytes:
        blob_client = self._client.get_blob_client(
            container=self._container_name,
            blob=blob_path,
        )
        return blob_client.download_blob().readall()
