import json
import os
from typing import Any

import azure.functions as func
from leaguebrief.auth import (
    AuthConflictError,
    AuthenticationError,
    UserDisabledError,
    authenticate_current_user,
)
from leaguebrief.db.leagues import SqlLeagueRepository
from leaguebrief.db.users import SqlUserRepository
from leaguebrief.leagues import (
    LeagueAccessDeniedError,
    LeagueAttachMismatchError,
    LeagueNotFoundError,
    LeagueService,
    LeagueValidationError,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def build_health_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "leaguebrief-api",
        "role": os.getenv("FUNCTION_APP_ROLE", os.getenv("APP_KIND", "api")),
        "environment": os.getenv("LEAGUEBRIEF_ENVIRONMENT", "local"),
    }


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(build_health_payload()),
        mimetype="application/json",
        status_code=200,
    )


def get_user_repository() -> SqlUserRepository:
    return SqlUserRepository()


def get_league_repository() -> SqlLeagueRepository:
    return SqlLeagueRepository()


@app.route(route="me", methods=["GET"])
def me(req: func.HttpRequest) -> func.HttpResponse:
    try:
        payload = authenticate_current_user(req.headers, get_user_repository())
        return _json_response(payload, 200)
    except AuthenticationError as exc:
        return _json_response({"error": "unauthorized", "message": str(exc)}, 401)
    except UserDisabledError:
        return _json_response(
            {"error": "forbidden", "message": "User is disabled."},
            403,
        )
    except AuthConflictError as exc:
        return _json_response({"error": "conflict", "message": str(exc)}, 409)


@app.route(route="leagues", methods=["POST"])
def create_league(req: func.HttpRequest) -> func.HttpResponse:
    try:
        current_user = _authenticate_current_user(req)
        payload = _read_json_object(req)
        result = LeagueService(get_league_repository()).create_or_attach_league(
            current_user["id"],
            payload,
        )
        status_code = (
            201
            if result["canonicalLeagueCreated"] or result["userLeagueCreated"]
            else 200
        )
        return _json_response(result, status_code)
    except (
        AuthenticationError,
        UserDisabledError,
        AuthConflictError,
        LeagueValidationError,
    ) as exc:
        return _error_response(exc)


@app.route(route="leagues", methods=["GET"])
def list_leagues(req: func.HttpRequest) -> func.HttpResponse:
    try:
        current_user = _authenticate_current_user(req)
        payload = LeagueService(get_league_repository()).list_user_leagues(
            current_user["id"]
        )
        return _json_response(payload, 200)
    except (AuthenticationError, UserDisabledError, AuthConflictError) as exc:
        return _error_response(exc)


@app.route(route="leagues/{leagueId}", methods=["GET"])
def get_league(req: func.HttpRequest) -> func.HttpResponse:
    try:
        current_user = _authenticate_current_user(req)
        league_id = _route_param(req, "leagueId")
        payload = LeagueService(get_league_repository()).get_authorized_league(
            current_user["id"],
            league_id,
        )
        return _json_response(payload, 200)
    except (
        AuthenticationError,
        UserDisabledError,
        AuthConflictError,
        LeagueValidationError,
        LeagueNotFoundError,
        LeagueAccessDeniedError,
    ) as exc:
        return _error_response(exc)


@app.route(route="leagues/{leagueId}/attach", methods=["POST"])
def attach_league(req: func.HttpRequest) -> func.HttpResponse:
    try:
        current_user = _authenticate_current_user(req)
        league_id = _route_param(req, "leagueId")
        payload = _read_json_object(req)
        result = LeagueService(get_league_repository()).attach_to_league(
            current_user["id"],
            league_id,
            payload,
        )
        return _json_response(result, 201 if result["userLeagueCreated"] else 200)
    except (
        AuthenticationError,
        UserDisabledError,
        AuthConflictError,
        LeagueValidationError,
        LeagueNotFoundError,
        LeagueAccessDeniedError,
        LeagueAttachMismatchError,
    ) as exc:
        return _error_response(exc)


def _json_response(payload: dict[str, Any], status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(payload),
        mimetype="application/json",
        status_code=status_code,
    )


def _authenticate_current_user(req: func.HttpRequest) -> dict[str, Any]:
    payload = authenticate_current_user(req.headers, get_user_repository())
    user = payload["user"]
    if not isinstance(user, dict) or not isinstance(user.get("id"), str):
        raise AuthenticationError("Authenticated user payload is invalid.")
    return user


def _read_json_object(req: func.HttpRequest) -> dict[str, object]:
    try:
        payload = req.get_json()
    except ValueError as exc:
        raise LeagueValidationError("Request body must be valid JSON.") from exc

    if not isinstance(payload, dict):
        raise LeagueValidationError("Request body must be a JSON object.")
    return payload


def _route_param(req: func.HttpRequest, name: str) -> str:
    route_params = getattr(req, "route_params", None)
    if hasattr(route_params, "get"):
        value = route_params.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise LeagueValidationError(f"Missing route parameter: {name}.")


def _error_response(exc: Exception) -> func.HttpResponse:
    if isinstance(exc, AuthenticationError):
        return _json_response({"error": "unauthorized", "message": str(exc)}, 401)
    if isinstance(exc, UserDisabledError):
        return _json_response(
            {"error": "forbidden", "message": "User is disabled."},
            403,
        )
    if isinstance(exc, AuthConflictError):
        return _json_response({"error": "conflict", "message": str(exc)}, 409)
    if isinstance(exc, LeagueValidationError):
        return _json_response({"error": "bad_request", "message": str(exc)}, 400)
    if isinstance(exc, LeagueNotFoundError):
        return _json_response({"error": "not_found", "message": str(exc)}, 404)
    if isinstance(exc, (LeagueAccessDeniedError, LeagueAttachMismatchError)):
        return _json_response({"error": "forbidden", "message": str(exc)}, 403)
    return _json_response(
        {"error": "internal_server_error", "message": "Unexpected server error."},
        500,
    )
