# SpecMatch — AI assistant context

SpecMatch matches messy construction-material records to a canonical
catalog, assigns confidence tiers, and exposes the results through a
FastAPI API and a server-rendered (Jinja2) review console.

## Layout

- `backend/app/` — FastAPI application; `routers/` stay thin, logic lives
  in `services/`.
- `backend/app/models/schemas.py` — API contracts. **FROZEN: never modify.**
- `backend/app/services/matching/` — matching interfaces; the engine
  implementation goes here.
- `config/settings.yaml` — scoring weights and tier thresholds. Read them
  via `app.config.get_settings()`; never hardcode.
- `data/` — fixture CSVs ingested at startup.

## Commands

- Run locally: `cd backend && uvicorn app.main:app --reload`
- Tests: `cd backend && pytest`
- Full stack: `docker compose up --build` (API + console on :8000)
- On this Windows dev machine: use the Python 3.12 venv at
  `backend/.venv` (`.venv\Scripts\python.exe -m pytest`). Do NOT use the
  system Python 3.14 — pinned dependencies do not install on it.

## Hard rules (breaking these disqualifies the submission)

1. **Never modify `backend/app/models/schemas.py`.** CI verifies its
   sha256 on every push. If a contract seems wrong, document it in the
   README instead.
2. **Never hardcode scoring weights or tier thresholds.** They live in
   `config/settings.yaml` and are read through
   `app.config.get_settings()`. Tests inject their own config via the
   `SPECMATCH_CONFIG` env var or by constructing `TierThresholds`
   directly.
3. **No credentials in the repo.** `.env` stays gitignored; only
   `.env.example` is committed.
4. **CI must be green on the final commit to `main`.**
5. **`docker compose up --build` must work from a clean clone**, with
   data persisting across restarts (SQLite file on the mounted volume
   under `DATA_DIR`).

## Commit conventions

- Imperative subject line, max 72 characters.
- One logical change per commit.
- A test that reproduces a bug is committed **before** the commit that
  fixes it. For filed issues use paired messages:
  `Issue #N test: <what it reproduces>` then `Issue #N fix: <what changed>`.
- Commits are authored by the repo owner only — no co-author trailers.

## Logging contract

- Every log line goes through
  `app.core.logging.log_event(logger, level, event, **fields)`.
- `event` is a snake_case identifier (`ingest_completed`,
  `review_persisted`); all context goes in keyword fields.
- Never use `print()` or string-interpolated log messages.

## Error handling contract

Every call to an external dependency (filesystem, network, database
file) must catch the dependency's specific exception type at the call
site, log a structured `dependency_failure` event with the dependency
name and enough context to reproduce, then re-raise as
`app.core.errors.DependencyError` using `raise ... from exc`.
Reference implementation: `_read_csv()` in `app/services/ingest.py`.

## Architecture rules

- Routers handle HTTP only; all logic lives in `services/`.
- The matching engine implements the abstract interfaces in
  `services/matching/interfaces.py` (retriever → scorer → engine) so
  strategies stay swappable.
- Tier assignment always goes through
  `services/matching/tiering.py:assign_tier()`; both thresholds are
  inclusive lower bounds.
- Matching must be deterministic: stable sorts, ties broken by
  `catalog_id`. The README reports tier counts that reviewers re-run.
- Persist the top-k candidates (`Settings.matching.top_k`) per record
  with per-signal score breakdowns, as JSON in the `matches` table.

## Console conventions

- Server-rendered Jinja2 only — no JS frameworks; plain GET/POST forms
  (see the category filter form in `templates/records.html`).
- Render with `templates.TemplateResponse(request, name, context)`.
- Templates extend `base.html`.

## Test conventions

- Pytest, files under `backend/tests/`. The session-scoped `client`
  fixture in `conftest.py` boots the app against a throwaway database.
- Engine tests assert that specific constructed records land in specific
  tiers, including deliberate red cases (`MISC MTL ALLOW`,
  `MATL PER DWG S-501` must be red).
- Boundary tests drive thresholds from config values, not literals
  matching the shipped YAML by coincidence.

## Documentation style

- No em-dashes in project docs (README, PLAN, ARCHITECTURE_NOTES).
- Plain language, short sentences (aim near Flesch 80). Basic technical
  terms are fine; important ones get a short explanation in brackets on
  first use.
- The README must include: architecture diagram, setup, API reference
  with curl examples, how to run tests, matching design with measured
  tier distribution, root causes of the three issue fixes, an honest AI
  usage section, and deviations from PLAN.md.
