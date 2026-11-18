import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.contributions import router
from api.services.resource_contribution import ContributionConnection, ContributionError
from core.resource_contribution import PreparedContribution, contribution_package, prepare_owned_revision


@pytest.mark.parametrize("kind", ["materials", "luts"])
def test_remote_metadata_revision_keeps_resource_identity_and_technical_files(kind):
    files = ({"material.json": b'{"kind":"lumina_stage_a_material"}', "stage_A_parameters.json": b'{"parameters":{"E":[1,2,3]}}'}
             if kind == "materials" else {"calibration.msgpack": b"original-lut-bytes"})
    display = {"brand": "Brand", "material_type": "PLA", "name": "Original", "attribution": {"relationship": "original"}}
    source = PreparedContribution(kind, "original-local-key", "a" * 64, display, {"layer_order": "bottom_to_top"}, files)
    payload, resource_id, revision_id = contribution_package(source, display, "maker")
    prepared = prepare_owned_revision(kind, resource_id, revision_id, payload, display)
    changed, same_id, new_revision = contribution_package(prepared, {**display, "color_code": "101"}, "maker")
    assert same_id == resource_id and new_revision != revision_id
    with zipfile.ZipFile(io.BytesIO(changed)) as archive:
        if kind == "materials":
            assert archive.read(f"materials/{resource_id}/stage_A_parameters.json") == files["stage_A_parameters.json"]
        else:
            assert archive.read("calibration.msgpack") == files["calibration.msgpack"]
    assert prepared.compatibility == source.compatibility
    with pytest.raises(ValueError, match="identity"):
        prepare_owned_revision(kind, "someone-else", revision_id, payload, display)


def test_owned_revision_validates_each_calibration_file():
    source = PreparedContribution("luts", "BW", "a" * 64, {}, {}, {"calibration.json": b'{"entries":[]}'})
    payload, resource_id, revision_id = contribution_package(source, {}, "maker")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = archive.read("lumina_lut_bundle.json")
    tampered = io.BytesIO()
    with zipfile.ZipFile(tampered, "w") as archive:
        archive.writestr("lumina_lut_bundle.json", manifest)
        archive.writestr("calibration.json", b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        prepare_owned_revision("luts", resource_id, revision_id, tampered.getvalue(), {})


def test_review_actions_bind_original_account_and_revision(monkeypatch):
    service = ContributionConnection()
    monkeypatch.setattr(service, "status", lambda: {"state": "connected", "subject": "maker"})
    monkeypatch.setattr(service, "history", lambda: [{"kind": "luts", "lut_id": "lut_one", "revision_id": "rev_one", "status": "pending"}])
    calls = []
    monkeypatch.setattr(service, "_request", lambda *args, **kwargs: calls.append(args) or {"status": "withdrawn"})
    with pytest.raises(ContributionError):
        service.review_action("luts", "lut_one", "rev_one", "withdraw", "another-account")
    with pytest.raises(ContributionError):
        service.review_action("luts", "lut_another", "rev_one", "withdraw", "maker")
    assert calls == []
    assert service.review_action("luts", "lut_one", "rev_one", "withdraw", "maker")["status"] == "withdrawn"
    assert calls == [("POST", "/me/lut-submissions/lut_one/rev_one/withdraw")]


def test_revision_prepare_requires_local_origin_and_expected_account(monkeypatch):
    calls = []
    from api.services.resource_contribution import connection
    monkeypatch.setattr(connection, "prepare_revision", lambda *args: calls.append(args) or PreparedContribution("luts", "remote", "a" * 64, {}, {}, {}))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        payload = {"kind": "luts", "resource_id": "lut_one", "revision_id": "rev_one", "account_id": "maker"}
        assert client.post("/api/contributions/prepare-revision", json=payload).status_code == 403
        result = client.post("/api/contributions/prepare-revision", headers={"X-Lumina-Contribution": "1"}, json=payload)
        assert result.status_code == 200, result.text
    assert calls == [("luts", "lut_one", "rev_one", "maker")]


def test_product_templates_keep_regional_names_and_multiple_purchase_links():
    from api.routers.contributions import Product
    product = Product(brand="Brand", material_type="PLA", market_names={"CN": "中国商品名", "INTL": "International name"},
                      purchase_url="https://shop.test/cn?id=001", market="CN",
                      purchase_links=[{"url": "https://shop.test/global", "market": "INTL", "label": "Official store"}])
    display = product.display()
    assert display["market_names"] == {"CN": "中国商品名", "INTL": "International name"}
    assert display["purchase_links"] == [{"url": "https://shop.test/cn?id=001", "market": "CN"},
                                         {"url": "https://shop.test/global", "market": "INTL", "label": "Official store"}]
    with pytest.raises(ValueError):
        Product(purchase_links=[{"url": "https://private:secret@shop.test/"}])
    with pytest.raises(ValueError):
        Product(market_names={"CN": "x" * 201})
