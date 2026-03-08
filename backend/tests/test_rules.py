from __future__ import annotations


def test_rules_list_endpoint_bootstraps_defaults(client):
    response = client.get("/api/v1/rules")
    payload = response.json()

    intents = {item["intent"] for item in payload["items"]}

    assert response.status_code == 200
    assert payload["count"] >= 4
    assert {"invoice", "meeting", "request", "other"}.issubset(intents)


def test_rules_patch_updates_threshold_and_approval(client):
    list_response = client.get("/api/v1/rules")
    rules = list_response.json()["items"]
    invoice_rule = next(item for item in rules if item["intent"] == "invoice")

    response = client.patch(
        f"/api/v1/rules/{invoice_rule['id']}",
        json={"min_confidence": 0.82, "requires_approval": False, "is_active": True},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["rule"]["min_confidence"] == 0.82
    assert payload["rule"]["requires_approval"] is False
    assert payload["rule"]["is_active"] is True


def test_rules_bulk_patch_updates_multiple_rules(client):
    list_response = client.get("/api/v1/rules")
    rules = list_response.json()["items"]
    invoice_rule = next(item for item in rules if item["intent"] == "invoice")
    request_rule = next(item for item in rules if item["intent"] == "request")

    response = client.patch(
        "/api/v1/rules/bulk",
        json={
            "rules": [
                {
                    "id": invoice_rule["id"],
                    "min_confidence": 0.9,
                    "requires_approval": False,
                    "is_active": True,
                },
                {
                    "id": request_rule["id"],
                    "min_confidence": 0.7,
                    "requires_approval": True,
                    "is_active": False,
                },
            ]
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["updated_count"] == 2
    updated_by_intent = {item["intent"]: item for item in payload["rules"]}
    assert updated_by_intent["invoice"]["min_confidence"] == 0.9
    assert updated_by_intent["invoice"]["requires_approval"] is False
    assert updated_by_intent["request"]["min_confidence"] == 0.7
    assert updated_by_intent["request"]["is_active"] is False
