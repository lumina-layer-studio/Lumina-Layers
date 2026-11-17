"""Migrations from legacy lumina-recipe inputs.

旧 lumina-recipe 输入迁移。
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from .errors import ProjectFormatError
from .schema import AssetBlob, ProjectSnapshot, WorkflowDocument


def migrate_legacy_recipe(raw: Any) -> ProjectSnapshot:
    """Convert a legacy recipe without inventing omitted editing state.

    将旧配方转换为工程，但不捏造旧格式不存在的编辑状态。
    """

    if not isinstance(raw, dict) or raw.get("format") != "lumina-recipe":
        raise ProjectFormatError("legacy input is not a lumina-recipe")
    assets: list[AssetBlob] = []
    raw_assets = raw.get("asset")
    if isinstance(raw_assets, dict):
        for asset_id, descriptor in raw_assets.items():
            if not isinstance(descriptor, dict):
                continue
            payload = descriptor.get("payload_b64")
            if descriptor.get("encoding") != "base64" or not isinstance(payload, str):
                continue
            try:
                data = base64.b64decode(payload, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ProjectFormatError(f"legacy asset is invalid: {asset_id}") from exc
            assets.append(
                AssetBlob(
                    asset_id=str(asset_id),
                    data=data,
                    media_type=str(
                        descriptor.get("mime_type") or "application/octet-stream"
                    ),
                    filename=descriptor.get("filename"),
                )
            )
    recipe = raw.get("recipe")
    if not isinstance(recipe, dict):
        recipe = {}
    converter = recipe.get("converter")
    if not isinstance(converter, dict):
        converter = {}
    document = WorkflowDocument(
        document_id="converter",
        kind="converter",
        schema_version=1,
        payload={
            "legacyRecipe": converter,
            "spatialEdits": None,
            "modelSurface": None,
        },
        resource_refs=tuple(asset.asset_id for asset in assets),
        required_capabilities=("converter.v1",),
    )
    return ProjectSnapshot.new(
        name=str(raw.get("name") or "Imported Lumina project"),
        workflow_kinds=("converter",),
        documents=(document,),
        assets=tuple(assets),
        degraded_fields=(
            "converter.color_ops.spatial_region_edits",
            "converter.model_surface",
        ),
        warnings=(
            "Legacy lumina-recipe did not contain spatial edits or model-surface data.",
        ),
    )
