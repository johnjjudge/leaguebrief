#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

usage() {
  cat <<'EOF'
Usage: deploy-app-web.sh --env <dev|prod> --subscription <subscription-id> --resource-group <resource-group>

Builds and deploys the LeagueBrief frontend to Azure Static Web Apps.

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

require_commands az jq node npm npx
ensure_azure_context

web_dir="${REPO_ROOT}/apps/web"
require_directory "$web_dir" "Web app directory"
require_file "${web_dir}/package.json" "Web app package.json"

log "Installing web dependencies."
(
  cd "$web_dir"
  npm ci
  npm run build
)

build_dir=""
if [[ -d "${web_dir}/dist" ]]; then
  build_dir="${web_dir}/dist"
elif [[ -d "${web_dir}/build" ]]; then
  build_dir="${web_dir}/build"
else
  fail "Web build output not found. Expected ${web_dir}/dist or ${web_dir}/build."
fi

outputs_json="$(deployment_outputs_json)"
static_web_app_name="$(extract_output_value "$outputs_json" "staticWebAppName")"
deployment_token="$(
  az staticwebapp secrets list \
    --subscription "$AZ_SUBSCRIPTION_ID" \
    --name "$static_web_app_name" \
    --query properties.apiKey \
    --output tsv
)"

require_value "$deployment_token" "Static Web App deployment token"

log "Deploying web build from ${build_dir} to ${static_web_app_name}."
npx --yes @azure/static-web-apps-cli@latest deploy "$build_dir" --deployment-token "$deployment_token" --env production

log "Web deployment completed."
