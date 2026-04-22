from __future__ import annotations

import os
from collections.abc import Mapping


class SecretReaderConfigurationError(RuntimeError):
    """Raised when Key Vault secret reads cannot be configured."""


class AzureKeyVaultSecretReader:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        values = env or os.environ
        key_vault_uri = values.get("KEY_VAULT_URI")
        if not key_vault_uri:
            raise SecretReaderConfigurationError("Missing KEY_VAULT_URI.")

        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
        except ImportError as exc:
            raise SecretReaderConfigurationError(
                "azure-identity and azure-keyvault-secrets are required for Key Vault."
            ) from exc

        self._client = SecretClient(
            vault_url=key_vault_uri,
            credential=DefaultAzureCredential(),
        )

    def get_secret(self, name: str) -> str:
        secret = self._client.get_secret(name)
        value = getattr(secret, "value", None)
        if not isinstance(value, str) or not value:
            raise SecretReaderConfigurationError("Key Vault secret value is empty.")
        return value
