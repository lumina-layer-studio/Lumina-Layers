"""Community activity proxy using the existing, process-local account connection."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from api.routers.contributions import contribution_errors, local_client
from api.services.resource_contribution import connection

router = APIRouter(prefix="/api/community", tags=["Community"], dependencies=[Depends(local_client)])
Kind = Literal["materials", "luts"]


@router.get("/reports")
def feedback_history(offset: int = Query(default=0, ge=0, le=2**31-1)) -> dict[str, Any]:
    with contribution_errors():
        return connection.feedback_history(offset)


class ActivityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: str = Field(min_length=1, max_length=200)
    revision_id: str = Field(min_length=1, max_length=200)
    content_hash: str = Field(min_length=1, max_length=200)
    action: Literal["liked", "saved"]
    enabled: bool
    account_id: str = Field(min_length=1, max_length=200)


class FeedbackReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    resource_id: str = Field(min_length=1, max_length=200)
    revision_id: str = Field(min_length=1, max_length=200)
    content_hash: str = Field(pattern=r"^(sha256:)?[a-f0-9]{64}$")


class FeedbackReport(FeedbackReference):
    account_id: str = Field(min_length=1, max_length=200)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    category: Literal["attribution", "incorrect_data", "unsafe_link", "other"]
    message: str = Field(min_length=10, max_length=2000)
    evidence_url: str = Field(default="", max_length=2048)
    images: list[Annotated[str, Field(max_length=1_398_104)]] = Field(default_factory=list, max_length=3)


class FeedbackImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=200)
    image_id: str = Field(pattern=r"^[a-f0-9]{32}$")


@router.post("/{kind}/contributor")
def resource_contributor(kind: Kind, payload: FeedbackReference) -> dict[str, Any]:
    with contribution_errors():
        return connection.resource_feedback(kind, payload.model_dump(), "contributor")


@router.post("/{kind}/reports/mine")
def resource_reports(kind: Kind, payload: FeedbackReference) -> dict[str, Any]:
    with contribution_errors():
        return connection.resource_feedback(kind, payload.model_dump(), "mine")


@router.post("/{kind}/reports")
def report_resource(kind: Kind, payload: FeedbackReport) -> dict[str, Any]:
    with contribution_errors():
        return connection.resource_feedback(kind, payload.model_dump(exclude_unset=True), "submit")


@router.post("/reports/{report_id}/image")
def report_image(report_id: str, payload: FeedbackImageRequest) -> JSONResponse:
    with contribution_errors():
        return JSONResponse(connection.feedback_image(report_id, payload.image_id, payload.account_id),
                            headers={"Cache-Control": "no-store, private"})


@router.get("/{kind}/activity")
def activity(kind: Kind, resource_id: list[str] = Query(min_length=1, max_length=100)) -> dict[str, Any]:
    with contribution_errors():
        return connection.activity(kind, resource_id)


@router.get("/{kind}/mine")
def mine(kind: Kind) -> dict[str, Any]:
    with contribution_errors():
        return connection.my_activity(kind)


@router.put("/{kind}/activity")
def update(kind: Kind, payload: ActivityUpdate) -> dict[str, Any]:
    with contribution_errors():
        return connection.update_activity(kind, payload.model_dump())


@router.get("/{kind}/local-references")
def local_references(kind: Kind) -> dict[str, Any]:
    from api.services.resource_activity import local_resource_references
    return local_resource_references(kind)
