import pytest

from api.services.resource_contribution import ContributionConnection, ContributionError
from api.services.community_vault import CommunityVaultError


class Vault:
    available = True
    def __init__(self):
        self.records = {}
    def load(self, source):
        return self.records.get(source)
    def save(self, source, value):
        self.records[source] = value
    def delete(self, source):
        self.records.pop(source, None)


def service(vault, monkeypatch):
    monkeypatch.setenv("LUMINA_CONTRIBUTION_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    instance = ContributionConnection()
    instance.vault = vault
    return instance


def test_connected_account_is_saved_and_restored_without_browser_approval(monkeypatch):
    vault = Vault()
    first = service(vault, monkeypatch)
    first.source()
    first._token = "studio_pending"
    first._code = "ABCDEFGHIJ"
    calls = []
    def request(method, path, **kwargs):
        calls.append(path)
        if path.endswith("/device") or path.endswith("/refresh"):
            return {"access_token": "studio_device_access", "refresh_token": "studio_refresh_secret",
                    "device_id": "d1", "access_expires_at": 9999999999, "refresh_expires_at": 99999999999}
        return {"state": "connected", "subject": "user-one", "display_name": "Maker"}
    monkeypatch.setattr(first, "_request", request)
    assert first.status()["persistent"] is True
    assert vault.records
    restored = service(vault, monkeypatch)
    monkeypatch.setattr(restored, "_request", request)
    assert restored.status()["subject"] == "user-one"
    assert "/auth/studio/refresh" in calls
    assert restored._token == "studio_device_access"
    assert "refresh_token" not in restored.status()


def test_connection_without_protected_storage_stays_session_only(monkeypatch):
    vault = Vault()
    vault.available = False
    current = service(vault, monkeypatch)
    current.source()
    current._token = "studio_pending"
    def request(method, path, **kwargs):
        assert path == "/auth/studio/status"
        return {"state": "connected", "subject": "user-one", "display_name": "Maker"}
    monkeypatch.setattr(current, "_request", request)
    assert current.status()["persistent"] is False
    assert not vault.records


def test_network_failure_does_not_forget_saved_account_but_revocation_does(monkeypatch):
    vault = Vault()
    current = service(vault, monkeypatch)
    source = current.source()
    vault.save(source, {"refresh_token": "studio_refresh_saved", "subject": "one"})
    def request(method, path, **kwargs):
        raise ContributionError(502, "Offline")
    monkeypatch.setattr(current, "_request", request)
    with pytest.raises(ContributionError):
        current.status()
    assert vault.load(source)
    def revoked(method, path, **kwargs):
        raise ContributionError(401, "Revoked")
    monkeypatch.setattr(current, "_request", revoked)
    assert current.status()["state"] == "disconnected"
    assert vault.load(source) is None


def test_logout_and_source_change_do_not_reuse_other_source_credentials(monkeypatch):
    vault = Vault()
    current = service(vault, monkeypatch)
    first = current.source()
    vault.save(first, {"refresh_token": "studio_refresh_one", "subject": "one"})
    monkeypatch.setenv("LUMINA_CONTRIBUTION_REGISTRY_URL", "https://other.example/api/material-registry/v1")
    assert current.status()["state"] == "disconnected"
    assert vault.load(first) is not None
    current._token = "studio_device_two"
    vault.save(current.source(), {"refresh_token": "studio_refresh_two", "subject": "two"})
    monkeypatch.setattr(current, "_request", lambda *a, **k: {"state": "disconnected"})
    assert current.disconnect()["state"] == "disconnected"
    assert vault.load(current.source()) is None
    assert vault.load(first) is not None


def test_store_failure_keeps_a_temporary_connection_and_recovers(monkeypatch):
    vault = Vault()
    current = service(vault, monkeypatch)
    current.source()
    current._token = "studio_pending"
    def request(method, path, **kwargs):
        if path.endswith("/device"):
            return {"access_token": "studio_device_access", "refresh_token": "studio_refresh_secret",
                    "device_id": "d1", "access_expires_at": 9999999999}
        return {"state": "connected", "subject": "user-one", "display_name": "Maker"}
    monkeypatch.setattr(current, "_request", request)
    def broken(*args):
        raise CommunityVaultError()
    monkeypatch.setattr(vault, "save", broken)
    assert current.status()["persistent"] is False
    assert current.status()["state"] == "connected"
    assert current._token == "studio_device_access"
    monkeypatch.setattr(vault, "save", lambda source, value: vault.records.update({source: value}))
    assert current.status()["persistent"] is True
    assert vault.records


def test_unreadable_or_malformed_vault_does_not_block_session_login(monkeypatch):
    vault = Vault()
    current = service(vault, monkeypatch)
    def broken(*args):
        raise CommunityVaultError()
    monkeypatch.setattr(vault, "load", broken)
    assert current.status()["state"] == "disconnected"
    assert current.status()["can_remember"] is False
    monkeypatch.setattr(vault, "load", lambda source: ["corrupt"])
    assert current.status()["state"] == "disconnected"


def test_old_registry_can_keep_its_approved_temporary_connection(monkeypatch):
    current = service(Vault(), monkeypatch)
    current.source()
    current._token = "studio_pending"
    calls = []
    def request(method, path, **kwargs):
        calls.append(path)
        if path.endswith("/device"):
            raise ContributionError(503, "This material server needs the Studio community update.")
        return {"state": "connected", "subject": "user-one", "display_name": "Maker"}
    monkeypatch.setattr(current, "_request", request)
    assert current.status()["state"] == "connected"
    assert current.status()["persistent"] is False
    assert calls.count("/auth/studio/device") == 1


def test_disconnect_after_restart_restores_only_to_revoke(monkeypatch):
    vault = Vault()
    current = service(vault, monkeypatch)
    vault.save(current.source(), {"refresh_token": "studio_refresh_saved", "subject": "user-one"})
    calls = []
    def request(method, path, **kwargs):
        calls.append(path)
        if path.endswith("/refresh"):
            return {"access_token": "studio_device_access", "refresh_token": "studio_refresh_next",
                    "device_id": "d1", "access_expires_at": 9999999999}
        return {"state": "disconnected"}
    monkeypatch.setattr(current, "_request", request)
    assert current.disconnect()["state"] == "disconnected"
    assert calls == ["/auth/studio/refresh", "/auth/studio/disconnect"]
    assert not vault.records


def test_offline_disconnect_clears_local_account_and_reports_unfinished_revocation(monkeypatch):
    vault = Vault()
    current = service(vault, monkeypatch)
    vault.save(current.source(), {"refresh_token": "studio_refresh_saved", "subject": "user-one"})
    def offline(*args, **kwargs):
        raise ContributionError(502, "Offline")
    monkeypatch.setattr(current, "_request", offline)
    result = current.disconnect()
    assert result["state"] == "disconnected"
    assert result["disconnect_incomplete"] is True
    assert not vault.records
