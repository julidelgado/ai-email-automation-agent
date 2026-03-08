def test_metrics_dashboard_page_serves_html(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Metrics Dashboard" in response.text


def test_metrics_api_returns_summary(client):
    response = client.get("/api/v1/metrics")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert "http" in payload
    assert "jobs" in payload
    assert "actions" in payload
    assert "alerts" in payload
