# Project coverage and evidence

Implementation covers each active Layers creation workflow. This table separates automated owner/adapter checks from actual application runs; it does not claim every workflow has a complete platform installation test.

| Workflow | Persisted state and restore owner | Evidence |
| --- | --- | --- |
| Converter raster and SVG | Original/derived input, current recipe, project color source, output settings; fresh preview plus editor checkpoint | Real browser raster and SVG save/reopen; new session; 2,646 selection pixels and local replacement retained; adapter and checkpoint regressions |
| Spatial edits and custom stacks | Existing editor checkpoint including masks, selection, overrides and source binding | `test_editor_project_unit.py`, converter adapter, selection/history regressions; real local replacement roundtrip |
| Model surface | Original model, face index, rotation and placement; existing upload/select owners | Real STL upload → selected face 3 at 37° → save → fresh upload/select; adapter pose tests |
| Crop, relief, geometry, puzzle and batch | Canonical recipe plus original/derived source bookkeeping, heightmap bytes and ordered batch inputs | Existing recipe property tests in the full frontend suite; model/crop/recipe adapter checks; real four-mode generation |
| Calibration / gradient generation | Parameters, output settings, generated files and previews | Workflow adapter roundtrip and existing calibration tests |
| LUT extraction | Photograph, corners, confirmed ColorChecker pixels, editable LUT and page collection in a private workspace | Real byte checkpoint tests remove the original directory, restore, edit and recapture; multi-page and merged-result cases; frontend adapter checks |
| Gradient extraction | Both photographs, orientation/corners, calibrated sources, fit parameters, material draft and generated files | Backend fit checkpoint restores into a fresh owned session; frontend adapter roundtrip |
| Five-color recipes | Bound LUT bytes, selected layers, collection and swatch parameters/results | Adapter tests preserve recipes; backend private-context query tests |
| LUT manager / compare / details | Selected LUT bytes, query/selection/merge parameters and results | Each adapter tested against an empty/different library; private lookup wins over a same-named global LUT |
| Vectorizer | Input, parameters, actual result SVG and downstream Converter input | Real vectorization → save/reopen → editable parameters; tab-unmount preservation and stale completion regressions |
| Workshop / official bead module | Live source/raster, calibration, editor history, tool and palette through SDK handshake | Actual sandbox module UI edit → `.lum` → fresh workspace → restore → undo/redo, using browser development host fixtures; host rollback, SDK, live component and local package checks |
| File center / recovery | New/open/save/save-as/bundle, dirty guards, cover, search, recent files, pin/remove/locate, recovery choice | Browser application checks; file identity, native broker, atomic write, recovery quota/failure and stale-save tests |
| Launcher / packaging | Bounded capability selection, queue, file association and confirmed completion | Launcher Rust/UI/Python suites; actual shared-root receipt tests; Distribution Windows/macOS ZIP marker tests |

Project documents never depend on a saved `sessionId`, temporary file URL, process, local installation path or cloud credential. Derived runtime artifacts are recreated or rebound. A capture during an unsupported in-flight operation reports that operation instead of recording a partially committed result.

Native signed installers, Windows Explorer/macOS Finder double-click delivery on installed release packages, and a full fresh-machine walkthrough for every workflow remain release acceptance work. The implementation and package contracts are included in the linked PRs; no runtime, SDK or registry release is published here.
