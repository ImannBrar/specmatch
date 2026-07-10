"""Read and update persisted match results (Task 4).

The matches table stores each record's MatchResult as a JSON payload.
This module lists them (with tier filter and paging) and applies human
review decisions. A review never changes the machine-assigned tier: the
tier is the engine's receipt of how confident it was, and keeping it
intact means future engine versions can be measured against what humans
actually decided.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from app.core.db import get_conn
from app.core.errors import InvalidReviewError, MatchNotFoundError
from app.core.logging import log_event
from app.models.schemas import (
    MatchesResponse,
    MatchResult,
    Review,
    ReviewAction,
    ReviewRequest,
    Tier,
)

logger = logging.getLogger(__name__)


def list_matches(
    tier: Tier | None = None, limit: int = 50, offset: int = 0
) -> MatchesResponse:
    conn = get_conn()
    try:
        if tier is not None:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM matches WHERE tier = ?", (tier.value,)
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT payload FROM matches WHERE tier = ?"
                " ORDER BY record_id LIMIT ? OFFSET ?",
                (tier.value, limit, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) AS n FROM matches").fetchone()["n"]
            rows = conn.execute(
                "SELECT payload FROM matches ORDER BY record_id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
    finally:
        conn.close()
    items = [MatchResult.model_validate_json(row["payload"]) for row in rows]
    return MatchesResponse(total=total, items=items)


def get_match(record_id: str, conn: sqlite3.Connection) -> MatchResult:
    row = conn.execute(
        "SELECT payload FROM matches WHERE record_id = ?", (record_id,)
    ).fetchone()
    if row is None:
        raise MatchNotFoundError(f"no match for record {record_id}")
    return MatchResult.model_validate_json(row["payload"])


def apply_review(record_id: str, request: ReviewRequest) -> MatchResult:
    conn = get_conn()
    try:
        result = get_match(record_id, conn)
        selected, review_catalog_id = _resolve_selection(result, request, conn)
        review = Review(
            action=request.action,
            catalog_id=review_catalog_id,
            note=request.note,
            reviewed_at=datetime.now(timezone.utc),
        )
        updated = result.model_copy(
            update={"selected_catalog_id": selected, "review": review}
        )
        # Only the payload changes: tier and matched_at stay the engine's.
        conn.execute(
            "UPDATE matches SET payload = ? WHERE record_id = ?",
            (updated.model_dump_json(), record_id),
        )
        conn.commit()
    finally:
        conn.close()
    log_event(
        logger,
        logging.INFO,
        "review_persisted",
        record_id=record_id,
        action=request.action.value,
        catalog_id=review_catalog_id,
    )
    return updated


def _resolve_selection(
    result: MatchResult, request: ReviewRequest, conn: sqlite3.Connection
) -> tuple[str | None, str | None]:
    """Work out what the review selects: (selected_catalog_id, the id the
    Review records for the audit trail)."""
    if request.action is ReviewAction.accept:
        if not result.candidates:
            raise InvalidReviewError("nothing to accept: no candidates")
        top = result.candidates[0].catalog_id
        return top, top
    if request.action is ReviewAction.override:
        if not request.catalog_id:
            raise InvalidReviewError("override requires a catalog_id")
        known = conn.execute(
            "SELECT 1 FROM catalog WHERE catalog_id = ?", (request.catalog_id,)
        ).fetchone()
        if known is None:
            raise InvalidReviewError(f"unknown catalog_id {request.catalog_id}")
        return request.catalog_id, request.catalog_id
    return None, None  # reject
