# Portable projects on Layers — implementation and acceptance

**Goal:** Finish the editable `.lum` workflow on Layers main, using the existing recipe and editor checkpoint owners.

**Baseline:** `1308c06fc69915e11ead7dbefa0c1e7da11504d0`. Prior work: Studio #606/#688, `fae867ea2`.

**Execution:** Single agent, as requested. No merge or release is part of this change.

## Ownership

- Reuse the bounded v1 `.lum` archive, content hashes, identity and revision format.
- Converter documents use current `exportConverterRecipe` / `restoreConverterRecipe` and `prepareRecipeExport` / `pendingEditorProject`. The backend checkpoint remains the sole owner of spatial edits and selection masks.
- Project-local LUT/material resources and effective device settings do not install into or overwrite the user's global library/preferences.
- Other workflows keep their existing stores and API actions; adapters persist inputs and editable state, never runtime sessions or temporary URLs.
- Desktop owns file paths, atomic writes, a path-indexed catalog and recovery files. Browser owns its IndexedDB catalog/recovery. Multiple copies of one project are distinct file entries.
- Workshop current-state capture uses a versioned request/response handshake with the actual sandboxed module. Launcher reads bounded summaries and forwards structured file-open requests.

## Work and acceptance

- [x] Port container/session foundations and run their existing contract tests on the new baseline.
- [x] Add converter capture/restore using the current recipe/checkpoint chain. Preserve model surface stages, crop/rotation input, batch order, geometry and all current output parameters.
- [x] Add project-local LUT/material snapshot upload and lifecycle through preview, generation and replacement. Restore into an empty/different library without changing global files.
- [x] Add project-bound output settings consumed by preview/generate. Saving while edits are pending waits for the existing revision barrier; stale async completion cannot mark newer edits saved.
- [x] Add adapters for calibration, extractor, gradient generation/extraction, five-color, LUT authoring and vectorizer. Recreate backend sessions using each workflow's real owner before applying editable results.
- [x] Integrate project center, new/open/save/save-as/export, keyboard and menu commands, unsaved transitions, recent files, search, pin/remove/locate, and recoverable revisions. Use current shared controls and theme tokens.
- [x] Integrate desktop startup/open queues and file capability manifest. Wire actual Launcher and Workshop module support using independently reviewable repository changes where required.
- [x] Export `.lum` plus PNG from one frozen revision; explicitly opt in to embedding that revision in standard, puzzle, large-format and batch 3MF/ZIP outputs. Preserve final download TTL.
- [x] Verify save → fresh environment → restore → edit → save, with real LUT/material bytes, raster/SVG, model surface, each workflow adapter and Workshop unsaved state.
- [x] Verify application UI, packaged/open integration where available, and actual slicer import after 3MF embedding; record observed coverage per workflow.
- [x] Review final changes and run relevant regression/build/lint checks.
- [ ] Stop task-owned processes, push the topic branch and create the Layers PR with AI disclosure and exact validation results.

## Compatibility

Existing JSON and PNG imports remain supported. Legacy `.lum` documents that contain operation logs are migrated through the current owners; missing historical assets are reported rather than invented. Unknown workflow/module versions can be inspected without executing code or clearing the active editor.

## Progress

2026-11-04: New branch based on current Layers main; old Studio branch preserved. Restored archive, identity, session and recovery primitives with their format/lifecycle regression tests.

2026-11-04 acceptance: all implementation items above are complete. Real application runs cover private LUT + spatial edits, SVG, model surface, vectorization and live Workshop edit/restore/undo; actual Bambu imports cover standard, large-format, puzzle and batch outputs. The full evidence and unexecuted installed-package release checks are recorded in [the acceptance report](../../projects/acceptance-report.md). Five companion draft PRs are linked from [the architecture](../../projects/architecture.md).
