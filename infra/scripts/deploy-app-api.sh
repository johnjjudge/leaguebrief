#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

usage() {
  cat <<'EOF'
Usage: deploy-app-api.sh --env <dev|prod> --subscription <subscription-id> --resource-group <resource-group> [--skip-package]

Packages and deploys the LeagueBrief API Function App.

Environment variable fallbacks:
- LB_ENV
- LB_SUBSCRIPTION_ID
- LB_RESOURCE_GROUP
EOF
}

parse_common_args "$@"

if [[ "$SHOW_HELP" -eq 1 ]]; then
  usage
  exit 0
fi

require_commands az jq func
ensure_azure_context

if [[ "$SKIP_PACKAGE" -eq 0 ]]; then
  "${SCRIPT_DIR}/package-api.sh" --env "$ENVIRONMENT"
fi

package_dir="$(function_package_dir "api")"
require_directory "$package_dir" "API package directory"

outputs_json="$(deployment_outputs_json)"
api_function_app_name="$(extract_output_value "$outputs_json" "apiFunctionAppName")"

log "Publishing API package to ${api_function_app_name}."

(
  cd "$package_dir"
  func azure functionapp publish "$api_function_app_name" --python
)

log "API deployment completed."
