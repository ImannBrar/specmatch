from app.config import TierThresholds
from app.models.schemas import Tier
from app.services.matching.tiering import assign_tier

THRESHOLDS = TierThresholds(accept_min=0.85, review_min=0.60)


def test_high_score_is_green():
    assert assign_tier(0.95, THRESHOLDS) is Tier.green


def test_mid_score_is_yellow():
    assert assign_tier(0.70, THRESHOLDS) is Tier.yellow


def test_low_score_is_red():
    assert assign_tier(0.30, THRESHOLDS) is Tier.red


def test_score_at_accept_boundary_is_green():
    """Issue #2: accept_min is an inclusive lower bound, so a score of
    exactly accept_min belongs in green, not yellow."""
    assert assign_tier(0.85, THRESHOLDS) is Tier.green


def test_score_at_review_boundary_is_yellow():
    """review_min is likewise inclusive: exactly review_min is yellow."""
    assert assign_tier(0.60, THRESHOLDS) is Tier.yellow
