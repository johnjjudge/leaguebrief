import json

from function_app import build_health_payload, health


class _Request:
    pass


def test_build_health_payload_defaults(monkeypatch):
    monkeypatch.delenv("APP_KIND", raising=False)
    monkeypatch.delenv("FUNCTION_APP_ROLE", raising=False)
    monkeypatch.delenv("LEAGUEBRIEF_ENVIRONMENT", raising=False)

    assert build_health_payload() == {
        "status": "ok",
        "service": "leaguebrief-api",
        "role": "api",
        "environment": "local",
    }


def test_health_returns_json_response(monkeypatch):
    monkeypatch.setenv("FUNCTION_APP_ROLE", "api")
    monkeypatch.setenv("LEAGUEBRIEF_ENVIRONMENT", "test")

    response = health(_Request())

    assert response.status_code == 200
    assert json.loads(response.get_body()) == {
        "status": "ok",
        "service": "leaguebrief-api",
        "role": "api",
        "environment": "test",
    }
