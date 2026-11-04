# Portable projects on Layers

The project system targets Layers `1308c06fc69915e11ead7dbefa0c1e7da11504d0`. A `.lum` file carries editable workflow documents and their actual input resources. Opening it prepares new resources and sessions before replacing the current workspace.

## Existing owners

Converter schema 2 uses `prepareRecipeExport`, `exportConverterRecipe`, `buildFullRecipe` and `restoreConverterRecipe`. Spatial changes, custom stacks, virtual materials, masks and selection use the existing editor project checkpoint. The project layer does not add another editing history. Legacy converter schema 1 operation logs are replayed once through current APIs into a fresh private session; subsequent saves use schema 2. Old packages missing source bytes or selection anchors fail with a specific explanation.

Other workflow adapters capture explicit fields from their existing Zustand stores. Extractor pages and gradient fit data are restored through their existing backend owners. Output URLs become content-addressed assets; restored download/previews get new local URLs. Vectorizer state remains available when moving between tabs, including after sending an SVG to Converter. An abandoned vectorization response cannot replace newer input.

Project resources are private: selected LUT files, native database/model dependencies, material archives, confirmed ColorChecker pixels and custom 3MF templates. They are staged under owned temporary directories and consumed by preview, generation, replacement and workflow queries. Neither opening nor saving installs resources into the user's library. Same-named global LUTs cannot replace a bound project resource. Library refresh keeps bound entries visible.

Only output-affecting settings travel: device, slicer, nozzle, plate, custom template, base-layer/wipe-tower choices, SVG sampling and material solver settings. Theme, layout, account details, paths and network preferences remain local. Request builders consume the project settings projection while global preferences retain their values.

## File and session lifecycle

`projectId` identifies the artwork, `revisionId` identifies a frozen save, and `fileEntryId` identifies a particular local file. Two copied files can share project identity without sharing a save destination. Save As creates a new artwork identity. Save completion only marks the captured change sequence clean; later edits remain dirty. Browser download fallback reports a download and retains dirty state because it cannot confirm filesystem persistence.

The bounded ZIP container validates paths, duplicate members, size budgets, content hashes, schema and embedded SVG. Unknown workflow versions remain inspectable with their cover and summary. A limited open restores supported documents and preserves unsupported documents/assets on later saves. An unavailable Workshop module is never installed or executed from project metadata.

The adapter registry validates and prepares all documents before committing. Failure rolls committed adapters back and releases prepared resources. In-flight editing/generation blocks replacement. Runtime epochs reject stale completions. Restored converter previews advance the existing preview counters so auto-preview does not overwrite checkpoint edits.

Electron owns native dialogs, opaque file capabilities, atomic write/rename and the recent catalog. Trusted main-frame IPC is required. Browser file handles and recent copies use IndexedDB. Recovery revisions also use IndexedDB in both environments, separately from authoritative saved files; the controller retains three automatic recovery revisions per artwork. Recovery errors are visible. Resource leases use `pagehide`, so cancelling a browser close does not tear down the current session.

## Launcher and Workshop

Launcher reads bounded manifest summaries and each installed runtime's `Resources/project-capabilities.v1.json`. It forwards `--open-project <path> --project-request-id <id>` without changing the default runtime. The body handles dirty save/discard/cancel and replies through correlated shared-root receipts. `app-ready` is not `project-opened`. See [launcher-protocol.md](launcher-protocol.md).

The optional Workshop protocol captures the live sandboxed editor over its established MessagePort. Protocol 1 offers capture, non-mutating prepare, commit acknowledgement, discard and changed notifications. Host identity/schema checks, deadlines and byte limits apply. Module commit is acknowledged after React adopts the state. Returning to Workshop home retains the last captured module workspace. Switching main application tabs keeps the mounted module alive.

Companion changes:

- [SDK #3](https://github.com/lumina-layer-studio/Lumina-Workshop-SDK/pull/3): optional protocol and module lifecycle.
- [Fuse Bead Studio #4](https://github.com/MOVIBALE/Lumina-Fuse-Bead-Studio/pull/4): live source/raster/calibration/editor/history capture; immutable SDK source dependency.
- [Registry #6](https://github.com/lumina-layer-studio/Lumina-Workshop-Registry/pull/6): optional manifest capability validation.
- [Launcher #17](https://github.com/lumina-layer-studio/Lumina-Launcher/pull/17): installed-version choice, OS-open delivery and correlated completion.
- [Distribution #23](https://github.com/lumina-layer-studio/Lumina-Distribution/pull/23): packaged marker verification and standalone file association.

## Output attachment

The export bundle contains a `.lum` file and PNG cover from one captured revision. The separate “3MF includes project” choice defaults off. Enabling it freezes one revision before generation and attaches its exact bytes at `Metadata/Lumina/project.lum`, including every 3MF in a tile ZIP. Standard, large-format, puzzle and batch paths share this boundary. Final downloads keep the existing TTL and survive editor-session closure.

OPC content-type and relationship elements preserve their original namespace prefix. Rewriting these to generated prefixes prevented real slicers from reading the model despite equivalent XML. Puzzle assembly also preserves unused placeholder slots without assigning the same source material to two output slots.
