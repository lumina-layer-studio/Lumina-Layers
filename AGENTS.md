# Repository Guidelines

## Scope
Lumina Studio is a Python + React/TypeScript multi-material FDM color workflow built around `api/` + `api_server.py` + `frontend/` (FastAPI `:8000` + Vite `:5174`).

## Structure
- `core/`: UI-agnostic domain logic and the staged pipeline in `core/pipeline/`
- `api/`: FastAPI routers, schemas, session/file lifecycle, and worker orchestration
- `frontend/src/`: React 19, TypeScript, Zustand, Axios, Three.js, Tailwind, and Vitest
- `tests/` and `frontend/src/__tests__/`: backend/frontend regression coverage
- `printer_profiles/`, `assets/`, `lut-npy预设/`: templates, runtime assets, and LUT presets

## Common Commands
- `pip install -r requirements.txt`
- `cd frontend && npm install`
- `python api_server.py` | `python start_dev.py`
- `cd frontend && npm run dev|build|lint`
- `python -m pytest tests/ -v`
- `python -m pytest tests/ --hypothesis-show-statistics`
- `cd frontend && npx vitest --run`
- `docker build -t lumina-layers . && docker run -p 7860:7860 lumina-layers`

## Engineering Rules
- Python: PEP 8, explicit type hints, bilingual Google-style docstrings for new or changed public APIs
- Prefer NumPy/vectorized operations in hot paths
- Code shall favor good OO design: clear abstractions, single responsibility, high cohesion, low coupling, and readable composition
- Code shall remain easy to read: descriptive names, small helpers, shallow nesting, and no overlong functions, god objects, or copy-pasted logic
- Worker entry points must be top-level and picklable; pass only scalars and file paths across processes
- Reuse canonical enums/config from `config.py`, API schemas, and frontend constants
- New color modes, modeling modes, printer profiles, or slicer integrations must update validation, UI, translations, persisted settings, and tests together

## Lossless Refactoring
- Keep all existing public API signatures unchanged during refactors
- Write tests to verify current behavior before modifying implementation
- Each refactor should focus on a single responsibility; avoid sweeping changes

## Frontend Rules
- All user-facing strings must come from `frontend/src/i18n/translations.ts`
- Support both light and dark themes via tokens/Tailwind vars; no raw UI colors like `#fff`, `bg-white`, or `text-black`
- Keep components focused on presentation/local interaction; use API clients and Zustand stores for orchestration
- Preserve `settingsStore` persistence and best-effort backend sync

## Architecture & Robustness
- Preserve layering: `core/` -> API/workers -> UI
- Put reusable business logic in `core/`; routes do validation, session/file handling, and error translation; CPU-heavy work belongs in workers or `core/`
- The staged pipeline lives in `core/pipeline/` (S01–S12 step modules coordinated by `coordinator.py`)
- Keep preview/generation flows compatible with `SessionStore` and `FileRegistry`
- Validate file types, LUT/mode compatibility, coordinates, required cache/session keys, and optional dependencies early with actionable errors
- Never assume session/cache state exists or is fresh; return deterministic `4xx`/`5xx`, not raw tracebacks
- Register every temp file for cleanup; preserve original state before destructive cache mutations; prevent stale preview/download caching
- Use explicit timeouts, distinguish fatal vs non-fatal failures, and degrade optional features such as HEIC/HEIF gracefully
- Current supported workflows include calibration, extraction/manual correction, LUT merge/inspection, preview/generation, batch conversion, large-format tiled generation, printer/slicer integration, and BW/4-color/6-color/8-color/5-color-extended modes

## Tests
- Backend: `pytest` + Hypothesis; Frontend: Vitest + fast-check
- File naming: `test_*_unit.py` / `test_*_properties.py` (Python); `*.test.ts(x)` / `*.property.test.ts` (Frontend)
- Add focused regression tests for new algorithms, bug fixes, cache/session/temp-file cleanup, timeout/fallback paths, invalid uploads/LUTs, and out-of-bounds/background clicks

## Hygiene & Commits
- Do not commit secrets, machine-local config, IDE junk, generated caches, or transient artifacts
- `user_settings.json` is optional runtime data; code must tolerate missing or partial values safely
- Use Conventional Commits: `<type>(<scope>): <subject>`
- When commit bodies or PR descriptions are needed, write English first and Chinese second
- Summaries should explain why, not just touched files
