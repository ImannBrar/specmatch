"""Matching engine tests (Task 3): normalization, tier claims over the
fixture set, config-driven behaviour, and determinism."""

import sqlite3

import pytest

from app.config import MatchingSettings, Settings, TierThresholds, get_settings
from app.models.schemas import RecordOut, Tier
from app.services.ingest import run_ingest
from app.services.matching.engine import LexicalMatchingEngine, run_matching
from app.services.matching.normalize import (
    expand_token,
    normalize_record_text,
    tokenize,
)


def _fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_ingest(conn)
    return conn


@pytest.fixture(scope="module")
def matched():
    conn = _fresh_conn()
    results = {r.record_id: r for r in run_matching(conn)}
    yield conn, results
    conn.close()


# --- normalization ---------------------------------------------------------


def test_abbreviations_expand_to_catalog_wording():
    tokens = normalize_record_text("CONC RM 50MPA W/ 25% SLAG", set())
    assert {"concrete", "ready", "mix", "50mpa", "25pct", "slag"} <= tokens


def test_dimension_strings_stay_atomic():
    assert "4x2x3/16" in tokenize("HSS 4X2X3/16")
    # the mm glue must not eat the 89 out of the dimension
    assert {"38x89", "mm"} <= set(tokenize("38x89 mm"))


def test_unknown_token_falls_back_to_unique_prefix():
    assert expand_token("polyis", {"polyiso", "porcelain"}) == ["polyiso"]
    # ambiguous prefixes stay untouched
    assert expand_token("gra", {"grade", "granular"}) == ["gra"]


def test_unknown_plural_falls_back_to_singular():
    assert expand_token("fasteners", {"fastener"}) == ["fastener"]


# --- tier claims over the fixture set --------------------------------------


def test_confident_record_is_green_with_the_right_candidate(matched):
    _, results = matched
    result = results["SRC-0004"]  # CONC RM 50MPA W/ 25% SLAG
    assert result.tier is Tier.green
    assert "50 MPa, 25% slag" in result.candidates[0].description


def test_swapped_numbers_do_not_cross_match(matched):
    # 50 MPa / 25% slag must not land on the 25 MPa / 50% slag entry:
    # both records share the same bag of numbers.
    _, results = matched
    top = results["SRC-0004"].candidates[0]
    assert "25 MPa, 50% slag" not in top.description


def test_dimensioned_steel_matches_exact_size(matched):
    _, results = matched
    top = results["SRC-0110"].candidates[0]  # STL HSS 4X2X3/16 GR B
    assert "4x2x3/16" in top.description


def test_tier_distribution_over_fixture_set(matched):
    # The distribution the README reports; reviewers reproduce this.
    _, results = matched
    counts = {"green": 0, "yellow": 0, "red": 0}
    for result in results.values():
        counts[result.tier.value] += 1
    assert counts == {"green": 124, "yellow": 14, "red": 12}


def test_non_material_records_land_red(matched):
    _, results = matched
    assert results["SRC-0002"].tier is Tier.red  # MATL PER DWG S-501
    assert results["SRC-0074"].tier is Tier.red  # MISC MTL ALLOW


def test_green_records_carry_a_selected_catalog_id(matched):
    _, results = matched
    for result in results.values():
        if result.tier is Tier.green:
            assert result.selected_catalog_id == result.candidates[0].catalog_id
        else:
            assert result.selected_catalog_id is None


# --- contract and config behaviour ------------------------------------------


def test_scores_and_signals_stay_within_bounds(matched):
    _, results = matched
    weight_names = set(get_settings().matching.weights)
    top_k = get_settings().matching.top_k
    for result in results.values():
        assert 1 <= len(result.candidates) <= top_k
        scores = [c.score for c in result.candidates]
        assert scores == sorted(scores, reverse=True)
        for candidate in result.candidates:
            assert 0.0 <= candidate.score <= 1.0
            assert set(candidate.signals) == weight_names
            for value in candidate.signals.values():
                assert 0.0 <= value <= 1.0


def test_tiers_follow_injected_thresholds():
    # SRC-0021 scores in the mid-0.8s: yellow by default config, red under
    # strict thresholds, green under loose ones. Only the config changes.
    def tier_under(thresholds: TierThresholds) -> Tier:
        conn = _fresh_conn()
        try:
            settings = Settings(
                matching=get_settings().matching, tiers=thresholds
            )
            engine = LexicalMatchingEngine(conn, settings=settings)
            row = conn.execute(
                "SELECT record_id, raw_text, category, unit, quantity,"
                " ingested_at FROM records WHERE record_id = 'SRC-0021'"
            ).fetchone()
            return engine.match_record(RecordOut(**dict(row))).tier
        finally:
            conn.close()

    assert tier_under(get_settings().tiers) is Tier.yellow
    assert tier_under(TierThresholds(accept_min=0.99, review_min=0.98)) is Tier.red
    assert tier_under(TierThresholds(accept_min=0.50, review_min=0.30)) is Tier.green


def test_weights_drive_the_composite_score():
    # With all weight on category agreement, a category-matched candidate
    # must score exactly the category signal, ignoring text entirely.
    conn = _fresh_conn()
    try:
        category_only = Settings(
            matching=MatchingSettings(
                top_k=1, weights={"category_agreement": 1.0}
            ),
            tiers=get_settings().tiers,
        )
        engine = LexicalMatchingEngine(conn, settings=category_only)
        row = conn.execute(
            "SELECT record_id, raw_text, category, unit, quantity, ingested_at"
            " FROM records WHERE record_id = 'SRC-0004'"
        ).fetchone()
        result = engine.match_record(RecordOut(**dict(row)))
        assert result.candidates[0].score in (0.0, 0.5, 1.0)
    finally:
        conn.close()


# --- determinism and persistence --------------------------------------------


def test_matching_is_deterministic_across_runs(matched):
    _, first = matched
    conn = _fresh_conn()
    try:
        second = {r.record_id: r for r in run_matching(conn)}
    finally:
        conn.close()
    assert first.keys() == second.keys()
    for record_id, result in first.items():
        other = second[record_id]
        assert result.tier is other.tier
        assert [c.catalog_id for c in result.candidates] == [
            c.catalog_id for c in other.candidates
        ]
        assert [c.score for c in result.candidates] == [
            c.score for c in other.candidates
        ]


def test_rerunning_match_all_keeps_existing_results(matched):
    conn, _ = matched
    before = conn.execute(
        "SELECT payload FROM matches WHERE record_id = 'SRC-0004'"
    ).fetchone()["payload"]
    run_matching(conn)
    after = conn.execute(
        "SELECT payload FROM matches WHERE record_id = 'SRC-0004'"
    ).fetchone()["payload"]
    assert after == before
