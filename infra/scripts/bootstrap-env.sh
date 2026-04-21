#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

usage() {
  cat <<'EOF'
Usage: bootstrap-env.sh --env <dev|prod> --subscription <subscription-id> --resource-group <resource-group>

Checks local deployment prerequisites for LeagueBrief on macOS:
- required CLIs
- Azure login and subscription access
- target resource group access
- Azure Bicep availability
- Azure provider registration status

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

require_commands az jq zip python3.13 node npm npx func
ensure_azure_context
ensure_bicep_available

providers=(
  Microsoft.App
  Microsoft.Cdn
  Microsoft.Insights
  Microsoft.KeyVault
  Microsoft.Network
  Microsoft.OperationalInsights
  Microsoft.Sql
  Microsoft.Storage
  Microsoft.Web
)

log "Using subscription ${AZ_SUBSCRIPTION_ID} and resource group ${RESOURCE_GROUP}."

for provider in "${providers[@]}"; do
  registration_state="$(
    az provider show \
      --subscription "$AZ_SUBSCRIPTION_ID" \
      --namespace "$provider" \
      --query registrationState \
      --output tsv
  )"

  if [[ "$registration_state" != "Registered" ]]; then
    warn "Provider ${provider} is ${registration_state}. Register it before deploying infra."
  fi
done

log "Environment bootstrap checks completed successfully."
