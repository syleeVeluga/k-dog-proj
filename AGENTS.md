# Repository Guidelines

## Project Structure & Module Organization

K-DOG is an operator-facing dog/guardian assessment application. The final development target is the 2026-10-02 integrated specification v1.3 / S1.1. Start with `docs/개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md`, then its requirement traceability, source inventory, open questions and individual PR-S00–S17 plans. Customer originals in ignored `docs/요구사항_20261003/` are local-only; obtain them through the project owner and verify the recorded hashes before source-dependent implementation. Do not commit participant data or these source files. At the review baseline `3654596`, C00–C07B of the 2026-09-29 edition are implemented, the API defaults to that edition, and S1 implementation has not started. A plan-document merge does not implement S1. On 2026-10-03 the user authorized discarding existing app scores and derived results: S01 resets them, preserves raw inputs/operational records, and starts S1 scores empty. Do not build old-score migration/read compatibility. Protect new S1 revisions normally. Remove replaced old execution paths only after checking callers. `docs/` contains:

- `K-DOG_개발기준변경검토_v1.0_20261003.md`: final requirements versus baseline implementation.
- `개발반영_20261003/`: active S00–S17 plans, R01–R25/T01–T32 traceability, D01–D06/G01–G05, source access and review record.
- The prior 2026-09-29 C00–C15 plans and Q01–Q12 ledger (`개발반영_20260929/`) were removed from the working tree on 2026-10-03; read them at commit `056ed7a` for completed infrastructure evidence, not superseded scoring/report assumptions.

- `큐브전달_20260929/`: historical v3 source, still checked by `app.import_catalogs --check`. It does not override the final S1 specification.
- `DEVELOPMENT.md`, `PILOT_OPERATIONS.md`: environment, commands, installation and operations.
- `K-DOG_Gemini영상API_적용계획_v1.0_20260907.md`: Gemini video request contract (infrastructure).

Earlier 55-item documents (PRD v0.4, implementation guide, M1–M6 records) were removed on 2026-09-15 and exist only in git history before commit `7124809`. The 9월 13일 `최종 고객 문서/` source folder (42-item edition; it was not final — the final source is `docs/요구사항_20261003/`) and the plans/reviews built on it (변경검토 0915, P0/P1, 검수결과·검수인계·채점규칙 확인요청, `검수개선/`, `리포트구현/`) were removed on 2026-10-03; read them at commit `056ed7a`. Do not treat their scoring, aggregation or report rules as current.

`backend/app/domain/*_v3.py` contains the separate 9월 29일 contracts for 117 original rows, 113 used rows, 109 direct entries and four automatic rows, with raw Korean row codes. The unmodified `base.py/catalog.py/contracts.py/validation.py` remain the 42-item v2 edition. `backend/app/legacy/` holds read-only 55-item modules still imported by the frozen worker; no new features there. `backend/app/import_catalogs.py` extracts/checks only the 9월 29일 source via `import_catalogs_v3.py`; the 9월 13일 source folder (`최종 고객 문서/`) was removed on 2026-10-03, so the committed `*-v2.json` catalogs are kept as-is and no longer re-verified against Excel. `resources/catalogs/*-v1.json` remains read-only and checked against `resources/source/` by tests. `backend/app/api.py` provides the FastAPI API; `storage.py` manages SQLite and immutable input files; `worker.py` runs analysis stages. `frontend/` contains the React UI. Tests and synthetic fixtures live in `backend/tests/` and `frontend/tests/`; extracted catalogs, rules and mappings live in `resources/`. Create directories only when needed.

## Build, Test, and Development Commands

From `backend/`, run `uv sync --locked` to install pinned dependencies, `uv run --locked python -X utf8 -m unittest discover -s tests -v` for tests, and `uv run --locked python -X utf8 -m app.import_catalogs --check` to verify catalogs against Excel. From `frontend/`, use `npm ci`, `npm run build`, and `npm run test:e2e`. Start the built app from `backend/` with `uv run --locked python -X utf8 -m app.manage serve`. See `docs/DEVELOPMENT.md` for initial account provisioning and browser installation. Repository-root checks:

- `git status --short`: inspect pending changes.
- `git diff --check`: detect whitespace errors in tracked changes.
- `git diff -- docs/`: review requirement edits.

When scaffolding the application, document exact installation, local startup, build, and test commands in `docs/`; commit dependency lockfiles alongside tooling.

## Mandatory Library & Framework Version Verification

Before installing or using any library or framework, always search the internet to verify its latest stable version. Check official documentation, release notes, and the official package registry; do not rely on memory or existing manifests alone.

- Confirm runtime compatibility, peer dependencies, breaking changes, and the API documentation for the selected version before implementation.
- Default to the latest compatible stable release. If an existing project constraint requires an older version, record the latest version, selected version, and reason; do not silently upgrade unrelated dependencies.
- Record the verification date and source links in the work summary, and pin installed dependency versions in the appropriate manifest/lockfile.
- If online verification is unavailable, report the blocker and continue independent work; do not install or introduce unverified library/framework usage.

## Coding Style & Naming Conventions

Preserve Korean terminology, requirement IDs, relative document links, and version/date metadata. Follow the existing document naming pattern: `K-DOG_<topic>_v<version>_<YYYYMMDD>.md`.

No formatter, linter, or indentation configuration exists. For new code, use four-space Python indentation and two-space TypeScript/CSS indentation; use `snake_case` for Python functions/modules and `PascalCase` for React components. Keep modules small and validate API input/output types explicitly.

## Testing Guidelines

Tests use standard-library `unittest`; no coverage threshold is configured. For S1 changes, derive expectations from the final integrated specification, its calculation workbook and `docs/개발반영_20261003/` traceability/acceptance ledgers. Superseded 42-item/v3 values are not S1 golden values. Keep the established safeguards (immutable per-attempt artifacts with occupancy tokens, re-checking deletion state before use, explicit reuse manifests, pinned revisions in exports, distinguishing missing observation from undecided rules). Name Python tests `test_<behavior>.py`. Keep fixture-based tests distinct from real provider validation. For documentation changes, check links in the committed tree as well as local source hashes and consistency across specifications.

## Commit & Pull Request Guidelines

Use concise, type-prefixed subjects (`docs:`, `feat:`, `fix:`, `release:`, `merge:`) such as `docs: clarify retry behavior`. Work in one branch per PR and follow the PR procedure in `docs/개발반영_20260929/K-DOG_개발반영계획_v1.0_20260930.md` (implement → verify → review → triage findings → apply accepted ones → push). PRs should describe scope, affected requirements, validation performed, and unresolved issues. Link related issues when available; include screenshots for UI changes.

## Security & Agent Instructions

Keep API keys, participant data, videos, and runtime files outside source control. Preserve read-only source materials; never invent missing assessment rules.

## Mandatory Graft Usage

Always use graft for repository code discovery and analysis, in every session and task. If `graft/` is missing or `graft check` reports it stale, run `graft build` before relying on it.

- Use `graft ask "<task>" --source` (MCP `graft_find_code`) to locate and understand code.
- Use `graft grep "<literal>"` (`graft_find_all`) when every occurrence is needed.
- Use `graft callers <symbol>` (`graft_trace_calls`) before changing a symbol, `graft skeleton <file>` (`graft_file_api`) for a file's API, and `graft map` (`graft_repo_map`) for an overview.

Do not bypass these with grep/glob/whole-file reads. Text search is allowed for documentation, configuration, string literals, unindexed files, or insufficient graph results. Run `graft build` after code changes. If graft is unavailable, state the limitation before using fallback tools.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->
