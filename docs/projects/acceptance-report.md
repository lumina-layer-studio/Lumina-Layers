# Layers portable-project acceptance — 2026-11-04

The implementation reuses the current recipe/editor checkpoint owners and supplies project adapters for all active creation workflows. Five companion draft PRs supply the real SDK/module, registry, Launcher and packaging integration; links are in [architecture.md](architecture.md). Nothing was merged or released.

## Executed checks

- Frontend full suite: **351 files, 3,907 tests passed**. After the final private-LUT draft guard and settings validation, the affected suites passed separately (82 and 10 tests respectively). TypeScript/Vite production build passed. ESLint: **0 errors, 68 existing warnings**.
- Backend generation, puzzle, file TTL, material API, Workshop and editor regression group: **414 passed**. Container/property/resource/workflow/editor/error/logging group: **80 passed**. Focused export/template/revision tests: **7 passed**. Earlier SVG worker regressions also passed. These groups overlap and are not summed.
- Electron project broker, file operations, menu and application quit: **24 passed**. Includes actual correlated receipt files, two copies with the same project ID, atomic-write interruption, frame trust and dirty-close acknowledgement.
- Logging quality `--mode fast` passed. Builds retain the existing large-bundle warning; test output includes jsdom's unimplemented canvas/navigation notices.
- SDK: **27 contract tests** and TypeScript passed. Bead: **360 tests / 44 files**, production build and **4 package checks** passed. Registry: **122 tests** passed.
- Launcher: Rust workspace **299 passed / 6 ignored**, QA **186 passed / 5 ignored**, Clippy with warnings denied, **261 frontend tests**, **192 Python tests**, frontend build. Final targeted project Rust/UI checks passed after follow-up changes.
- Distribution: **648 Python tests passed / 3 skipped**. The skipped tests need a separate archive-codec binary. Final Windows/macOS ZIP marker checks and public-source adaptation tests ran.

The route-canary fixtures predated current material preflight and passed sentinel, non-LUT/non-ZIP bytes into real native readers. Their same failures were reproduced with baseline route code. They now stub those unrelated owners while retaining scheduling/logging assertions. The real generation and slicer runs below exercise actual files.

## Real application and native output

A local Vite application and Python 3.12 backend processed a 40×30 image with a private four-color LUT. A selected region was replaced, captured and reopened into a fresh session. Selection remained **2,646 pixels**, one local replacement remained, and recapture produced a new valid editor checkpoint. The global library did not contain the fixture LUT.

Separate runs saved/reopened SVG input, an STL model with face 3 selected and 37° rotation, and a real vectorization result (42,672-byte SVG) that remained editable after restore. The browser's dirty navigation guard was exercised during reload.

The actual built bead module ran in its sandbox with the SDK MessagePort. Clicking its 3D editor placed a bead at cell 496. Host capture → `.lum` → empty workspace → reopen preserved the cell, project identity and undo history; the restored UI could undo and redo the edit. This browser development harness served the local module build and synthetic color-library responses; it was not an installed desktop runtime test. Download fallback preserved the dirty state, cancelling a new-project transition retained the active project, and project-center search and pin controls worked. Light, dark and narrow-viewport screenshots were inspected.

One frozen `.lum` revision was attached to standard 3MF, two large-format tile 3MFs, a four-piece puzzle and a two-image batch. Every embedded copy matched the frozen file byte-for-byte. All four download URLs returned **200 after closing the source editor session**.

**Bambu Studio 02.08.02.61** loaded all five resulting 3MF files via its actual `--info` importer with exit code 0 and reported manifold geometry. Standard output measured 10 × 7.5 × 1.6 mm. The check exposed and fixed OPC namespace-prefix rewriting and a duplicate puzzle source-slot mapping. OrcaSlicer 2.4.2 parsed the corrected package but rejected this Bambu 2.8 fixture's process settings; it is not counted as an Orca-profile pass.

Reproduction evidence is retained locally under `output/playwright`: the `.lum`, generated 3MF/ZIP files, compact verification JSON and slicer logs. Transient command logs and fixture drivers are task-local under `.scratch` and are not product source or committed machine paths.

## Boundaries

No signed desktop installer or release was built. Native installed-package double-click tests on Windows/macOS and full fresh-machine manual runs of each workflow are outstanding release acceptance, not claimed here. Missing legacy assets cannot be reconstructed from old operation logs. Unsupported module/schema documents are preserved for limited inspection instead of being executed. See [coverage-matrix.md](coverage-matrix.md) for the evidence level per workflow.

AI assistance: GPT-6 via Codex desktop implemented, tested and reviewed this adaptation; exact earlier model identities for inherited code are unknown. There is no claim of human review.
