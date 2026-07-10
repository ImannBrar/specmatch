"""Server-rendered review console (Jinja2).

The record table is implemented. The review panel is stubbed — completing
it is Task 5.
"""

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.db import get_conn
from app.core.errors import InvalidReviewError, MatchNotFoundError
from app.models.schemas import ReviewAction, ReviewRequest, Tier
from app.services import match_store

router = APIRouter()

templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")


@router.get("/", response_class=HTMLResponse)
def record_table(request: Request, category: str | None = Query(default=None)):
    # An empty value means "All categories" (no filter), not a category name.
    category = category or None
    conn = get_conn()
    try:
        categories = [
            row["category"]
            for row in conn.execute(
                "SELECT DISTINCT category FROM records"
                " WHERE category IS NOT NULL AND category != '' ORDER BY category"
            ).fetchall()
        ]
        if category is not None:
            rows = conn.execute(
                "SELECT record_id, raw_text, category, unit, quantity FROM records"
                " WHERE category = ? ORDER BY id",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT record_id, raw_text, category, unit, quantity FROM records"
                " ORDER BY id"
            ).fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "records.html",
        {
            "records": rows,
            "categories": categories,
            "selected_category": category,
        },
    )


@router.get("/review", response_class=HTMLResponse)
def review_panel(request: Request, tier: str | None = Query(default=None)):
    selected_tier = tier if tier in ("green", "yellow", "red", "all") else "yellow"
    conn = get_conn()
    try:
        tier_counts = {t.value: 0 for t in Tier}
        for row in conn.execute(
            "SELECT tier, COUNT(*) AS n FROM matches GROUP BY tier"
        ).fetchall():
            tier_counts[row["tier"]] = row["n"]
    finally:
        conn.close()
    queue_tier = None if selected_tier == "all" else Tier(selected_tier)
    matches = match_store.list_matches(tier=queue_tier, limit=500).items
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "matches": matches,
            "tier_counts": tier_counts,
            "selected_tier": selected_tier,
        },
    )


@router.post("/review/{record_id}", response_class=HTMLResponse)
def submit_review(
    record_id: str,
    action: str = Form(),
    catalog_id: str | None = Form(default=None),
    tier: str = Form(default="yellow"),
):
    try:
        request_body = ReviewRequest(
            action=ReviewAction(action), catalog_id=catalog_id or None
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        match_store.apply_review(record_id, request_body)
    except MatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(url=f"/review?tier={tier}", status_code=303)
