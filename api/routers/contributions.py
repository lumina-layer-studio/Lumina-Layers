"""Prepare, confirm and follow up manual public resource contributions."""

import base64
import binascii
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from ipaddress import ip_address
import os
import sqlite3
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
import warnings
import zipfile

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.services.resource_contribution import ContributionError, configured_contribution_server, connection
from core.resource_contribution import prepare_contribution
from core.resource_attribution import normalize_attribution
from api.services.resource_activity import local_resource_origin, preserve_origin_license


def _is_allowed_browser_origin(browser_url: str) -> bool:
    try:
        parsed = urlsplit(browser_url)
        host = parsed.hostname
        _ = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None:
        return False
    host = host.rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        if ip_address(host).is_loopback:
            return True
    except ValueError:
        pass

    origin = f"{parsed.scheme}://{parsed.netloc}"
    configured = os.environ.get("LUMINA_CONTRIBUTION_ALLOWED_ORIGINS", "").split(",")
    return any(origin == value.strip().rstrip("/") for value in configured)


def local_client(request: Request, response: Response, x_lumina_contribution: str = Header(default="")) -> None:
    # Same-origin GET requests may carry only a Referer.
    browser_url = request.headers.get("Origin", request.headers.get("Referer"))
    if x_lumina_contribution != "1" or (
        browser_url is not None and not _is_allowed_browser_origin(browser_url)
    ):
        raise HTTPException(403, "Open the contribution dialog in Lumina Studio.")
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/contributions", tags=["Contributions"], dependencies=[Depends(local_client)])


class PurchaseLink(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    url: str = Field(min_length=1, max_length=2048)
    market: Literal["CN", "INTL", "ALL"] = "ALL"
    label: str = Field(default="", max_length=100)

    @field_validator("url")
    @classmethod
    def public_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        parsed.port
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use a public HTTP(S) product link without credentials.")
        return value


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    brand: str = Field(default="", max_length=200)
    material_type: str = Field(default="", max_length=200)
    series: str = Field(default="", max_length=200)
    color_name: str = Field(default="", max_length=200)
    color_code: str = Field(default="", max_length=200)
    sku: str = Field(default="", max_length=200)
    material_id: str = Field(default="", max_length=200)
    revision_id: str = Field(default="", max_length=200)
    purchase_url: str = Field(default="", max_length=2048)
    market: Literal["", "CN", "INTL", "ALL"] = "ALL"
    purchase_links: list[PurchaseLink] = Field(default_factory=list, max_length=7)
    market_names: dict[Literal["CN", "INTL"], str] = Field(default_factory=dict, max_length=2)

    @field_validator("market_names")
    @classmethod
    def regional_names(cls, value: dict[str, str]) -> dict[str, str]:
        if any(len(name) > 200 for name in value.values()):
            raise ValueError("Regional product names must contain at most 200 characters.")
        return {key: name.strip() for key, name in value.items() if name.strip()}

    @field_validator("purchase_url")
    @classmethod
    def public_url(cls, value: str) -> str:
        if value:
            parsed = urlsplit(value)
            parsed.port
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use a public HTTP(S) product link without credentials.")
        return value

    def display(self) -> dict[str, Any]:
        result = self.model_dump(exclude={"purchase_url", "market", "purchase_links", "market_names"})
        if not self.material_id or not self.revision_id:
            result.pop("material_id", None)
            result.pop("revision_id", None)
        links = ([{"url": self.purchase_url, "market": self.market}] if self.purchase_url else []) + [link.model_dump() for link in self.purchase_links]
        if links:
            result["purchase_links"] = links
        if self.market_names:
            result["market_names"] = self.market_names
        return result


class ResourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["materials", "luts"]
    key: str = Field(min_length=1, max_length=1024)


class OwnedRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["materials", "luts"]
    resource_id: str = Field(min_length=1, max_length=200)
    revision_id: str = Field(min_length=1, max_length=200)


PrintImageRole = Literal["white_card", "black_card", "calibration_board", "finished_print"]


class PrintImagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: PrintImageRole
    data: str = Field(min_length=1, max_length=1_500_000)


def _clean_and_verify_print_photo(raw_val: str) -> str:
    cleaned = raw_val.split(",", 1)[1] if raw_val.startswith("data:image/") and "," in raw_val else raw_val
    try:
        decoded = base64.b64decode(cleaned, validate=True)
    except binascii.Error as exc:
        raise ValueError("Could not read this print photo. Use JPG, PNG or WebP.") from exc
    if not decoded or len(decoded) > 1024 * 1024:
        raise ValueError("Each print photo must be under 1 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(decoded)) as img:
                if (
                    img.format not in {"JPEG", "PNG", "WEBP"}
                    or getattr(img, "is_animated", False)
                    or img.width * img.height > 16_000_000
                ):
                    raise ValueError("Use a static JPG, PNG or WebP print photo.")
                img.load()
    except ValueError:
        raise
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Could not read this print photo. Use JPG, PNG or WebP.") from exc
    return cleaned


_ALLOWED_PRINT_ROLES: dict[str, set[str]] = {
    "materials": {"white_card", "black_card", "finished_print"},
    "luts": {"calibration_board", "finished_print"},
}
_REQUIRED_PRINT_ROLES: dict[str, tuple[str, ...]] = {
    "materials": ("white_card", "black_card", "finished_print"),
    "luts": ("calibration_board", "finished_print"),
}
_MAX_PRINT_ROLE_COUNTS: dict[str, int] = {
    "white_card": 1,
    "black_card": 1,
    "calibration_board": 2,
    "finished_print": 2,
}


def _validate_contribution_print_images(
    kind: Literal["materials", "luts"],
    photos: list[Any],
    *,
    require_present: bool,
) -> None:
    if not photos:
        if require_present:
            raise HTTPException(422, "Attach at least one actual print photo for review.")
        return
    if all(isinstance(entry, str) for entry in photos):
        return
    if not all(isinstance(entry, dict) for entry in photos):
        raise HTTPException(422, "Use a consistent print photo format.")
    allowed = _ALLOWED_PRINT_ROLES[kind]
    counts: dict[str, int] = {}
    for entry in photos:
        role = str(entry.get("role") or "")
        if role not in allowed:
            raise HTTPException(422, "Print photo slot does not match this resource kind.")
        counts[role] = counts.get(role, 0) + 1
        if counts[role] > _MAX_PRINT_ROLE_COUNTS.get(role, 4):
            raise HTTPException(422, "Too many print photos in a single slot.")
    required = _REQUIRED_PRINT_ROLES[kind]
    if any(counts.get(req, 0) < 1 for req in required):
        if kind == "materials":
            raise HTTPException(
                422,
                "Attach photos of the white-backing gradient card, black-backing gradient card, and at least one finished print.",
            )
        raise HTTPException(
            422,
            "Attach at least one calibration board photo and at least one finished print photo.",
        )


class ContributionRequest(ResourceSelection):
    queue_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    product: Product
    filaments: list[Product] = Field(default_factory=list, max_length=16)
    consent: Literal[True]
    account_id: str = Field(min_length=1, max_length=200)
    attribution: dict[str, Any]
    revision: OwnedRevision | None = None
    updates_resource_id: str | None = Field(default=None, min_length=1, max_length=200)
    print_images: list[
        Annotated[str, Field(min_length=1, max_length=1_500_000)] | PrintImagePayload
    ] = Field(default_factory=list, max_length=4)

    @field_validator("print_images")
    @classmethod
    def valid_print_images(cls, values: list[str | PrintImagePayload]) -> list[Any]:
        if not values:
            return []
        if all(isinstance(item, str) for item in values):
            return [_clean_and_verify_print_photo(item) for item in values if isinstance(item, str)]
        if all(isinstance(item, PrintImagePayload) for item in values):
            return [
                {"role": item.role, "data": _clean_and_verify_print_photo(item.data)}
                for item in values
                if isinstance(item, PrintImagePayload)
            ]
        raise ValueError("Use a consistent print photo format.")

    @field_validator("attribution")
    @classmethod
    def public_attribution(cls, value: dict[str, Any]) -> dict[str, Any]:
        # The original installed reference is attached by the backend below.
        # Validate fields after that attachment so it can replace a source URL.
        if not isinstance(value.get("relationship"), str) or value["relationship"] not in {"original", "adapted", "redistributed"}:
            raise ValueError("Choose the origin of this calibration.")
        if set(value) - {"relationship", "original_author", "source_url", "rights_basis"}:
            raise ValueError("Source identities are resolved from the installed resource.")
        return value


@contextmanager
def contribution_errors() -> Iterator[None]:
    try:
        yield
    except ContributionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "The selected local resource no longer exists. Refresh your library.") from exc
    except sqlite3.Error as exc:
        raise HTTPException(503, "The contribution queue is unavailable. Check local storage and retry.") from exc
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as exc:
        raise HTTPException(422, "Check the selected calibration data and contribution fields.") from exc


@router.get("/connection")
def status() -> dict[str, Any]:
    with contribution_errors():
        return connection.status()


@router.get("/connection/server")
def contribution_server() -> dict[str, str]:
    with contribution_errors():
        return {"server": configured_contribution_server()}


@router.post("/connection")
def start() -> dict[str, Any]:
    with contribution_errors():
        return connection.start()


@router.delete("/connection")
def disconnect() -> dict[str, Any]:
    with contribution_errors():
        from api.services.contribution_queue import queue_store
        queue = queue_store()
        if queue.path.exists():
            queue.pause(connection.source())
        return connection.disconnect()


@router.post("/prepare")
def prepare(request: ResourceSelection) -> dict[str, Any]:
    with contribution_errors():
        prepared = prepare_contribution(request.kind, request.key)
        origin = local_resource_origin(request.kind, request.key)
        prepared.display = preserve_origin_license(prepared.display, origin)
        return {**prepared.summary(), "origin": origin}


@router.get("/history")
def history() -> dict[str, Any]:
    with contribution_errors():
        return {"items": connection.history()}


class PrepareRevisionRequest(OwnedRevision):
    account_id: str = Field(min_length=1, max_length=200)


class OriginalSourceRequest(PrepareRevisionRequest):
    content_hash: str = Field(pattern=r"^(sha256:)?[a-f0-9]{64}$")


@router.post("/original-source")
def original_source(request: OriginalSourceRequest) -> dict[str, bool]:
    with contribution_errors():
        return {"eligible": connection.owns_original_source(**request.model_dump())}


@router.post("/prepare-revision")
def prepare_revision(request: PrepareRevisionRequest) -> dict[str, Any]:
    with contribution_errors():
        prepared = connection.prepare_revision(request.kind, request.resource_id, request.revision_id, request.account_id)
        return {**prepared.summary(), "origin": _revision_origin(prepared.display)}


def _revision_origin(display: dict[str, Any]) -> dict[str, Any] | None:
    prior = display.get("attribution") or {}
    if not prior or prior.get("relationship") == "original":
        return None
    return {"reference": prior.get("source"), "modified": prior.get("relationship") == "adapted",
            "original_author": prior.get("original_author", ""), "rights_basis": prior.get("rights_basis", "")}


class ReviewActionRequest(PrepareRevisionRequest):
    action: Literal["withdraw", "submit"]


@router.post("/review-action")
def review_action(request: ReviewActionRequest) -> dict[str, Any]:
    with contribution_errors():
        return connection.review_action(request.kind, request.resource_id, request.revision_id, request.action, request.account_id)


@router.post("/submit")
def submit(request: ContributionRequest) -> dict[str, Any]:
    with contribution_errors():
        if request.queue_id and request.updates_resource_id:
            raise HTTPException(422, "Review queued calibrations before linking a different resource.")
        if request.revision:
            if request.queue_id or request.revision.kind != request.kind:
                raise HTTPException(422, "Choose a single contribution revision.")
            prepared = connection.prepare_revision(request.kind, request.revision.resource_id, request.revision.revision_id, request.account_id)
            if request.key != prepared.key:
                raise HTTPException(409, "The revision changed. Reopen the contribution form.")
            origin = _revision_origin(prepared.display)
        elif request.queue_id:
            from api.services.contribution_queue import queue_store
            queue = queue_store()
            job, prepared, origin = queue.snapshot(connection.source(), request.queue_id)
            if job["account"] != request.account_id or prepared.kind != request.kind or prepared.key != request.key:
                raise HTTPException(409, "Reconnect the account that created this contribution.")
        else:
            prepared = prepare_contribution(request.kind, request.key)
            origin = local_resource_origin(request.kind, request.key)
        prepared.display = preserve_origin_license(prepared.display, origin)
        if prepared.fingerprint != request.fingerprint:
            raise HTTPException(409, "The local resource changed. Reopen the contribution form.")
        attribution = dict(request.attribution)
        if origin:
            reference = origin["reference"]
            if attribution["relationship"] == "original":
                if (request.revision or request.queue_id or not reference
                        or not connection.owns_original_source(**reference, account_id=request.account_id)):
                    raise HTTPException(422, "This resource has a public source. Preserve its original attribution.")
                if request.updates_resource_id and request.updates_resource_id != reference["resource_id"]:
                    raise HTTPException(422, "An original public contribution can only update its own resource.")
                prepared.resource_id = reference["resource_id"]
            elif reference:
                attribution["source"] = reference
        attribution = normalize_attribution(attribution)
        if request.kind == "materials" and (not request.product.brand or not request.product.material_type):
            raise HTTPException(422, "Brand and material type are required.")
        display = {**request.product.display(), "description": request.description, "attribution": attribution}
        display.pop("material_id", None)
        display.pop("revision_id", None)
        if request.kind == "materials":
            display["material_name"] = request.name
            if "estimated_rgb" in prepared.display:
                display["estimated_rgb"] = prepared.display["estimated_rgb"]
            if "preview_swatches" in prepared.display:
                display["preview_swatches"] = prepared.display["preview_swatches"]
        else:
            display["name"] = request.name
            original_slots = prepared.display.get("filaments", [])
            if not original_slots or len(request.filaments) != len(original_slots):
                raise HTTPException(422, "Keep every LUT filament channel in its original order.")
            if any(not row.brand or not row.material_type or not row.color_name for row in request.filaments):
                raise HTTPException(422, "Confirm the brand, material and color of each LUT channel.")
            display["filaments"] = [
                {**original, **product.display()}
                for original, product in zip(original_slots, request.filaments)
            ]
            for field in ("brand", "material_type"):
                values = {getattr(row, field) for row in request.filaments}
                display[field] = next(iter(values)) if len(values) == 1 else ""
        if request.queue_id:
            status = connection.status()
            if status.get("state") != "connected" or status.get("subject") != request.account_id:
                raise HTTPException(409, "Reconnect the account that created this contribution.")
            if not status.get("email_verified"):
                raise HTTPException(403, "Verify your email in the material library first.")
            stored_photos = request.print_images or queue.print_images(connection.source(), request.queue_id)
            _validate_contribution_print_images(request.kind, stored_photos, require_present=True)
            queue.review(connection.source(), request.queue_id, request.account_id, display, print_images=stored_photos)
            return {"kind": request.kind, "status": "queued", "queue_id": request.queue_id}
        if request.updates_resource_id and request.revision:
            raise HTTPException(422, "The correction is already bound to its original resource.")
        if request.updates_resource_id and prepared.resource_id is None:
            with connection.lock:
                rows = connection.history()
                field = "material_id" if request.kind == "materials" else "lut_id"
                target = next((row for row in rows if row["kind"] == request.kind and row.get(field) == request.updates_resource_id), None)
                if not target:
                    raise HTTPException(404, "The selected resource does not belong to the connected account.")
                connection.owned_revision(request.kind, target[field], target["revision_id"], request.account_id)
                prepared.resource_id = target[field]
        is_existing_owned = bool(request.revision or prepared.resource_id)
        _validate_contribution_print_images(
            request.kind,
            request.print_images,
            require_present=not is_existing_owned,
        )
        submit_kwargs = {"print_images": request.print_images} if request.print_images else {}
        return connection.submit(prepared, display, expected_subject=request.account_id, **submit_kwargs)


class AutomaticContributionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=200)
    enabled: bool
    consent: bool = False


@router.get("/queue")
def pending_contributions() -> dict[str, Any]:
    from api.services.contribution_queue import queue_store
    with contribution_errors():
        queue = queue_store()
        if not queue.path.exists():
            return {"enabled": False, "account_id": None, "items": []}
        server = connection.source()
        grant = queue.grant(server)
        return {"enabled": bool(grant and grant["enabled"]),
                "account_id": grant["account"] if grant else None, "items": queue.items(server)}


@router.put("/automatic")
def automatic_contributions(request: AutomaticContributionRequest) -> dict[str, Any]:
    from api.services.contribution_queue import queue_store
    with contribution_errors():
        queue = queue_store()
        server = connection.source()
        if request.enabled:
            status = connection.status()
            if status.get("state") != "connected" or status.get("subject") != request.account_id:
                raise HTTPException(409, "Connect the account that will submit your calibrations.")
            if not status.get("email_verified"):
                raise HTTPException(403, "Verify your email in the material library first.")
            if not request.consent:
                raise HTTPException(422, "Confirm public sharing before enabling automatic contributions.")
            queue.configure(server, request.account_id, True)
        elif queue.path.exists():
            queue.pause(server)
        return pending_contributions()


@router.get("/queue/{job_id}/prepare")
def prepare_queued_contribution(job_id: str) -> dict[str, Any]:
    from api.services.contribution_queue import queue_store
    with contribution_errors():
        _, prepared, origin = queue_store().snapshot(connection.source(), job_id)
        return {**prepared.summary(), "origin": origin}


class QueueAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["retry", "pause", "cancel"]
    account_id: str | None = None


@router.post("/queue/{job_id}")
def change_queued_contribution(job_id: str, request: QueueAction) -> dict[str, Any]:
    from api.services.contribution_queue import queue_store
    with contribution_errors():
        queue = queue_store()
        server = connection.source()
        if request.action == "retry":
            row, _, _ = queue.snapshot(server, job_id)
            status = connection.status()
            if (status.get("state") != "connected" or not status.get("email_verified")
                    or status.get("subject") != row["account"] or request.account_id != row["account"]):
                raise HTTPException(409, "Reconnect and verify the original contribution account.")
        queue.action(server, job_id, request.action)
        return pending_contributions()
