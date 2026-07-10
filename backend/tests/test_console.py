import re


def test_record_table_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SRC-" in resp.text


def test_category_filter_narrows_results(client):
    resp = client.get("/", params={"category": "Concrete"})
    assert resp.status_code == 200
    assert "CONC" in resp.text
    assert "GYP BD" not in resp.text


def test_review_panel_defaults_to_yellow_queue(client):
    resp = client.get("/review")
    assert resp.status_code == 200
    assert "yellow 14" in resp.text
    assert "SRC-0021" in resp.text  # a yellow record
    assert "SRC-0002" not in resp.text  # red stays out of the yellow queue


def test_review_panel_filters_by_tier(client):
    resp = client.get("/review", params={"tier": "red"})
    assert resp.status_code == 200
    assert "SRC-0002" in resp.text
    assert "SRC-0021" not in resp.text


def test_console_review_action_persists(client):
    resp = client.post(
        "/review/SRC-0034",
        data={"action": "accept", "tier": "yellow"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/review?tier=yellow"
    page = client.get("/review", params={"tier": "yellow"})
    assert "reviewed: accept" in page.text


def test_console_review_rejects_bad_action(client):
    resp = client.post("/review/SRC-0034", data={"action": "explode"})
    assert resp.status_code == 422


def test_switching_back_to_all_categories_shows_all_records(client):
    """Issue #3: submitting the value carried by the "All categories"
    option must show every record, not an empty table."""
    page = client.get("/").text
    match = re.search(
        r'<option value="([^"]*)"[^>]*>All categories</option>', page
    )
    assert match is not None
    resp = client.get("/", params={"category": match.group(1)})
    assert resp.status_code == 200
    assert "SRC-" in resp.text
    assert "No records." not in resp.text
