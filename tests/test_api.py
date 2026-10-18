"""REST endpoint tests using Flask's test client."""


def test_dashboard_page_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"SIMULATION MODE" in res.data


def test_status_endpoint(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["mode"] == "SIMULATION"
    assert data["total_sorted"] == 0
    assert data["counts"] == {"WET": 0, "DRY": 0, "METAL": 0}
    assert data["mqtt"]["enabled"] is False
    assert data["hardware"]["physical_hardware_tested"] is False
    assert set(data["fill_levels"]) == {"wet", "dry", "metal"}


def test_simulate_each_type(client):
    for kind, expected in [("wet", "WET"), ("dry", "DRY"), ("metal", "METAL")]:
        res = client.post("/api/simulate", json={"type": kind})
        assert res.status_code == 201
        assert res.get_json()["classification"] == expected

    res = client.post("/api/simulate", json={"type": "none"})
    assert res.status_code == 200
    assert res.get_json()["sorted"] is False

    status = client.get("/api/status").get_json()
    assert status["total_sorted"] == 3
    assert status["no_item_readings"] == 1


def test_simulate_custom_reading(client):
    res = client.post("/api/simulate", json={"reading": {"ir": True, "moisture": 99, "metal": True}})
    assert res.status_code == 201
    assert res.get_json()["classification"] == "METAL"


def test_simulate_validation_errors(client):
    res = client.post("/api/simulate", json={"type": "glass"})
    assert res.status_code == 400
    assert "type" in res.get_json()["error"]

    res = client.post("/api/simulate", json={"reading": {"ir": True, "moisture": 120, "metal": False}})
    assert res.status_code == 400
    body = res.get_json()
    assert body["error"] == "invalid sensor reading"
    assert any("between 0 and 100" in d for d in body["details"])

    res = client.post("/api/simulate", data="not json", content_type="application/json")
    assert res.status_code == 400

    res = client.post("/api/simulate", json={})
    assert res.status_code == 400


def test_events_endpoint_returns_latest_first(client):
    client.post("/api/simulate", json={"type": "wet"})
    client.post("/api/simulate", json={"type": "metal"})
    events = client.get("/api/events").get_json()["events"]
    assert [e["category"] for e in events] == ["METAL", "WET"]
    assert {"timestamp", "moisture", "servo_action", "servo_angle", "source"} <= set(events[0])

    assert len(client.get("/api/events?limit=1").get_json()["events"]) == 1
    assert client.get("/api/events?limit=abc").status_code == 400
    assert client.get("/api/events?limit=0").status_code == 400


def test_fill_levels_endpoint(client):
    client.post("/api/simulate", json={"type": "dry"})
    data = client.get("/api/fill-levels").get_json()
    assert data["current"]["dry"]["level"] == 5.0
    assert data["thresholds"]["high"] == 80.0
    assert data["history"][-1]["dry"] == 5.0


def test_alerts_endpoint_and_reset(client):
    for _ in range(16):
        client.post("/api/simulate", json={"type": "wet"})
    alerts = client.get("/api/alerts").get_json()
    assert len(alerts["active"]) == 1
    assert alerts["active"][0]["bin"] == "wet"

    res = client.post("/api/reset", json={})
    assert res.status_code == 200
    assert res.get_json()["alerts_resolved"] == 1
    alerts = client.get("/api/alerts").get_json()
    assert alerts["active"] == []
    assert alerts["history"][0]["active"] is False


def test_reset_invalid_bin(client):
    res = client.post("/api/reset", json={"bin": "plastic"})
    assert res.status_code == 400


def test_settings_endpoints(client):
    assert client.get("/api/settings").get_json()["settings"]["fill_high_threshold"] == 80.0

    res = client.put("/api/settings", json={"moisture_threshold": 30})
    assert res.status_code == 200
    assert res.get_json()["settings"]["moisture_threshold"] == 30

    res = client.post("/api/simulate", json={"reading": {"ir": True, "moisture": 40, "metal": False}})
    assert res.get_json()["classification"] == "WET"

    res = client.put("/api/settings", json={"fill_low_threshold": 95})
    assert res.status_code == 400
    assert "details" in res.get_json()


def test_unknown_api_route_returns_json_404(client):
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert res.get_json()["error"] == "endpoint not found"
    assert client.get("/api/simulate").status_code == 405
