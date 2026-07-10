# Architecture notes

These are my orientation answers for Task 1. I wrote them after reading
the starter code. Paths are relative to `backend/` unless they start with
`config/` or `data/`.

## 1. Tracing one record from CSV to the review console

Take the first row of `data/source_records.csv`:
`SRC-0001,"BATT  INSUL MW R-22",Insulation,m2,4526.8`.

It passes through these modules, in order:

1. **`app/main.py`**. This is where the app starts. On startup it calls
   `run_ingest()` before serving any request. Ingest means loading the
   raw data files into the database.
2. **`app/services/ingest.py`**. `run_ingest()` sets up the database
   tables. Then `ingest_records()` reads `data/source_records.csv` and
   inserts each row into the `records` table. It also stamps the time it
   was loaded.
3. **`app/core/db.py`**. This module owns the database. It is SQLite (a
   small database stored in one file). The row now lives in the file
   `specmatch.db` under the data folder. Docker mounts a volume there (a
   piece of storage that outlives the container), so data survives
   restarts.
4. **`app/services/matching/engine.py`**. The matching engine (built in
   Task 3) picks the record up from the database. It finds likely catalog
   entries, scores each one, and combines the scores using weights from
   `config/settings.yaml`. Then
   **`app/services/matching/tiering.py`** maps the final score to a tier
   (green, yellow, or red, which means accept, review, or reject). The
   result is saved as JSON in the `matches` table.
5. **`app/routers/console.py`**. The review page route (`GET /review`)
   reads that saved match back out of the database.
6. **`app/templates/review.html`**. This template renders the page. It
   shows the source text, the scored candidates, and the review actions.

Side note: the record table at `GET /` shows the raw record even before
matching. That path is `console.py` plus `templates/records.html`. The
API version is `app/routers/records.py`.

## 2. Tier thresholds: where they live, and how to move them

The thresholds (the score cutoffs between tiers) are defined in
**`config/settings.yaml`** under the `tiers:` key:

```yaml
tiers:
  accept_min: 0.85   # score >= accept_min            -> green
  review_min: 0.60   # review_min <= score < accept   -> yellow, below -> red
```

`app/config.py` loads them with `get_settings()` into the
`TierThresholds` object. Both values are inclusive lower bounds, meaning
a score equal to the cutoff belongs in the higher tier. The function
caches its result, and the `SPECMATCH_CONFIG` environment variable can
point it at a different file. Tests use that to inject their own values.

To move the review/accept boundary without touching Python: edit
`accept_min` in `config/settings.yaml`. For example, change `0.85` to
`0.90` to send more matches to human review. Then restart the app so the
cached settings reload.

## 3. The CONTRIBUTING.md rule for failing dependency calls

Quoted from `CONTRIBUTING.md` (Error handling):

> Every call to an external dependency (filesystem, network, subprocess,
> database file) must catch the dependency's specific exception type at the
> call site, log a structured `dependency_failure` event that includes the
> dependency name and enough context to reproduce, and re-raise as
> `app.core.errors.DependencyError` using `raise ... from exc`.

In plain words: when code talks to something outside the app (like a
file), and that fails, the code must catch that exact error where it
happened, write a structured log line about it, and raise the project's
own error type in its place.

One place the existing code follows this rule: **`_read_csv()` in
`app/services/ingest.py`**. It catches `OSError` (the error type for
file problems) right where the file is read. It logs a
`dependency_failure` event with the dependency name, the path, and the
error text. Then it raises `DependencyError(...) from exc`. The
`get_settings()` function in `app/config.py` follows the same pattern
when it reads the YAML file.
