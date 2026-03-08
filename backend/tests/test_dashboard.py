def test_dashboard_page_serves_html(client):
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Action Review Dashboard" in response.text
    assert "Google Calendar Integration" in response.text
    assert "Rules" in response.text
    assert "Save All Changes" in response.text
    assert "Tasks" in response.text
    assert "Audit Timeline" in response.text
