"""Backend-only access to Electron's OS-protected, workspace-local store."""
import os
import re
from typing import Any
from urllib.parse import urlsplit

import httpx


class CommunityVaultError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Protected account storage is unavailable.")


class CommunityVault:
    @property
    def available(self) -> bool:
        try:
            parsed = urlsplit(os.environ.get("LUMINA_COMMUNITY_VAULT_URL", ""))
            return bool(parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                        and parsed.port and parsed.path == "/" and not parsed.username
                        and not parsed.query and not parsed.fragment
                        and re.fullmatch(r"[a-f0-9]{64}", os.environ.get("LUMINA_COMMUNITY_VAULT_TOKEN", "")))
        except ValueError:
            return False

    def _call(self, action: str, source: str, value: Any = None) -> dict[str, Any]:
        if not self.available:
            return {}
        try:
            with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
                response = client.post(os.environ["LUMINA_COMMUNITY_VAULT_URL"],
                    headers={"X-Lumina-Vault": os.environ["LUMINA_COMMUNITY_VAULT_TOKEN"]},
                    json={"action": action, "source": source, "value": value})
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("Invalid vault response")
                return result
        except (httpx.HTTPError, ValueError):
            raise CommunityVaultError() from None

    def load(self, source: str) -> dict[str, Any] | None:
        return self._call("load", source).get("value")

    def save(self, source: str, value: dict[str, Any]) -> None:
        self._call("save", source, value)

    def delete(self, source: str) -> None:
        self._call("delete", source)
