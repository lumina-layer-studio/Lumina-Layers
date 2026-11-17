# Creative Workshop Context

## Purpose

Creative Workshop is Lumina Studio's installable-module system. It lets an
independent, self-contained tool prepare an image and reproducible edit
envelope, then hand that image into Lumina's existing LUT/material, layered
color, preview, and 3MF workflow.

The first official module is `lumina.bead-pattern`, maintained in the separate
`Lumina-Fuse-Bead-Studio` repository. The standalone public
`Lumina-Workshop-SDK` repository owns the SDK source and immutable releases.
The host repository consumes an exact SDK release and owns package trust,
installation lifecycle, sandbox, storage, and converter handoff; it must not
import the official module's React source.

## Boundary map

```text
independent module repository
  -> immutable @lumina/workshop-sdk tarball
  -> one immutable .lumina-workshop Release asset + SHA-256
  -> signed GitHub Registry or official seed
  -> core/workshop package + release + install validation
  -> /api/workshop/v1 manager endpoints
  -> Workshop manager and sandboxed iframe
  -> MessageChannel RPC with declared permissions
  -> host-validated PNG + recipe envelope
  -> existing Lumina converter path
```

### Public SDK

- Public source: `https://github.com/lumina-layer-studio/Lumina-Workshop-SDK`.
- Exact host dependency: public Release `v1.0.1`.
- Recommended SDK for new modules: public Release `v1.0.2`. Both SDK
  releases use Workshop API `1.0.0` and manifest v1. The host dependency pin
  is not a requirement for the SDK version bundled into an installed module.
- The SDK owns manifest, permission, RPC, project, color-library, UI-state,
  handoff, and recipe contracts plus the bounded iframe client.
- SDK `1.1.0` (source on the SDK repository's topic branch, **not released**)
  adds manifest v2 backends, the `backend.tasks` handshake feature, and the
  stdlib-only Python backend SDK `lumina-workshop-backend`. The host keeps its
  exact SDK 1.0.1 pin and carries the backend RPC contract host-side until a
  tagged 1.1.0 Release exists.
- The public repository's protected `validate` and Release workflows are the
  only SDK publication authority.

The SDK has no dependency on React, Electron, Lumina source, or private host
objects.

The current host supports SDK 1.0.2's optional native SVG/thickness handoff
and live UI-state events. Modules targeting older hosts without these extensions
must omit `svgBytes` and `recommendedTotalThicknessMm`, send only base PNG
handoff fields, and use `ui.getState()` when UI events are unavailable. Including
PNG alongside unknown fields does not satisfy older hosts' closed schemas.
Modules may instead require a tested host range that supports the extensions;
declare actual host/API compatibility in the manifest.
The offline bead seed stays at `1.0.1`; the signed online catalog also offers
the reviewed `1.0.8` module. Startup does not force an online upgrade, and seed
restore keeps using the exact lock. Existing assets and digests are immutable.

### Python trust and lifecycle

- `core/workshop/models.py`: closed Pydantic models and exact SemVer/module
  identity.
- `core/workshop/package_validator.py`: fail-closed ZIP, manifest, HTML, text,
  and static-image inspection.
- `core/workshop/release_client.py`: bounded canonical GitHub Release access.
- `core/workshop/registry_client.py`: exact-byte Ed25519 verification, cache,
  snapshot fallback, compatibility, state, and revocation selection.
- `core/workshop/install_store.py`: atomic install-state document.
- `core/workshop/installer.py`: candidate install, activation, rollback,
  disable, uninstall, tombstone, and runtime-health transitions.
- `core/workshop/seed.py`: exact seed-lock verification and startup
  convergence without downgrade or post-uninstall resurrection.
- `assets/workshop-registry/keys.json`: application-owned public trust roots.
- `assets/workshop-registry/registry-v1.json`: bundled verified/offline
  catalog snapshot.
- `scripts/verify_workshop_release_chain.py`: one offline gate binding the
  public SDK checksum and pnpm integrity to the signed Registry, module
  Release bytes, reviewed manifest, and desktop seed lock.

The Python *host* never imports module code. Routes validate requests and
translate domain errors; installed bytes remain under `LUMINA_WORKSHOP_DATA_DIR`.

### Module backends (Workshop API 1.1.0, manifest v2)

A module may declare a backend: a Python entry under `backend/`, a wheels-only
PEP 751 `pylock.toml`, optional hash-pinned models, and optional acceleration
variants. The host runs it as a **local process with the user's permissions**
(not an OS sandbox); declared capabilities only explain intent.

- `core/workshop/backend/runtime.py`: per-data-directory coordinator
  (consent, transactional preparation, tasks, stop/disable/uninstall,
  reference-based reclamation, startup reconciliation, shutdown).
- `locks.py` (strict lock subset, canonical digest, wheelhouse/mirror
  rewriting), `tooling.py` (pinned uv with private cache/interpreter dirs,
  managed or explicit interpreter), `environments.py` (environment key =
  platform + Python minor + lock digest), `store.py` (SHA-256 content store;
  an object goes when no link, logical reference, or in-flight pin keeps it,
  and publish/link/collect decisions share one lock), `model_files.py` (models
  stay while an installed version or the user's retention references them,
  also where views are copies on drives without hard links), `review.py`
  (signed `reviews-v1.json`),
  `state.py` (`runtime/state.json`, separate from install-state v1),
  `tasks.py`, `supervisor.py`, `process.py`, `win_job.py`, `protocol.py`.
- `api/workshop_runtime_service.py` creates runtimes lazily per data dir and
  installers whose hooks bind package identity and keep versions needed by
  running tasks; `api/routers/workshop_backend.py` exposes backend status,
  consent, preparation, tasks, outputs, stop/presence, acceleration, and the
  storage overview behind `require_local_app_origin`.
- Prototype finding: uv's private cache gives hard-link sharing, but
  `uv cache prune` frees nothing referenced and `uv cache clean <name>` drops
  every version of a name, so later installs duplicate surviving versions. The
  host therefore keeps large files in `runtime/store/objects/<sha256>` and uses
  the uv cache only as a download cache cleaned during GC.
- GC runs while other modules prepare: a preparation leases its environments
  and pins its models until it commits under the GC lock, and destructive
  cleanup (staging, download cache, temporary downloads, interpreters) runs
  only when no preparation works.
- A deletion that fails because a file is in use is never replayed by path:
  names are reused (content hashes, environment keys, versions), so every
  pass derives garbage from current references again. Environment folders
  left without a valid record are swept by GC or cleared by the next build of
  that key; `runtime/state.json` `pending` only reports what is still waiting.
- Frontend: `contracts.ts` (host 1.1.0 extension of the pinned SDK),
  `runtime/capabilities.ts` (backend methods need a declared backend),
  `payloadValidation.ts`, `handlers.ts` (frame close never cancels host
  tasks), `WorkshopFrame.tsx` (handshake API ≤ host, `backend.tasks` feature,
  presence heartbeat), `workshop/backend/*` dialogs and storage view.

### API

`api/routers/workshop.py` exposes `/api/workshop/v1`:

- trusted catalog and installed-module listing;
- exact Registry, GitHub, and local package installation;
- candidate activation, rollback, enable/disable, uninstall, and seed restore;
- runtime health success/failure;
- safe README/license/gallery details;
- fixed-header runtime HTML and bounded static public assets.

Official modules installed from the signed Registry, and official seed modules,
may run in the restricted browser sandbox without the desktop token. Community
Registry, GitHub, and local runtime HTML still require the per-launch desktop
token. The token is passed only from Electron main process to the loopback
backend and never enters preload, renderer state, logs, bug reports, or response
headers.

### Frontend host

- `frontend/src/api/workshop.ts`: typed manager API.
- `frontend/src/workshop/WorkshopPanel.tsx`: Installed, Discover, and Developer
  views plus lifecycle confirmations.
- `frontend/src/workshop/runtime/WorkshopFrame.tsx`: sandbox iframe,
  handshake, candidate health, and teardown.
- `frontend/src/workshop/runtime/rpcHost.ts`: identity, permission, rate,
  timeout, in-flight duplicate-request, and payload enforcement. Completed
  request IDs are released; a frame has no lifetime request-count quota.
- `frontend/src/workshop/runtime/handlers.ts`: host-owned capability handlers.
- `frontend/src/workshop/projectStorage.ts`: module namespaces, 64 MiB record,
  256 MiB module quota, 1 MiB recipe quota, and snapshots.
- `frontend/src/workshop/converterHandoff.ts`: PNG, dimensions, physical size,
  color-library identity, replacement confirmation, and atomic converter
  handoff.
- `frontend/src/recipe/importRecipe.ts`: module-independent recipe-envelope
  validation; it never imports module implementation code.

Only manager view and active module identity persist in the Workshop shell
store. Pending recipes, diagnostics, projects, source images, credentials, and
signatures do not.

### Electron boundary

- `electron/workshop-security.cjs`: canonical custom URLs and fail-closed
  request/navigation/popup/permission/download decisions.
- `electron/main.cjs`: `lumina-workshop://` protocol proxy, per-launch token,
  frame request firewall, and renderer-process isolation check.
- `electron/preload.cjs`: exposes only the Workshop runtime-mode query.

Each module is loaded as:

```text
lumina-workshop://<module-id>/<exact-semver>/ui/index.html
```

The iframe uses `sandbox="allow-scripts"` without `allow-same-origin`.
Backend CSP denies all by default and permits only inline script/style and
explicit `data:`/`blob:` worker/image/font/media resources. If the committed
module frame shares the top renderer process, Electron clears it, records
`runtime-isolation-unavailable`, and keeps subsequent module loads in safe
mode.

## Invariants

1. A module ID is permanently bound to one product and reviewed repository.
   GitHub-confirmed URL redirects do not rewrite that binding. A changed
   Release asset URL is accepted only when repository metadata fetched through
   the registered address confirms its current canonical repository. Metadata
   redirects stay inside the HTTPS GitHub API; package hashes still apply.
2. Official and community packages use the same package inspection, install
   transaction, sandbox, RPC, quota, health, rollback, and uninstall paths.
3. A module receives only permissions declared in its exact manifest version.
4. No v1 module has general network, filesystem-path, clipboard, popup, or
   parent-DOM authority.
5. Registry signatures cover exact index bytes; Release asset SHA-256 covers
   exact package bytes. Failed remote verification never replaces trusted
   cache or snapshot state.
6. Updates are candidates until handshake succeeds. Permission expansion
   requires confirmation; repeated startup failures preserve rollback.
7. Uninstall keeps projects by default. An official-uninstalled tombstone
   prevents silent seed restoration after restart.
8. Recipe schema remains v3. A Workshop envelope is JSON, at most 1 MiB, and
   structurally validated without loading module code.
9. Missing, disabled, or incompatible modules never block restoration of the
   converter image and parameters.
10. Bug reports contain only module identity, install source, audit status,
    runtime mode, and a stable error code. They exclude project payloads,
    matrices, image bytes, paths, tokens, and signatures.
11. Image handoff is the only module-to-converter path and is revalidated by
    the host.
12. A backend version runs only after consent bound to its exact package
    SHA-256 and declaration digest; unreviewed code needs an explicit risk
    confirmation; a Registry block refuses the next start.
13. Installed, enabled, and running are separate. Tasks are host-owned: page
    switches and backend stops never cancel them; cancel, disable, uninstall,
    and exit end the module's process tree. Outputs stay readable afterwards.
14. Uninstall keeps projects and task data by default and reclaims programs by
    reference; retained user data never pins environments or interpreters.
15. One module's lifecycle never breaks another's: cleanup triggered by a
    preparation, uninstall, or setting change spares other modules' running
    preparations, and a variant start failure marks only its own module.

## Glossary

| Term | Meaning | Avoid |
| --- | --- | --- |
| module | Independently released installable Workshop tool | plugin when referring to the package contract |
| package | One `<id>-<version>.lumina-workshop` validated ZIP asset | arbitrary ZIP or source checkout |
| Registry | Signed reviewed catalog of repositories and exact Release assets | mutable download list |
| seed | Exact official package embedded for offline first install/recovery | special trusted runtime |
| candidate | Installed version not active until a successful sandbox start | partially active update |
| active version | Version currently opened by the host | newest downloaded version |
| previous version | Rollback target retained by installer | backup archive |
| recipe envelope | Bounded generic JSON allowing a module to restore editing | project database or source image |
| color library | Host-normalized LUT/material/native palette snapshot | raw LUT or material filesystem |
| handoff | Host-validated image and metadata transition into converter | direct store mutation |
| browser restricted mode | Mode that runs signed-Registry official modules, official seed, and fixtures only | secure community runtime |
| unsafe development mode | Explicit local-package mode using synthetic data | production browser sandbox |

## Focused verification

Run from the repository root:

```bash
PYTHONPATH=/private/tmp/lumina-workshop-python-deps \
  .venv/bin/python -m pytest \
  tests/test_workshop_package_unit.py \
  tests/test_workshop_registry_unit.py \
  tests/test_workshop_installer_unit.py \
  tests/test_workshop_api_unit.py \
  tests/test_workshop_seed_lifecycle_unit.py \
  tests/test_workshop_seed_startup_unit.py \
  tests/test_workshop_release_chain_unit.py \
  tests/test_workshop_backend_package_unit.py \
  tests/test_workshop_backend_review_unit.py \
  tests/test_workshop_backend_store_unit.py \
  tests/test_workshop_backend_supervisor_unit.py \
  tests/test_workshop_backend_runtime_integration.py \
  tests/test_workshop_backend_api_unit.py -v
# Optional cross-repository check against the public Python SDK source:
LUMINA_WORKSHOP_SDK_PYTHON_SRC=/path/to/Lumina-Workshop-SDK/python/src \
  .venv/bin/python -m pytest tests/test_workshop_backend_public_sdk_integration.py
.venv/bin/python scripts/run_vitest.py run \
  src/__tests__/workshop-rpc-host.test.ts \
  src/__tests__/workshop-runtime.test.tsx \
  src/__tests__/workshop-manager.test.tsx \
  src/__tests__/workshop-backend-rpc.test.ts \
  src/__tests__/workshop-backend-manager.test.tsx \
  src/__tests__/workshop-project-storage.test.ts \
  src/__tests__/workshop-handoff.test.ts \
  src/__tests__/recipe-import.test.ts \
  src/__tests__/recipe-export.test.ts
CI=true pnpm --dir electron test
CI=true pnpm --dir frontend build
```

Before a desktop release, download the exact SDK asset and checksum named by
`frontend/package.json`, plus the exact module asset named by
`assets/workshop-seed/seed-lock.json`, then run:

```bash
.venv/bin/python scripts/verify_workshop_release_chain.py \
  --sdk-archive /path/to/lumina-workshop-sdk-1.0.1.tgz \
  --sdk-checksum /path/to/lumina-workshop-sdk-1.0.1.tgz.sha256 \
  --seed-archive /path/to/lumina.bead-pattern-1.0.1.lumina-workshop
```

This gate performs no network access and fails if any Release byte, checksum,
pnpm integrity, Registry signature, reviewed manifest field, or seed identity
has drifted.

The repository may not have a local `.venv`; use the configured project Python
environment without changing test semantics. Non-watch frontend tests must run
through `scripts/run_vitest.py`.

Automated tests and HTTP success are not complete acceptance. Desktop QA must
also verify install, open, project save/reload, handoff, permission expansion
refusal, update, rollback, disable, uninstall with retained projects, offline
open, crash safe mode, and seed restore in Chinese/English and light/dark.

## Related documents

- `docs/workshop-module-development.md`
- `docs/superpowers/specs/2026-07-30-installable-creative-workshop-design.md`
- `docs/superpowers/plans/2026-07-30-installable-creative-workshop-host.md`
- `docs/superpowers/plans/2026-07-30-fuse-bead-studio-module.md`
- `docs/superpowers/plans/2026-07-30-workshop-registry-and-seed-release.md`
- `docs/bug-report-reproducibility.md`
