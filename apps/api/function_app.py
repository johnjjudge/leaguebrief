import json
import os
from typing import Any

import azure.functions as func

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
