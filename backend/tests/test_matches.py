"""Contract tests for the match endpoints (Task 4). Each test uses its
own record so the session-scoped client's state stays untangled."""


def test_list_matches_shape(client):
    body = client.get("/matches").json()
    assert body["total"] == 150
    assert len(body["items"]) == 50  # default limit
    item = body["items"][0]
    assert set(item) == {
        "record_id",
        "source_text",
        "tier",
        "candidates",
        "selected_catalog_id",
        "review",
        "matched_at",
    }
    candidate = item["candidates"][0]
    assert set(candidate) == {"catalog_id", "description", "score", "signals"}


def test_list_matches_filters_by_tier(client):
    body = client.get("/matches", params={"tier": "yellow", "limit": 500}).json()
    assert body["total"] == 14
    assert len(body["items"]) == 14
    assert all(item["tier"] == "yellow" for item in body["items"])


def test_list_matches_pages_with_limit_and_offset(client):
    first = client.get("/matches", params={"limit": 10, "offset": 0}).json()
    second = client.get("/matches", params={"limit": 10, "offset": 10}).json()
    assert first["total"] == second["total"] == 150
    first_ids = [item["record_id"] for item in first["items"]]
    second_ids = [item["record_id"] for item in second["items"]]
    assert len(first_ids) == len(second_ids) == 10
    assert not set(first_ids) & set(second_ids)


def test_review_accept_persists_and_keeps_tier(client):
    before = client.post(
        "/matches/SRC-0021/review", json={"action": "accept", "note": "looks right"}
    )
    assert before.status_code == 200
    body = before.json()
    assert body["tier"] == "yellow"  # the machine's tier is the receipt
    assert body["review"]["action"] == "accept"
    assert body["review"]["note"] == "looks right"
    assert body["selected_catalog_id"] == body["candidates"][0]["catalog_id"]
    # persisted: it comes back with the review on a fresh read
    match = next(
        item
        for item in client.get(
            "/matches", params={"tier": "yellow", "limit": 500}
        ).json()["items"]
        if item["record_id"] == "SRC-0021"
    )
    assert match["review"]["action"] == "accept"


def test_review_override_selects_the_given_entry(client):
    candidates = next(
        item
        for item in client.get("/matches", params={"limit": 500}).json()["items"]
        if item["record_id"] == "SRC-0020"
    )["candidates"]
    alternative = candidates[1]["catalog_id"]
    resp = client.post(
        "/matches/SRC-0020/review",
        json={"action": "override", "catalog_id": alternative},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_catalog_id"] == alternative
    assert body["review"]["catalog_id"] == alternative
    assert body["tier"] == "yellow"


def test_review_override_requires_a_known_catalog_id(client):
    missing = client.post("/matches/SRC-0037/review", json={"action": "override"})
    assert missing.status_code == 422
    unknown = client.post(
        "/matches/SRC-0037/review",
        json={"action": "override", "catalog_id": "CAT-DOES-NOT-EXIST"},
    )
    assert unknown.status_code == 422


def test_review_reject_clears_selection(client):
    resp = client.post("/matches/SRC-0002/review", json={"action": "reject"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_catalog_id"] is None
    assert body["review"]["action"] == "reject"
    assert body["tier"] == "red"


def test_review_unknown_record_is_404(client):
    resp = client.post("/matches/SRC-9999/review", json={"action": "accept"})
    assert resp.status_code == 404
