#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

usage() {
  cat <<'EOF'
Usage: deploy-infra.sh --env <dev|prod> --subscription <subscription-id> --resource-group <resource-group>

Deploys the LeagueBrief Azure infrastructure directly from Bicep.

Required environment variables:
- LB_SQL_ADMIN_PASSWORD

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

require_commands az
ensure_azure_context
ensure_bicep_available
require_value "${LB_SQL_ADMIN_PASSWORD:-}" "LB_SQL_ADMIN_PASSWORD"

template_file="${REPO_ROOT}/infra/bicep/main.bicep"
parameter_file="${REPO_ROOT}/infra/bicep/parameters/${ENVIRONMENT}.bicepparam"

require_file "$template_file" "Bicep template"
require_file "$parameter_file" "Bicep parameter file"

log "Deploying infrastructure with deployment name $(deployment_name)."

az deployment group create \
  --subscription "$AZ_SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$(deployment_name)" \
  --template-file "$template_file" \
  --parameters "$parameter_file" \
  --parameters sqlAdministratorPassword="$LB_SQL_ADMIN_PASSWORD"

log "Infrastructure deployment completed."
