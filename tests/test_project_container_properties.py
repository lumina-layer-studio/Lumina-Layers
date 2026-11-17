from __future__ import annotations

from hypothesis import given, strategies as st

from core.projects.container import build_project_bytes, read_project
from core.projects.schema import AssetBlob, ProjectSnapshot, WorkflowDocument


@given(st.binary(min_size=0, max_size=2048))
def test_binary_asset_round_trip_is_content_addressed(payload: bytes) -> None:
    snapshot = ProjectSnapshot.new(
        name="property",
        workflow_kinds=("converter",),
        documents=(
            WorkflowDocument(
                document_id="doc",
                kind="converter",
                schema_version=1,
                payload={"source": None},
                resource_refs=("asset",),
            ),
        ),
        assets=(
            AssetBlob(
                asset_id="asset",
                data=payload,
                media_type="application/octet-stream",
                filename="payload.bin",
            ),
        ),
    )

    restored = read_project(build_project_bytes(snapshot))
    assert restored.assets["asset"].sha256 == snapshot.assets["asset"].sha256
    assert restored.assets["asset"].data == payload
