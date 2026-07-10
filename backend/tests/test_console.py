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
