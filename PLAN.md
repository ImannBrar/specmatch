# Plan

This is my order of work, my matching strategy, the risks I see, and my
time budget. If I deviate from this plan, I will note it in the README.

## Order of work

1. **Orientation (this commit).** Read the codebase, answer the Task 1
   questions, write this plan. About 1 to 1.5 hours.
2. **Issue fixes (Task 2).** For each of #1, #2, #3: first commit a
   failing test that reproduces the bug, then commit the fix separately,
   referencing the issue number. I do these before the engine on purpose.
   The engine depends on two of them. Match results pass through
   `assign_tier()` (issue #2). And issue #1 duplicates records on every
   restart, which would corrupt any tier numbers I report. About 1.5
   hours.
3. **Matching engine (Task 3).** The core of the challenge. See the
   strategy below. Includes tests: hand-built records that must land in
   specific tiers, plus boundary tests driven by config values. About 3
   to 4 hours.
4. **API endpoints (Task 4).** Build `/health`, `/matches` with tier
   filter and paging, and the review endpoint. All must match the frozen
   contracts (fixed request and response shapes) in `models/schemas.py`.
   Add tests for the response shapes. About 1 hour.
5. **Review console (Task 5).** Complete the stubbed `/review` page using
   the existing page style: tier queues with counts, per-signal score
   breakdowns, and accept/override/reject forms. About 1.5 hours.
6. **Docker and CI (Task 6).** Confirm the app starts from a fresh
   download with one command, and that data survives restarts. Extend CI
   (the automated checks that run on every push) to run tests, lint, and
   a Docker build, next to the existing frozen-file check. About 1 hour.
7. **Documentation.** Write the README: diagram, setup steps, API
   examples, engine design, the measured tier counts, the root cause of
   each issue, and an honest section on how I used AI. Extend CLAUDE.md
   with the project rules I actually relied on. About 1 hour.

Total: roughly 10 to 11 hours against the 8 to 12 hour budget.

## Matching engine strategy

The interfaces in `services/matching/interfaces.py` are fixed. Retrieval
finds likely candidates, scoring rates each one, and the engine ties it
together. My plan:

- **Clean the text first (normalization).** Source text looks like
  `CONC RM 30MPa w/ 25% FA`. The catalog says "Ready-mix concrete,
  30 MPa, 25% fly ash". Comparing them raw is useless. So: lowercase
  everything, strip punctuation, and expand a map of common construction
  shorthand (CONC means concrete, RM means ready-mix, INSUL means
  insulation, MW means mineral wool, FA means fly ash, and so on). Also
  clean up numbers with units, like `30MPa`.
- **Retrieval.** Compare the cleaned record text against all 800 cleaned
  catalog entries by counting shared words. The catalog is small, so
  checking every entry is fine. Keep the best 20 or so for full scoring.
- **Scoring.** Combine three signals with weights: text similarity,
  category agreement (do the two categories match), and unit
  compatibility (do the units of measure match). The weights come only
  from `config/settings.yaml`, using the keys already defined there.
  Nothing is hardcoded.
- **Tiering.** The final score goes through the existing `assign_tier()`
  function (after the issue #2 fix). The top candidates are saved with
  their per-signal scores, so a reviewer can see why each match scored
  the way it did.
- **Same input, same output (determinism).** Sorting is stable, with ties
  broken by catalog id. The tier counts I report in the README must come
  out identical when the reviewers re-run it.
- Records with no real description, like `MISC MTL ALLOW` or
  `MATL PER DWG S-501`, must land in red. I will not tune the numbers to
  make red disappear.
- **Stretch goal (only if time remains).** Compare against a
  meaning-based retrieval approach (embeddings). Skipped by default. A
  strong core beats extras.

## Risks

- **Time.** About 10 hours of work against a hard deadline. Mitigation:
  strict task order above, a timebox on the console, and the stretch
  goal already cut.
- **Reviewers re-run my tier counts.** If my engine is not fully
  deterministic, my README numbers will not match theirs. Mitigation:
  stable sorting, committed config, and a final check from a fresh
  download before submitting.
- **Overfitting the shorthand map.** A hand-built map can quietly
  memorize the test data. Mitigation: keep it to genuinely common
  construction shorthand, and document it as a design choice in the
  README.
- **Windows at home, Linux in CI and Docker.** Line endings and paths
  can differ. Mitigation: run the full test suite inside Docker before
  the final push.
