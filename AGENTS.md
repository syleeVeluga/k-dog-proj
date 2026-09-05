# Repository Guidelines

## Project Structure & Module Organization

K-DOG is an operator-facing dog/guardian assessment application at milestone M0 (domain contracts and catalog import). `docs/` contains:

- `K-DOG_PRD_v0.4_20260905.md`: product requirements and roles.
- `K-DOG_바이브코딩_구현지시서_v1.0_20260905.md`: MVP scope, implementation contracts, and acceptance checks.
- `K-DOG_AI_처리_파이프라인_v0.1_20260905.md`: AI stages and data contracts.
- `K-DOG_문서검수_v1.0_20260905.md`: unresolved review findings F-01–F-05.

`backend/app/domain/` contains validated Python contracts; `backend/app/import_catalogs.py` reads source Excel workbooks in `docs/`. Tests and synthetic fixtures live in `backend/tests/`; extracted catalogs and pending-rule records live in `resources/`. Frontend, API, database, and worker implementation are planned for later milestones. Create directories only when needed.

## Build, Test, and Development Commands

From `backend/`, run `uv sync --locked` to install pinned dependencies, `uv run --locked python -X utf8 -m unittest discover -s tests -v` for tests, and `uv run --locked python -X utf8 -m app.import_catalogs --check` to verify catalogs against Excel. See `docs/DEVELOPMENT.md`. No application server/build command exists yet. Repository-root checks:

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

Tests use standard-library `unittest`; no coverage threshold is configured. Use implementation-guide §11 scenarios T01–T16 to drive tests, especially scoring, permissions, exports, and interrupted-worker recovery. Address review findings F-01–F-05 when implementing affected contracts. Name Python tests `test_<behavior>.py`. Keep fixture-based tests distinct from real provider validation. For documentation changes, check links and consistency across specifications.

## Commit & Pull Request Guidelines

The single existing commit uses `docs: 초기 K-DOG 프로젝트 문서 추가`. Continue concise, type-prefixed subjects such as `docs: clarify retry behavior`; no broader historical convention exists. PRs should describe scope, affected requirements, validation performed, and unresolved issues. Link related issues when available; include screenshots for UI changes.

## Security & Agent Instructions

Keep API keys, participant data, videos, and runtime files outside source control. Preserve read-only source materials; never invent missing assessment rules. `.codebase-memory/` is an ignored local cache.

## Mandatory Codebase Memory Usage

Always use `codebase-memory-mcp` for repository code discovery and analysis. Check indexing with `list_projects`; run `index_repository` if missing and refresh stale indexes before relying on them.

- Use `search_graph` to find symbols, then `get_code_snippet` with the returned qualified name.
- Use `trace_path` for callers/dependencies, `query_graph` for complex relationships, and `get_architecture` for an overview.
- Use `search_code` for graph-aware text searches.

Do not bypass these tools with grep/glob/direct source reads. Text search is allowed for documentation, configuration, string literals, or insufficient graph results. If MCP is unavailable, state the limitation before using fallback tools.

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
