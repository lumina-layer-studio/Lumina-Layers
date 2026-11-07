import pytest
from pydantic import ValidationError
from core.workshop.models import WorkshopManifestV1


def manifest():
    return {"manifestVersion": 1, "id": "fixture.editor", "version": "1.0.0", "name": {"zh-CN": "编辑器", "en-US": "Editor"}, "description": {"zh-CN": "编辑器", "en-US": "Editor"}, "publisher": "Fixture", "workshopApi": {"min": "1.0.0", "maxExclusive": "2.0.0"}, "luminaVersion": {"min": "2.0.0"}, "entrypoints": {"ui": "ui/index.html"}, "permissions": [{"name": "project.storage", "reason": "Save edits"}]}


def test_optional_workshop_snapshot_capability_preserves_old_modules():
    value = manifest()
    assert WorkshopManifestV1.model_validate(value).project_snapshots is None
    value["projectSnapshots"] = {"protocol": 1, "schemas": ["editor/v1"]}
    assert WorkshopManifestV1.model_validate(value).project_snapshots.schemas == ("editor/v1",)
    value["permissions"] = []
    with pytest.raises(ValidationError, match="project.storage"):
        WorkshopManifestV1.model_validate(value)


@pytest.mark.parametrize("capability", [{"protocol": 2, "schemas": ["editor/v1"]}, {"protocol": 1, "schemas": []}, {"protocol": 1, "schemas": ["editor/v1", "editor/v1"]}, {"protocol": 1, "schemas": ["x" * 129]}])
def test_workshop_snapshot_capabilities_reject_unknown_or_unbounded_schemas(capability):
    value = manifest()
    value["projectSnapshots"] = capability
    with pytest.raises(ValidationError):
        WorkshopManifestV1.model_validate(value)
