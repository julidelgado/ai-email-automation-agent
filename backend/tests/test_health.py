def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["environment"] == "test"


def test_readiness_endpoint(client):
    response = client.get("/api/v1/ready")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"]["database"] == "ok"
