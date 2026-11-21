"""Community connections using the existing Registry identity and owner workflows."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from core.resource_contribution import MAX_FILE_BYTES, PreparedContribution, contribution_package, prepare_owned_revision
from api.services.community_vault import CommunityVault, CommunityVaultError


class ContributionError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def configured_contribution_server() -> str:
    # The public-read mirror has no account API. Account requests use this
    # server only, without read tokens or fallback mirrors.
    value = os.environ.get("LUMINA_CONTRIBUTION_REGISTRY_URL",
                           "https://dan5.shmx.top/api/material-registry/v1").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.path.endswith("/api/material-registry/v1")
            or (parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"})):
        raise ContributionError(503, "The contribution server URL is invalid.")
    return value


class ContributionConnection:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._source = ""
        self.subject = ""
        self._token = ""
        self._code = ""
        self.vault = CommunityVault()
        self._access_expires_at = 0.0
        self._device: dict[str, Any] | None = None
        self._device_saved = False
        self._ignore_saved = False
        self._vault_healthy = True
        self._device_supported = True

    def source(self) -> str:
        value = configured_contribution_server()
        if not value:
            self._source, self._token, self._code = "", "", ""
            self.subject = ""
            self._device = None
            return ""
        if value != self._source:
            self.subject = ""
            self._token, self._code = "", ""
            self._device = None
            self._access_expires_at = 0
            self._device_saved = False
            self._ignore_saved = False
            self._vault_healthy = True
            self._device_supported = True
            self._source = value
        return value

    def _forget_device(self) -> None:
        self.subject = ""
        self._token, self._code = "", ""
        self._device = None
        self._access_expires_at = 0
        self._device_saved = False
        self._ignore_saved = True
        if self._source and self.vault.available:
            try:
                self.vault.delete(self._source)
            except CommunityVaultError:
                self._vault_healthy = False

    def _save_device(self) -> None:
        if not self._device or not self.vault.available:
            return
        try:
            self.vault.save(self._source, self._device)
            self._device_saved = True
            self._ignore_saved = False
            self._vault_healthy = True
        except CommunityVaultError:
            self._device_saved = False
            self._vault_healthy = False

    def _accept_device(self, credentials: dict[str, Any], subject: str) -> None:
        if (not isinstance(credentials, dict)
                or not isinstance(credentials.get("access_token"), str)
                or not credentials["access_token"].startswith("studio_device_")
                or not isinstance(credentials.get("refresh_token"), str)
                or not credentials["refresh_token"].startswith("studio_refresh_")
                or not isinstance(credentials.get("device_id"), str)
                or not isinstance(credentials.get("access_expires_at"), (int, float))):
            raise ContributionError(502, "The material server returned invalid device credentials.")
        self._token = credentials["access_token"]
        self._access_expires_at = credentials["access_expires_at"]
        self._device = {"refresh_token": credentials["refresh_token"],
                        "device_id": credentials["device_id"], "subject": subject}
        self._device_saved = False
        self._save_device()
        self._code = ""

    def _restore_device(self) -> None:
        saved = self._device
        if saved is None and self.vault.available and not self._ignore_saved:
            try:
                saved = self.vault.load(self._source)
                self._vault_healthy = True
            except CommunityVaultError:
                self._vault_healthy = False
                return
        if not isinstance(saved, dict) or not isinstance(saved.get("refresh_token"), str):
            return
        try:
            credentials = self._request("POST", "/auth/studio/refresh",
                                        json={"refresh_token": saved["refresh_token"]})
            self._accept_device(credentials, saved.get("subject", ""))
        except ContributionError as exc:
            if exc.status == 401:
                self._forget_device()
            else:
                raise

    def _request(self, method: str, path: str, *, archive: bool = False, preserve_resource_errors: bool = False, **kwargs: Any) -> Any:
        source = self.source()
        if not source:
            raise ContributionError(503, "The contribution server has not been configured.")
        headers = {"Authorization": f"Bearer {self._token}", "X-CSRF-Token": self._token} if self._token else {}
        try:
            timeout = 12 if "/activity" in path or path == "/auth/studio/status" else 45
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=8), follow_redirects=False) as client:
                if archive:
                    with client.stream(method, source + path, headers=headers, **kwargs) as response:
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_FILE_BYTES:
                                raise ContributionError(413, "The revision archive exceeds the contribution limit.")
                            chunks.append(chunk)
                        response = httpx.Response(response.status_code, content=b"".join(chunks), headers=response.headers)
                else:
                    response = client.request(method, source + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ContributionError(502, "The material server could not be reached. Please retry.") from exc
        if response.status_code == 401 or response.status_code == 403 and not preserve_resource_errors:
            self._token, self._code = "", ""
            raise ContributionError(401, "Reconnect your material account and try again.")
        if response.status_code >= 300:
            if response.status_code == 404 and not preserve_resource_errors:
                raise ContributionError(503, "This material server needs the Studio community update.")
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            raise ContributionError(response.status_code if response.status_code < 500 else 502,
                                    detail[:500] if isinstance(detail, str) else "The material server could not complete the request.")
        if archive:
            return response.content
        try:
            return response.json()
        except ValueError as exc:
            raise ContributionError(502, "The contribution server returned an invalid response.") from exc

    def status(self) -> dict[str, Any]:
        with self.lock:
            source = self.source()
            if source and (not self._token or (
                    self._device and self._access_expires_at < time.time() + 60)):
                self._restore_device()
            result: dict[str, Any] = {"state": "disconnected" if source else "unavailable",
                                      "server": source, "web_url": source.removesuffix("/api/material-registry/v1"),
                                      "persistent": False, "can_remember": self.vault.available and self._vault_healthy}
            if source and self._token:
                result.update(self._request("GET", "/auth/studio/status"))
                if result["state"] == "disconnected":
                    self._forget_device()
                if result["state"] == "pending":
                    result.update({"code": self._code,
                                   "connect_url": result["web_url"] + "/#/studio-connect?code=" + self._code})
                if result["state"] == "connected":
                    self.subject = result["subject"]
                    if self._device is None and self.vault.available and self._device_supported:
                        try:
                            credentials = self._request("POST", "/auth/studio/device", json={"name": "Lumina Studio"})
                        except ContributionError as exc:
                            if exc.status != 503:
                                raise
                            self._device_supported = False
                        else:
                            self._accept_device(credentials, result["subject"])
                    elif self._device and not self._device_saved:
                        self._save_device()
                    result["persistent"] = self._device_saved
                    result["can_remember"] = self.vault.available and self._vault_healthy and self._device_supported
            return result

    def start(self) -> dict[str, Any]:
        with self.lock:
            current = self.status()
            if current["state"] in {"connected", "pending"}:
                return current
            result = self._request("POST", "/auth/studio/start")
            self._token, self._code = result["token"], result["code"]
            return self.status()

    def disconnect(self) -> dict[str, Any]:
        with self.lock:
            self.source()
            incomplete = False
            try:
                if not self._token:
                    self._restore_device()
                if self._token:
                    self._request("POST", "/auth/studio/disconnect")
            except ContributionError:
                incomplete = True
            finally:
                self._forget_device()
            return {**self.status(), "disconnect_incomplete": incomplete or not self._vault_healthy}

    def history(self) -> list[dict[str, Any]]:
        with self.lock:
            if self.status()["state"] != "connected":
                raise ContributionError(401, "Connect your existing material account first.")
            materials = self._request("GET", "/me/material-submissions")
            luts = self._request("GET", "/me/lut-submissions")["items"]
            return [{**row, "kind": kind} for kind, rows in (("materials", materials), ("luts", luts)) for row in rows]

    def owned_revision(self, kind: str, resource_id: str, revision_id: str,
                       expected_subject: str | None = None) -> dict[str, Any]:
        status = self.status()
        if status["state"] != "connected" or expected_subject and status.get("subject") != expected_subject:
            raise ContributionError(409, "Reconnect the original contribution account and reopen the form.")
        field = "material_id" if kind == "materials" else "lut_id"
        row = next((row for row in self.history() if row["kind"] == kind and row.get(field) == resource_id and row.get("revision_id") == revision_id), None)
        if row is None:
            raise ContributionError(404, "This revision does not belong to the connected account.")
        return row

    def owns_original_source(self, kind: str, resource_id: str, revision_id: str,
                             content_hash: str, account_id: str) -> bool:
        with self.lock:
            try:
                row = self.owned_revision(kind, resource_id, revision_id, account_id)
                attribution = (row.get("display") or {}).get("attribution")
                if attribution and (not isinstance(attribution, dict) or attribution.get("relationship") != "original"):
                    return False
                # The public lookup verifies the revision's hash on the same
                # Registry. Ownership comes from the owner's record above.
                self.resource_feedback(kind, {
                    "resource_id": resource_id, "revision_id": revision_id, "content_hash": content_hash,
                }, "contributor")
            except ContributionError as exc:
                if exc.status in {401, 403, 404, 409}:
                    return False
                raise
        return True

    @staticmethod
    def _revision_path(kind: str, row: dict[str, Any]) -> str:
        if kind == "materials":
            return "/me/material-submissions/" + quote(row["submission_id"], safe="")
        return "/me/lut-submissions/" + quote(row["lut_id"], safe="") + "/" + quote(row["revision_id"], safe="")

    def prepare_revision(self, kind: str, resource_id: str, revision_id: str,
                         expected_subject: str | None = None) -> PreparedContribution:
        with self.lock:
            row = self.owned_revision(kind, resource_id, revision_id, expected_subject)
            payload = self._request("GET", self._revision_path(kind, row) + "/archive", archive=True)
            return prepare_owned_revision(kind, resource_id, revision_id, payload, row.get("display") or {})

    def review_action(self, kind: str, resource_id: str, revision_id: str, action: str, expected_subject: str) -> dict[str, Any]:
        with self.lock:
            row = self.owned_revision(kind, resource_id, revision_id, expected_subject)
            result = self._request("POST", self._revision_path(kind, row) + "/" + action)
            return {**result, "kind": kind}

    def activity(self, kind: str, ids: list[str]) -> dict[str, Any]:
        from core.public_resources import is_static_catalog, material_registry_url, lut_registry_url

        source = material_registry_url() if kind == "materials" else lut_registry_url()
        # Counts are public; only capture the local identity under the account lock.
        # Personal flags are loaded separately through /mine.
        with self.lock:
            account_server = self.source()
            subject = self.subject if self._token and self.subject else None
        static = is_static_catalog(source)
        if not static and not account_server:
            raise ContributionError(503, "The contribution server has not been configured.")
        try:
            with httpx.Client(timeout=httpx.Timeout(20 if static else 12, connect=8), follow_redirects=False) as client:
                if static:
                    from core.public_catalog import snapshot_activity
                    from core.single_stage.material_files import MATERIALS_DIR
                    from utils.lut_manager import LUTManager
                    from pathlib import Path

                    directory = Path(MATERIALS_DIR) / "_sync/catalogs" if kind == "materials" else LUTManager.cloud_lut_sync_dir() / "catalogs"
                    result = snapshot_activity(client=client, base=source, kind=kind, ids=ids, cache_dir=directory)
                else:
                    response = client.get(account_server + f"/resources/{kind}/activity",
                                          params=[("resource_id", value) for value in ids])
                    response.raise_for_status()
                    result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ContributionError(502, "The public activity snapshot could not be loaded.") from exc
        result["subject"] = subject
        return result

    def my_activity(self, kind: str) -> dict[str, Any]:
        with self.lock:
            status = self.status()
            if status["state"] != "connected":
                raise ContributionError(401, "Connect your community account.")
            rows: list[dict[str, Any]] = []
            while True:
                page = self._request("GET", f"/me/resources/{kind}/activity",
                                     params={"offset": len(rows), "limit": 500})
                rows.extend(page["items"])
                if not page["has_more"]:
                    return {"items": rows, "subject": page["subject"]}
                if not page["items"]:
                    raise ContributionError(502, "Account activity could not be loaded.")

    def update_activity(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            status = self.status()
            if status["state"] != "connected":
                raise ContributionError(401, "Connect your community account.")
            if status["subject"] != payload["account_id"]:
                raise ContributionError(409, "The connected account changed. Try again.")
            return self._request("PUT", f"/me/resources/{kind}/activity", json=payload)

    def resource_feedback(self, kind: str, payload: dict[str, Any], action: str) -> dict[str, Any]:
        with self.lock:
            if action == "contributor":
                result = self._request("GET", f"/resources/{kind}/contributor", params=payload, preserve_resource_errors=True)
                profile = result.get("contributor")
                # Older Registry versions may still include retired contact fields.
                return {"contributor": None if profile is None else {
                    "id": profile["id"], "display_name": profile["display_name"],
                }}
            status = self.status()
            if status["state"] != "connected":
                raise ContributionError(401, "Connect your community account.")
            if action == "mine":
                return self._request("GET", f"/me/resources/{kind}/reports", params=payload, preserve_resource_errors=True)
            if payload["account_id"] != status["subject"]:
                raise ContributionError(409, "The connected account changed. Reopen the report.")
            # Email verification may be required; that permission error does not
            # invalidate an otherwise healthy community connection.
            return self._request("POST", f"/me/resources/{kind}/reports", json=payload, preserve_resource_errors=True)

    def feedback_history(self, offset: int) -> dict[str, Any]:
        with self.lock:
            if self.status()["state"] != "connected":
                raise ContributionError(401, "Connect your community account.")
            return self._request("GET", "/me/resource-reports", params={"offset": offset, "limit": 50})

    def feedback_image(self, report_id: str, image_id: str, expected_subject: str) -> dict[str, Any]:
        with self.lock:
            status = self.status()
            if status["state"] != "connected":
                raise ContributionError(401, "Connect your community account.")
            if status["subject"] != expected_subject:
                raise ContributionError(409, "The connected account changed. Reopen the report.")
            result = self._request("GET", f"/me/resource-reports/{quote(report_id, safe='')}/images/{quote(image_id, safe='')}",
                                   preserve_resource_errors=True)
            if result.get("subject") != expected_subject:
                raise ContributionError(409, "The connected account changed. Reopen the report.")
            return result

    def record_download(self, kind: str, entry: dict[str, Any], account_id: str | None) -> bool | None:
        """Record only after a verified install; never fail a completed download."""
        if not account_id:
            return None
        try:
            self.update_activity(kind, {
                "resource_id": entry["material_id" if kind == "materials" else "lut_id"],
                "revision_id": entry["revision_id"], "content_hash": entry["content_hash"],
                "action": "downloaded", "enabled": True, "account_id": account_id,
            })
            return True
        except ContributionError:
            return False

    def submit(self, prepared: PreparedContribution, display: dict[str, Any],
               expected_subject: str | None = None,
               print_images: list[Any] | None = None) -> dict[str, Any]:
        # Serialize submissions and account switching. A retry checks server receipts
        # first, including after a connection loss between upload and acknowledgement.
        with self.lock:
            status = self.status()
            if status["state"] != "connected":
                raise ContributionError(401, "Connect your existing material account first.")
            if expected_subject is not None and status["subject"] != expected_subject:
                raise ContributionError(409, "The connected account changed. Reopen the form and confirm attribution.")
            payload, resource_id, revision_id = contribution_package(prepared, display, status["subject"])
            field = "material_id" if prepared.kind == "materials" else "lut_id"
            existing = next((row for row in self.history() if row["kind"] == prepared.kind
                             and row.get(field) == resource_id and row.get("revision_id") == revision_id), None)
            submit_json_kw = {"json": {"print_images": print_images}} if print_images else {}
            if existing:
                if existing.get("status") in {"draft", "withdrawn"}:
                    extra = submit_json_kw if prepared.kind == "materials" else {}
                    return {**self._request("POST", self._revision_path(prepared.kind, existing) + "/submit", **extra), "kind": prepared.kind}
                if existing.get("status") in {"needs_changes", "rejected", "unpublished"}:
                    raise ContributionError(409, "Revise the submission before sending it for review again.")
                return existing
            if prepared.kind == "materials":
                receipt = existing or self._request("POST", "/me/material-submissions",
                    files={"archive": ("material.zip", payload, "application/zip")},
                    data={"visibility": "private", "calibration_method": "gradient_card",
                          "publish_calibrator_name": "true"})
                return {**self._request("POST", f"/me/material-submissions/{receipt['submission_id']}/submit", **submit_json_kw),
                        "kind": "materials"}
            lut_data_kw = {"data": {"print_images": json.dumps(print_images)}} if print_images else {}
            return {**self._request("POST", "/me/lut-submissions",
                                   files={"archive": ("lut.zip", payload, "application/zip")},
                                   **lut_data_kw),
                    "kind": "luts"}


connection = ContributionConnection()
