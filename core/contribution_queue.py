"""Durable calibration snapshots, shared budgets and workspace-bound consent."""

from __future__ import annotations

from contextlib import closing, contextmanager
import io
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator
import uuid
import zipfile

from core.resource_contribution import PreparedContribution, json_bytes, sha, with_contribution_license

CONSENT_VERSION = "lumina-data-v1"
MAX_PENDING = 100
MAX_BYTES = 512 * 1024 * 1024


class ContributionQueue:
    def __init__(self, path: Path, workspace: str) -> None:
        self.path, self.workspace = path, workspace

    @contextmanager
    def transaction(self, *, write: bool = True) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            # A future schema must never be rewritten by an older runtime.
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("This contribution queue needs a newer Lumina version.")
            if version == 0:
                db.execute("BEGIN IMMEDIATE")
                # Another instance may have initialized the queue while we waited.
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise ValueError("This contribution queue needs a newer Lumina version.")
                if version == 0:
                    db.execute("""CREATE TABLE IF NOT EXISTS contribution_grants (
                        workspace TEXT NOT NULL, server TEXT NOT NULL, account TEXT NOT NULL,
                        enabled INTEGER NOT NULL, consent_version TEXT NOT NULL, confirmed_at REAL NOT NULL,
                        PRIMARY KEY(workspace, server))""")
                    db.execute("""CREATE TABLE IF NOT EXISTS contribution_jobs (
                        id TEXT PRIMARY KEY, workspace TEXT NOT NULL, server TEXT NOT NULL, account TEXT NOT NULL,
                        kind TEXT NOT NULL, resource_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                        name TEXT NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
                        reviewed INTEGER NOT NULL, original INTEGER NOT NULL,
                        snapshot BLOB, digest TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                        next_attempt REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL, receipt TEXT,
                        UNIQUE(workspace, server, account, kind, resource_key, fingerprint))""")
                    db.execute("PRAGMA user_version=1")
                db.commit()
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db

    def configure(self, server: str, account: str, enabled: bool) -> None:
        with self.transaction() as db:
            # Re-enabling never resumes older jobs implicitly.
            previous = db.execute("SELECT consent_version FROM contribution_grants WHERE workspace=? AND server=?",
                                  (self.workspace, server)).fetchone()
            changed_terms = bool(previous and previous["consent_version"] != CONSENT_VERSION)
            db.execute("""UPDATE contribution_jobs SET state='paused'
                WHERE workspace=? AND server=? AND state='queued' AND (account<>? OR ?=0 OR ?=1)""",
                (self.workspace, server, account, int(enabled), int(changed_terms)))
            db.execute("""INSERT INTO contribution_grants VALUES(?,?,?,?,?,?)
                ON CONFLICT(workspace,server) DO UPDATE SET account=excluded.account,
                enabled=excluded.enabled, consent_version=excluded.consent_version,
                confirmed_at=excluded.confirmed_at""",
                (self.workspace, server, account, int(enabled), CONSENT_VERSION, time.time()))

    def pause(self, server: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE contribution_grants SET enabled=0 WHERE workspace=? AND server=?",
                       (self.workspace, server))
            db.execute("""UPDATE contribution_jobs SET state='paused'
                WHERE workspace=? AND server=? AND state='queued'""", (self.workspace, server))

    def grant(self, server: str) -> dict[str, Any] | None:
        with self.transaction(write=False) as db:
            row = db.execute("SELECT * FROM contribution_grants WHERE workspace=? AND server=?",
                             (self.workspace, server)).fetchone()
            if not row:
                return None
            grant = dict(row)
            grant["enabled"] = int(bool(grant["enabled"] and grant["consent_version"] == CONSENT_VERSION))
            return grant

    def owns_snapshot(self, server: str, account: str, prepared: PreparedContribution) -> bool:
        with self.transaction(write=False) as db:
            return db.execute("""SELECT 1 FROM contribution_jobs WHERE workspace=? AND server=? AND account=?
                AND kind=? AND resource_key=? AND fingerprint=? AND original=1 LIMIT 1""",
                (self.workspace, server, account, prepared.kind, prepared.key, prepared.fingerprint)).fetchone() is not None

    @staticmethod
    def encode(prepared: PreparedContribution, display: dict[str, Any], origin: Any) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("snapshot.json", json_bytes({
                "kind": prepared.kind, "key": prepared.key, "fingerprint": prepared.fingerprint,
                "display": with_contribution_license(prepared, display),
                "compatibility": prepared.compatibility, "origin": origin,
                "consent_version": CONSENT_VERSION,
            }))
            for name, payload in prepared.files.items():
                archive.writestr("files/" + name, payload)
        return output.getvalue()

    @staticmethod
    def decode(payload: bytes, digest: str) -> tuple[PreparedContribution, Any]:
        if sha(payload) != digest:
            raise ValueError("The saved contribution snapshot is damaged.")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            meta = json.loads(archive.read("snapshot.json"))
            # Earlier snapshots were confirmed under CC BY 4.0, even when the
            # license was only added later by the upload packager.
            if not meta["display"].get("license") and meta.get("consent_version") == "public-calibration-v1":
                meta["display"]["license"] = "CC-BY-4.0"
            prepared = PreparedContribution(meta["kind"], meta["key"], meta["fingerprint"],
                meta["display"], meta["compatibility"],
                {name[6:]: archive.read(name) for name in archive.namelist() if name.startswith("files/")})
        return prepared, meta["origin"]

    def add(self, server: str, account: str, prepared: PreparedContribution,
            display: dict[str, Any], origin: Any, *, ready: bool, reason: str = "") -> str | None:
        payload = self.encode(prepared, display, origin)
        with self.transaction() as db:
            grant = db.execute("""SELECT * FROM contribution_grants
                WHERE workspace=? AND server=? AND account=? AND enabled=1""",
                (self.workspace, server, account)).fetchone()
            if not grant or grant["consent_version"] != CONSENT_VERSION:
                return None
            existing = db.execute("""SELECT id FROM contribution_jobs WHERE workspace=?
                AND server=? AND account=? AND kind=? AND resource_key=? AND fingerprint=?""",
                (self.workspace, server, account, prepared.kind, prepared.key, prepared.fingerprint)).fetchone()
            if existing:
                return existing["id"]
            # Every workspace using this shared data root shares one budget.
            usage = db.execute("""SELECT COUNT(*),COALESCE(SUM(LENGTH(snapshot)),0)
                FROM contribution_jobs WHERE snapshot IS NOT NULL""").fetchone()
            if usage[0] >= MAX_PENDING or usage[1] + len(payload) > MAX_BYTES:
                raise ValueError("The contribution queue is full. Manage pending items in My submissions.")
            job_id = uuid.uuid4().hex
            db.execute("""INSERT INTO contribution_jobs
                (id,workspace,server,account,kind,resource_key,fingerprint,name,state,reason,reviewed,original,snapshot,digest,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, self.workspace, server, account, prepared.kind, prepared.key, prepared.fingerprint,
                 str(display.get("material_name") or display.get("name") or prepared.key),
                 "queued" if ready else "needs_review", reason, int(ready),
                 int(display.get("attribution", {}).get("relationship") == "original"),
                 payload, sha(payload), time.time()))
            return job_id

    def items(self, server: str) -> list[dict[str, Any]]:
        with self.transaction(write=False) as db:
            return [dict(row) for row in db.execute("""SELECT id,account,kind,resource_key,name,state,
                reason,reviewed,original,attempts,next_attempt,created_at,receipt FROM contribution_jobs
                WHERE workspace=? AND server=?
                ORDER BY state IN ('received','cancelled'),created_at DESC LIMIT 200""",
                (self.workspace, server))]

    def snapshot(self, server: str, job_id: str) -> tuple[dict[str, Any], PreparedContribution, Any]:
        with self.transaction(write=False) as db:
            row = db.execute("""SELECT * FROM contribution_jobs WHERE workspace=? AND server=? AND id=?""",
                             (self.workspace, server, job_id)).fetchone()
            if not row or row["snapshot"] is None:
                raise ValueError("The pending contribution no longer exists.")
            prepared, origin = self.decode(row["snapshot"], row["digest"])
            return dict(row), prepared, origin

    def review(self, server: str, job_id: str, account: str, display: dict[str, Any]) -> None:
        row, prepared, origin = self.snapshot(server, job_id)
        if row["account"] != account:
            raise ValueError("Reconnect the account that created this contribution.")
        payload = self.encode(prepared, display, origin)
        with self.transaction() as db:
            usage = db.execute("SELECT COALESCE(SUM(LENGTH(snapshot)),0) FROM contribution_jobs WHERE id<>?",
                               (job_id,)).fetchone()[0]
            if usage + len(payload) > MAX_BYTES:
                raise ValueError("The contribution queue is full.")
            changed = db.execute("""UPDATE contribution_jobs SET snapshot=?,digest=?,state='queued',
                reason='',reviewed=1,original=?,next_attempt=0 WHERE id=? AND state NOT IN ('sending','received','cancelled')""",
                (payload, sha(payload), int(display.get("attribution", {}).get("relationship") == "original"), job_id)).rowcount
            if not changed:
                raise ValueError("This contribution is already being processed. Refresh its status.")

    def action(self, server: str, job_id: str, action: str) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM contribution_jobs WHERE workspace=? AND server=? AND id=?",
                             (self.workspace, server, job_id)).fetchone()
            if not row or row["state"] in {"sending", "received", "cancelled"}:
                raise ValueError("This contribution cannot be changed. Refresh its status.")
            if action == "retry" and not row["reviewed"]:
                raise ValueError("Complete the contribution details first.")
            state = {"retry": "queued", "pause": "paused", "cancel": "cancelled"}[action]
            db.execute("""UPDATE contribution_jobs SET state=?,next_attempt=0,
                snapshot=CASE WHEN ?='cancelled' THEN NULL ELSE snapshot END WHERE id=?""",
                (state, state, job_id))

    def claim(self, server: str, account: str) -> str | None:
        """Caller holds the shared OS worker lock through remote receipt storage."""
        with self.transaction() as db:
            # Acquiring that lock proves no previous worker is still sending.
            grant = db.execute("SELECT * FROM contribution_grants WHERE workspace=? AND server=?",
                               (self.workspace, server)).fetchone()
            resumed = bool(grant and grant["enabled"] and grant["account"] == account
                           and grant["consent_version"] == CONSENT_VERSION)
            db.execute("""UPDATE contribution_jobs SET state=? WHERE workspace=?
                AND server=? AND account=? AND state='sending'""",
                ("queued" if resumed else "paused", self.workspace, server, account))
            if not resumed:
                db.execute("""UPDATE contribution_jobs SET state='paused' WHERE workspace=?
                    AND server=? AND account=? AND state='queued'""", (self.workspace, server, account))
                return None
            row = db.execute("""SELECT id FROM contribution_jobs WHERE workspace=? AND server=?
                AND account=? AND reviewed=1 AND state='queued' AND next_attempt<=? ORDER BY created_at LIMIT 1""",
                (self.workspace, server, account, time.time())).fetchone()
            if not row:
                return None
            db.execute("UPDATE contribution_jobs SET state='sending',attempts=attempts+1 WHERE id=?", (row["id"],))
            return row["id"]

    def finish(self, job_id: str, *, receipt: dict[str, Any] | None = None,
               reason: str = "", retryable: bool = False) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM contribution_jobs WHERE id=? AND workspace=?",
                             (job_id, self.workspace)).fetchone()
            if not row:
                return
            grant = db.execute("SELECT * FROM contribution_grants WHERE workspace=? AND server=?",
                               (self.workspace, row["server"])).fetchone()
            enabled = (grant and grant["enabled"] and grant["account"] == row["account"]
                       and grant["consent_version"] == CONSENT_VERSION)
            state = "received" if receipt else ("queued" if enabled else "paused") if retryable else "needs_review"
            db.execute("""UPDATE contribution_jobs SET state=?,reason=?,next_attempt=?,receipt=?,
                snapshot=CASE WHEN ? IS NOT NULL THEN NULL ELSE snapshot END WHERE id=?""",
                (state, reason[:500], time.time() + min(3600, 30 * 2 ** min(row["attempts"], 7)),
                 json.dumps(receipt) if receipt else None, json.dumps(receipt) if receipt else None, job_id))
