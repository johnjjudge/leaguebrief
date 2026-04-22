from __future__ import annotations

import os
from collections.abc import Mapping


class SecretStoreConfigurationError(RuntimeError):
    """Raised when the secret store cannot be configured."""


class AzureKeyVaultSecretStore:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        values = env or os.environ
        key_vault_uri = values.get("KEY_VAULT_URI")
        if not key_vault_uri:
            raise SecretStoreConfigurationError("Missing KEY_VAULT_URI.")

        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
        except ImportError as exc:
            raise SecretStoreConfigurationError(
                "azure-identity and azure-keyvault-secrets are required for Key Vault."
            ) from exc

        self._client = SecretClient(
            vault_url=key_vault_uri,
            credential=DefaultAzureCredential(),
        )

    def set_secret(self, name: str, value: str) -> None:
        self._client.set_secret(name, value)
