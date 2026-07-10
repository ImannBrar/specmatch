# SpecMatch

SpecMatch matches messy construction-material records to a clean catalog.
Site records look like `CONC RM 50MPA W/ 25% SLAG`. The catalog says
"Ready-mix concrete, 50 MPa, 25% slag". The engine finds the right catalog
entry for each record, scores its confidence, and sorts every match into a
tier: green (auto-accept), yellow (needs human review), or red (no
acceptable candidate). A small web console lets a reviewer work through
the yellow and red queues.

## How a record flows through the system

```
 data/catalog.csv        data/source_records.csv
        |                          |
        v                          v
 +--------------------------------------+
 |  ingest  (services/ingest.py)        |  runs at startup, safe to re-run
 +--------------------------------------+
                    |
                    v
      SQLite database (core/db.py)
      file lives under DATA_DIR, so a Docker
      volume keeps it across restarts
                    |
                    v
 +--------------------------------------+
 |  matching engine (services/matching) |
 |  normalize -> retrieve -> score      |
 |  -> assign tier (tiering.py)         |
 +--------------------------------------+
                    |
                    v
        matches table (one JSON result per record)
              |                     |
              v                     v
     JSON API (routers/)     review console (Jinja2 pages)
     /health /records        GET /  GET /review
     /matches                POST /review/{record_id}
```

Both ingest and matching run once at startup and are idempotent (running
them again changes nothing). Existing match results are kept as they are,
so review decisions survive restarts.

## Quick start (Docker)

```bash
git clone https://github.com/ImannBrar/specmatch && cd specmatch
cp .env.example .env
docker compose up --build
```

Console: http://localhost:8000 (record table at `/`, review queues at
`/review`). Interactive API docs: http://localhost:8000/docs.

The SQLite file lives on the `specmatch-data` volume. Restarting or
recreating the container keeps all data, including review decisions.

## Local development (without Docker)

Use Python 3.11 or 3.12. The pinned dependencies do not install on 3.14.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Tests and lint

```bash
cd backend
pytest                       # full suite, 40 tests
pytest tests/test_matching.py            # one file
pytest -k boundary                       # tests matching a keyword
```

The suite covers the three issue fixes (each was reproduced by a failing
test before the fix), engine behavior (known records must land in known
tiers, including deliberate red cases), threshold boundaries driven by
injected config, API response shapes, and the console flows.

CI also lints with ruff (a fast Python linter):

```bash
pip install ruff==0.15.21
ruff check backend
```

## API reference

All responses follow the frozen contracts in
`backend/app/models/schemas.py`.

### GET /health

```bash
curl http://localhost:8000/health
```

```json
{"status":"ok","records":150,"matched":150,"tiers":{"green":124,"yellow":14,"red":12}}
```

### GET /records

Paged list of ingested source records. Query params: `limit` (1 to 500,
default 50) and `offset`.

```bash
curl "http://localhost:8000/records?limit=2&offset=0"
```

### GET /matches

Paged list of match results as `MatchesResponse`: a `total` count and an
`items` array. Optional `tier` filter (`green`, `yellow`, `red`), plus
`limit` and `offset`.

```bash
curl "http://localhost:8000/matches?tier=yellow&limit=1"
```

```json
{
  "total": 14,
  "items": [
    {
      "record_id": "SRC-0020",
      "source_text": "STL HSS 10X6X3/16",
      "tier": "yellow",
      "candidates": [
        {
          "catalog_id": "CAT-0118",
          "description": "Steel HSS 10x6x3/16, ASTM A500 Grade C",
          "score": 0.807,
          "signals": {
            "string_similarity": 0.887,
            "category_agreement": 0.5,
            "unit_compatibility": 1.0
          }
        }
      ],
      "selected_catalog_id": null,
      "review": null,
      "matched_at": "2026-07-10T20:40:48Z"
    }
  ]
}
```

(Response shortened and scores rounded here for readability: the real
response carries up to five candidates per result and full-precision
scores.)

### POST /matches/{record_id}/review

Records a human decision. Body: `action` (`accept`, `override`, or
`reject`), `catalog_id` (required for `override`), optional `note`.
Returns the updated match result. `404` for an unknown record, `422` for
an invalid request (for example, an override without a `catalog_id`).

```bash
# accept the top candidate
curl -X POST http://localhost:8000/matches/SRC-0020/review \
  -H "Content-Type: application/json" \
  -d '{"action": "accept"}'

# override with a specific catalog entry
curl -X POST http://localhost:8000/matches/SRC-0021/review \
  -H "Content-Type: application/json" \
  -d '{"action": "override", "catalog_id": "CAT-0351", "note": "grade B"}'
```

### Console routes

`GET /` renders the record table with a category filter. `GET
/review?tier=yellow` renders a review queue with tier counts and
per-signal score breakdowns. The forms on that page post to
`POST /review/{record_id}` and redirect back to the same queue.

## Matching engine design

The engine is lexical (it compares words, not meanings). The design has
four stages. Weights, thresholds, and top-k all come from
`config/settings.yaml` through `app.config.get_settings()`. Nothing is
hardcoded.

### 1. Normalization (`services/matching/normalize.py`)

Records abbreviate, the catalog spells things out. Both sides are
lowercased and split into tokens (single words or numbers), then record
tokens are translated into catalog wording:

- A hand-built abbreviation map (`CONC` means concrete, `MW` means
  mineral wool, `RM` means ready mix, and so on). I built it by diffing
  the record vocabulary against the catalog vocabulary over the fixture
  data, not by guessing.
- Two fallbacks for spellings the map does not know: a plural strip, and
  a unique-prefix expansion (construction shorthand is usually a
  chopped-off word, so `gyps` expands to gypsum if exactly one catalog
  word starts that way; an ambiguous chop like `con` stays untouched).
- Numbers get glued to what they measure: `50 MPa` becomes the single
  token `50mpa`, `25%` becomes `25pct`. Without this, "50 MPa, 25% slag"
  and "25 MPa, 50% slag" contain the same tokens and become
  indistinguishable.
- Dimension strings like `6x6x3/8` stay whole as one token. Splitting
  them loses which number is which, and HSS 4x2 would look like HSS 2x2.
- Words that only appear in non-material records (`ALLOW`, `DWG`, `MOB`)
  are deliberately not translated. Those records must score low and land
  in red.

### 2. Retrieval (`engine.py`, LexicalRetriever)

The catalog is small (800 entries), so the retriever ranks all of it for
every record and hands the best 50 to the scorer. Ranking uses weighted
token overlap: rare words count more than common ones. This matters
because 341 of the 800 entries say "miscellaneous fastener assortment".
Sharing the word "fastener" proves almost nothing. Sharing "slag" proves
a lot. The similarity is mostly containment (how much of the record's
token weight the entry explains), blended with a symmetric overlap term
that penalizes candidates carrying extra specs the record never said.

### 3. Scoring (`engine.py`, WeightedSignalScorer)

Three signals, combined with the weights from `config/settings.yaml`
(string_similarity 0.60, category_agreement 0.25, unit_compatibility
0.15):

- `string_similarity`: the weighted token similarity described above.
- `category_agreement`: 1.0 when record and entry categories match, 0.0
  when they contradict, 0.5 (neutral) when the record left it blank.
- `unit_compatibility`: the same rule for the unit of measure.

Every persisted candidate keeps its per-signal breakdown, so a reviewer
can see why it scored the way it did.

### 4. Tiering (`tiering.py`)

The top candidate's score goes through `assign_tier()`. Both thresholds
(`accept_min: 0.85`, `review_min: 0.60`) are inclusive lower bounds.
Green matches auto-select their top candidate. Yellow and red wait for a
human.

### Determinism

Reviewers re-run these numbers, so matching must give the same output
every time: stable sorts everywhere, ties broken by `catalog_id`, and the
exact config committed. Re-running `match_all()` never recomputes an
existing match, which also protects review decisions.

### Measured tier distribution

Over the 150 fixture records (a test pins these counts):

| Tier   | Count | What is in it                                                        |
|--------|-------|----------------------------------------------------------------------|
| green  | 124   | Confident matches, auto-selected                                     |
| yellow | 14    | Correct top candidate, but the record has no category, so one signal is neutral |
| red    | 12    | Non-material records: allowances, mobilization, drawing references, "XX DO NOT USE XX" |

I did not tune the thresholds to shrink red. Records like
`MATL PER DWG S-501` have no catalog answer, and red is the correct
outcome for them.

## The three issue fixes

Each fix has a paired history: a commit with a failing test that
reproduces the bug, then the fix commit. Root causes, not symptoms:

- **#1 Duplicate records after re-running ingest.** The `records` table
  had no uniqueness rule on `record_id`, and `ingest_records()` did a
  plain `INSERT`. Ingest runs at every startup, so every restart doubled
  the rows. Fix: a `UNIQUE` constraint on `record_id` plus
  `INSERT OR REPLACE`, the same convention the catalog table already
  used. Ingest is now idempotent.
- **#2 Wrong tier at the boundary.** `assign_tier()` compared
  `score > accept_min`, but the documented contract says both thresholds
  are inclusive. A record scoring exactly 0.85 landed in yellow instead
  of green. The `review_min` check already used `>=`. Fix: use `>=` for
  `accept_min` too.
- **#3 "All categories" showed no records.** The filter's All option
  submitted the literal value `All`, and the router ran
  `WHERE category = 'All'`, which matches nothing. Fix: the All option
  submits an empty value, and the router treats an empty value as "no
  filter".

## CI

Every push to `main` runs two jobs (`.github/workflows/ci.yml`):

- **test**: a schema freeze check (sha256 of the frozen
  `models/schemas.py` must not change), ruff lint, then the pytest suite.
- **docker**: `docker compose build`, so a broken Dockerfile cannot land
  quietly.

## AI usage

I used Claude Code throughout and steered it in conversation. Honest
split of the work:

**Delegated to the assistant:** environment setup, first drafts of
`ARCHITECTURE_NOTES.md` and `PLAN.md` (I reviewed them and had them
rewritten in plain language), reproducing and fixing the three issues
test-first, implementing the engine and console under my direction, and
the vocabulary diff between records and catalog that the abbreviation map
is built on.

**Kept manual:** every design decision. I had the assistant lay out
seven candidate matching approaches with tradeoffs, questioned it on
robustness, fuzzy-matching libraries, and compute cost, and made the
calls. One call that shaped the design: I rejected an embeddings
(meaning-based vector) approach for the core after my questioning
surfaced that embeddings blur numbers, and this catalog contains families
of entries that differ only by numbers, like ten variants of "Ready-mix
concrete, N MPa, M% additive". A matcher that cannot tell 25 from 50
cannot rank those.

**A concrete case where I corrected its output:** the first engine
version green-matched the challenge's own example record, SRC-0004
(`CONC RM 50MPA W/ 25% SLAG`), to the wrong catalog entry: 25 MPa with
50% slag instead of 50 MPa with 25% slag. Same numbers, swapped roles,
because tokens were compared as an unordered bag. I caught it while
checking the queues against the fixture data and had the normalizer glue
each number to its unit (`50mpa`, `25pct`). Related corrections during
review: dimension strings were being split (making HSS 4x2 look like HSS
2x2), one glue rule corrupted catalog dimensions until a lookbehind fixed
it, and a `w/` to "with" translation added a dead token to every record
carrying it, so it was dropped.

The project rules the assistant worked under are committed in
`CLAUDE.md`.

## Deviations from PLAN.md

- **Retrieval got rarity weighting.** The plan said "count shared
  words". Plain counting drowned in the 341 near-identical
  "miscellaneous fastener assortment" entries, so shared tokens are
  weighted by rarity instead.
- **The retriever keeps 50 candidates, not 20.** The plan guessed 20.
  With 50, the category and unit signals still have room to reorder the
  string ranking. It is a retrieval width, not a scoring weight, so it
  lives as a named constant in `engine.py`.
- **Normalization grew two fallbacks.** The plan promised only a fixed
  abbreviation map. I challenged whether a map covers real-world spelling
  drift (conc, conc., con), which led to the plural strip and the
  unique-prefix expansion on top of the map.
- **The embeddings stretch goal stayed cut**, as the plan allowed, for
  the number-blindness reason above.

Everything else went as planned, in the planned order.
