def test_health_shape(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["records"] == 150
    # Matching runs at startup (Task 3), so every record is matched.
    assert body["matched"] == 150
    assert sum(body["tiers"].values()) == 150
