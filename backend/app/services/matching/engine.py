"""The matching engine (Task 3).

Design:

- Records and catalog entries are normalized into tokens (normalize.py).
- Retrieval ranks the whole catalog by weighted shared tokens; rare words
  count more than common ones (341 of 800 entries say "miscellaneous
  fastener assortment", so sharing "fastener" proves little, while
  sharing "slag" proves a lot).
- Scoring combines three signals with weights from
  config/settings.yaml (never hardcoded): string_similarity,
  category_agreement, unit_compatibility.
- Tier assignment goes through tiering.assign_tier with thresholds from
  Settings.tiers.
- The top-k candidates (Settings.matching.top_k) are persisted per
  record with their per-signal breakdowns as the MatchResult JSON
  payload in the matches table.
- Everything is deterministic: stable sorts, ties broken by catalog_id.
"""

import logging
import math
import sqlite3
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.core.db import get_conn
from app.core.logging import log_event
from app.models.schemas import Candidate, CatalogEntry, MatchResult, RecordOut, Tier
from app.services.matching.interfaces import (
    CandidateRetriever,
    CandidateScorer,
    MatchingEngine,
)
from app.services.matching.normalize import normalize_record_text, tokenize
from app.services.matching.tiering import assign_tier

logger = logging.getLogger(__name__)

# How many candidates the retriever hands to the scorer. Wide enough that
# the category and unit signals can reorder the string-similarity ranking.
# Not a scoring weight or threshold, so it lives here rather than config.
RETRIEVAL_LIMIT = 50


class CatalogIndex:
    """Token statistics over the catalog: each entry's token set, and how
    rare every token is across entries."""

    def __init__(self, catalog: list[CatalogEntry]):
        self.entry_tokens: dict[str, set[str]] = {
            entry.catalog_id: set(tokenize(entry.description)) for entry in catalog
        }
        self.vocab: set[str] = set().union(*self.entry_tokens.values())
        counts: dict[str, int] = {}
        for tokens in self.entry_tokens.values():
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
        self._doc_freq = counts
        self._n = len(catalog)

    def weight(self, token: str) -> float:
        """Rare tokens weigh more. A token in every entry weighs ~1; a
        token in one entry weighs ~log(N)+1."""
        return math.log((self._n + 1) / (self._doc_freq.get(token, 0) + 1)) + 1.0

    def similarity(self, record_tokens: set[str], entry_tokens: set[str]) -> float:
        """Weighted token similarity in [0, 1].

        Mostly "how much of the record's token weight does this entry
        explain" (containment), blended with a symmetric overlap term so
        an entry carrying extra specs is penalized a little. Containment
        dominates because catalog descriptions legitimately carry
        boilerplate the records omit ("CSA G40.21 300W"); the overlap
        term is what separates "20 MPa" from "20 MPa, 25% slag".
        These are the internal shape of the string_similarity signal,
        not signal weights (those come from config/settings.yaml).
        """
        shared = record_tokens & entry_tokens
        if not shared:
            return 0.0
        shared_w = sum(self.weight(t) for t in shared)
        record_w = sum(self.weight(t) for t in record_tokens)
        entry_w = sum(self.weight(t) for t in entry_tokens)
        containment = shared_w / record_w
        overlap = 2.0 * shared_w / (record_w + entry_w)
        return 0.7 * containment + 0.3 * overlap


class LexicalRetriever(CandidateRetriever):
    """Ranks the whole catalog by weighted token similarity."""

    def __init__(self, index: CatalogIndex):
        self._index = index

    def retrieve(
        self, record: RecordOut, catalog: list[CatalogEntry], limit: int
    ) -> list[CatalogEntry]:
        record_tokens = normalize_record_text(record.raw_text, self._index.vocab)
        ranked = sorted(
            catalog,
            key=lambda e: (
                -self._index.similarity(
                    record_tokens, self._index.entry_tokens[e.catalog_id]
                ),
                e.catalog_id,
            ),
        )
        return ranked[:limit]


class WeightedSignalScorer(CandidateScorer):
    """Combines per-signal scores into a composite using config weights."""

    def __init__(self, index: CatalogIndex, weights: dict[str, float]):
        self._index = index
        self._weights = weights
        self._record_token_cache: dict[str, set[str]] = {}

    def _record_tokens(self, raw_text: str) -> set[str]:
        if raw_text not in self._record_token_cache:
            self._record_token_cache[raw_text] = normalize_record_text(
                raw_text, self._index.vocab
            )
        return self._record_token_cache[raw_text]

    def _signals(self, record: RecordOut, entry: CatalogEntry) -> dict[str, float]:
        return {
            "string_similarity": self._index.similarity(
                self._record_tokens(record.raw_text),
                self._index.entry_tokens[entry.catalog_id],
            ),
            "category_agreement": _field_agreement(record.category, entry.category),
            "unit_compatibility": _field_agreement(record.unit, entry.unit),
        }

    def score(self, record: RecordOut, entry: CatalogEntry) -> Candidate:
        signals = self._signals(record, entry)
        total_weight = sum(self._weights.values())
        composite = (
            sum(self._weights[name] * signals[name] for name in self._weights)
            / total_weight
        )
        return Candidate(
            catalog_id=entry.catalog_id,
            description=entry.description,
            score=composite,
            signals=signals,
        )


def _field_agreement(record_value: str | None, entry_value: str) -> float:
    """1.0 when the record's category/unit matches the entry's, 0.0 when it
    contradicts it, 0.5 (neutral) when the record left it blank."""
    if not record_value:
        return 0.5
    return 1.0 if record_value.casefold() == entry_value.casefold() else 0.0


class LexicalMatchingEngine(MatchingEngine):
    """Retrieval + scoring over the ingested catalog."""

    def __init__(self, conn: sqlite3.Connection, settings: Settings | None = None):
        self._conn = conn
        self._settings = settings if settings is not None else get_settings()
        rows = conn.execute(
            "SELECT catalog_id, description, category, unit FROM catalog"
            " ORDER BY catalog_id"
        ).fetchall()
        self._catalog = [CatalogEntry(**dict(row)) for row in rows]
        index = CatalogIndex(self._catalog)
        self._retriever = LexicalRetriever(index)
        self._scorer = WeightedSignalScorer(index, self._settings.matching.weights)

    def match_record(self, record: RecordOut) -> MatchResult:
        entries = self._retriever.retrieve(record, self._catalog, RETRIEVAL_LIMIT)
        candidates = sorted(
            (self._scorer.score(record, entry) for entry in entries),
            key=lambda c: (-c.score, c.catalog_id),
        )
        top = candidates[: self._settings.matching.top_k]
        best_score = top[0].score if top else 0.0
        tier = assign_tier(best_score, self._settings.tiers)
        result = MatchResult(
            record_id=record.record_id,
            source_text=record.raw_text,
            tier=tier,
            candidates=top,
            # Green means auto-accept: the top candidate is selected.
            # Yellow and red wait for a human decision.
            selected_catalog_id=top[0].catalog_id if tier is Tier.green else None,
            review=None,
            matched_at=datetime.now(timezone.utc),
        )
        self._persist(result)
        return result

    def match_all(self) -> list[MatchResult]:
        """Match every ingested record that has no persisted match yet.

        Existing matches are returned as-is (not recomputed) so review
        decisions survive application restarts."""
        existing = {
            row["record_id"]: row["payload"]
            for row in self._conn.execute(
                "SELECT record_id, payload FROM matches"
            ).fetchall()
        }
        results: list[MatchResult] = []
        for row in self._conn.execute(
            "SELECT record_id, raw_text, category, unit, quantity, ingested_at"
            " FROM records ORDER BY id"
        ).fetchall():
            record = RecordOut(**dict(row))
            if record.record_id in existing:
                results.append(
                    MatchResult.model_validate_json(existing[record.record_id])
                )
            else:
                results.append(self.match_record(record))
        return results

    def _persist(self, result: MatchResult) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO matches (record_id, payload, tier, matched_at)"
            " VALUES (?, ?, ?, ?)",
            (
                result.record_id,
                result.model_dump_json(),
                result.tier.value,
                result.matched_at.isoformat(),
            ),
        )
        self._conn.commit()


def run_matching(conn: sqlite3.Connection | None = None) -> list[MatchResult]:
    """Match all ingested records. Runs at startup after ingest; safe to
    re-run (already-matched records are left untouched)."""
    owned = conn is None
    if conn is None:
        conn = get_conn()
    try:
        results = LexicalMatchingEngine(conn).match_all()
        counts = {tier.value: 0 for tier in Tier}
        for result in results:
            counts[result.tier.value] += 1
        log_event(
            logger,
            logging.INFO,
            "matching_completed",
            matched=len(results),
            **counts,
        )
        return results
    finally:
        if owned:
            conn.close()
