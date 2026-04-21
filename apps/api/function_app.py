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
from leaguebrief.db.users import SqlUserRepository

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


def _json_response(payload: dict[str, Any], status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(payload),
        mimetype="application/json",
        status_code=status_code,
    )
