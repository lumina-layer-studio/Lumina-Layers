import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import resource_activity
from api.services.resource_contribution import ContributionConnection, ContributionError

REF = {"resource_id": "mat_red", "revision_id": "revision_one", "content_hash": "sha256:" + "a" * 64}
HEADERS = {"X-Lumina-Contribution": "1"}


def test_feedback_proxy_accepts_only_local_clients_and_bounded_resource_payloads(monkeypatch):
    calls = []
    monkeypatch.setattr(resource_activity.connection, "resource_feedback", lambda *args: calls.append(args) or {"contributor": None})
    app = FastAPI()
    app.include_router(resource_activity.router)
    with TestClient(app) as client:
        path = "/api/community/materials/contributor"
        assert client.post(path, json=REF).status_code == 403
        assert client.post(path, json=REF, headers={**HEADERS, "Origin": "https://unrelated.test"}).status_code == 403
        assert client.post(path, json={**REF, "url": "https://unrelated.test"}, headers=HEADERS).status_code == 422
        assert client.post(path, json={**REF, "content_hash": "invalid"}, headers=HEADERS).status_code == 422
        assert client.post(path, json=REF, headers=HEADERS).json() == {"contributor": None}
    assert calls == [("materials", REF, "contributor")]


def test_report_connection_pins_writes_to_the_current_account(monkeypatch):
    connection = ContributionConnection()
    calls = []
    monkeypatch.setattr(connection, "status", lambda: {"state": "connected", "subject": "maker"})
    monkeypatch.setattr(connection, "_request", lambda *args, **kwargs: calls.append((args, kwargs)) or {})
    with pytest.raises(ContributionError, match="account changed"):
        connection.resource_feedback("materials", {**REF, "account_id": "another"}, "submit")
    assert calls == []
    connection.resource_feedback("materials", {**REF, "account_id": "maker"}, "submit")
    assert calls[0][0] == ("POST", "/me/resources/materials/reports")
    assert calls[0][1]["json"]["account_id"] == "maker"
    assert calls[0][1]["preserve_resource_errors"] is True


def test_public_lookup_does_not_require_account_or_install_resources(monkeypatch):
    connection = ContributionConnection()
    monkeypatch.setattr(connection, "status", lambda: pytest.fail("Public contact lookup must not start authentication"))
    calls = []
    monkeypatch.setattr(connection, "_request", lambda *args, **kwargs: calls.append((args, kwargs)) or {"contributor": None})
    assert connection.resource_feedback("luts", REF, "contributor") == {"contributor": None}
    assert calls == [(("GET", "/resources/luts/contributor"), {"params": REF, "preserve_resource_errors": True})]


def test_public_lookup_keeps_only_the_contributor_identity(monkeypatch):
    connection = ContributionConnection()
    monkeypatch.setattr(connection, "_request", lambda *args, **kwargs: {
        "contributor": {"id": "author-id", "display_name": "Author", "contact_url": "https://example.test/contact"},
    })
    assert connection.resource_feedback("luts", REF, "contributor") == {
        "contributor": {"id": "author-id", "display_name": "Author"},
    }


def test_private_image_reads_pin_the_current_account(monkeypatch):
    connection = ContributionConnection()
    calls = []
    monkeypatch.setattr(connection, "status", lambda: {"state": "connected", "subject": "maker"})
    monkeypatch.setattr(connection, "_request", lambda *args, **kwargs: calls.append((args, kwargs)) or {"subject": "maker", "data_url": "data:image/jpeg;base64,YQ=="})
    with pytest.raises(ContributionError, match="account changed"):
        connection.feedback_image("a" * 32, "b" * 32, "another")
    assert not calls
    assert connection.feedback_image("a" * 32, "b" * 32, "maker")["subject"] == "maker"
    assert calls[0][0] == ("GET", "/me/resource-reports/" + "a" * 32 + "/images/" + "b" * 32)


@pytest.mark.parametrize("status", [403, 404])
def test_resource_permission_or_missing_revision_does_not_disconnect_a_healthy_account(monkeypatch, status):
    import api.services.resource_contribution as service
    connection = ContributionConnection()
    connection._token = "studio_current"
    monkeypatch.setattr(connection, "source", lambda: "https://example.test/api/material-registry/v1")
    original_client = httpx.Client
    monkeypatch.setattr(service.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={"detail": "Check account verification or resource availability."})), **kwargs))
    with pytest.raises(ContributionError) as result:
        connection._request("POST", "/me/resources/materials/reports", json={}, preserve_resource_errors=True)
    assert result.value.status == status
    assert connection._token == "studio_current"
