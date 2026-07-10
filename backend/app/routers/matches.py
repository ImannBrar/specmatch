"""Match endpoints (Task 4), to the frozen contracts in models/schemas.py.
Routers stay thin: the logic lives in services/match_store.py."""

from fastapi import APIRouter, HTTPException, Query

from app.core.errors import InvalidReviewError, MatchNotFoundError
from app.models.schemas import MatchesResponse, MatchResult, ReviewRequest, Tier
from app.services import match_store

router = APIRouter()


@router.get("/matches", response_model=MatchesResponse)
def list_matches(
    tier: Tier | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> MatchesResponse:
    return match_store.list_matches(tier=tier, limit=limit, offset=offset)


@router.post("/matches/{record_id}/review", response_model=MatchResult)
def review_match(record_id: str, body: ReviewRequest) -> MatchResult:
    try:
        return match_store.apply_review(record_id, body)
    except MatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
