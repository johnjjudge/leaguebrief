#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ARTIFACTS_ROOT="${REPO_ROOT}/infra/.artifacts"

SHOW_HELP=0
SKIP_PACKAGE=0
ENVIRONMENT="${LB_ENV:-}"
AZ_SUBSCRIPTION_ID="${LB_SUBSCRIPTION_ID:-}"
RESOURCE_GROUP="${LB_RESOURCE_GROUP:-}"
POSITIONAL_ARGS=()

log() {
  printf '[%s] %s\n' "$(basename "$0")" "$*"
}

warn() {
  printf '[%s] WARNING: %s\n' "$(basename "$0")" "$*" >&2
}

fail() {
  printf '[%s] ERROR: %s\n' "$(basename "$0")" "$*" >&2
  exit 1
}

reset_common_args() {
  SHOW_HELP=0
  SKIP_PACKAGE=0
  ENVIRONMENT="${LB_ENV:-}"
  AZ_SUBSCRIPTION_ID="${LB_SUBSCRIPTION_ID:-}"
  RESOURCE_GROUP="${LB_RESOURCE_GROUP:-}"
  POSITIONAL_ARGS=()
}

parse_common_args() {
  reset_common_args

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --env)
        [[ $# -ge 2 ]] || fail "Missing value for --env."
        ENVIRONMENT="$2"
        shift 2
        ;;
      --subscription)
        [[ $# -ge 2 ]] || fail "Missing value for --subscription."
        AZ_SUBSCRIPTION_ID="$2"
        shift 2
        ;;
      --resource-group)
        [[ $# -ge 2 ]] || fail "Missing value for --resource-group."
        RESOURCE_GROUP="$2"
        shift 2
        ;;
      --skip-package)
        SKIP_PACKAGE=1
        shift
        ;;
      -h|--help)
        SHOW_HELP=1
        shift
        ;;
      --)
        shift
        while [[ $# -gt 0 ]]; do
          POSITIONAL_ARGS+=("$1")
          shift
        done
        ;;
      *)
        POSITIONAL_ARGS+=("$1")
        shift
        ;;
    esac
  done
}

require_command() {
  local command_name="$1"

  command -v "$command_name" >/dev/null 2>&1 || fail "Required command not found: $command_name"
}

require_commands() {
  local command_name
  for command_name in "$@"; do
    require_command "$command_name"
  done
}

require_directory() {
  local path="$1"
  local label="${2:-Directory}"

  [[ -d "$path" ]] || fail "$label not found: $path"
}

require_file() {
  local path="$1"
  local label="${2:-File}"

  [[ -f "$path" ]] || fail "$label not found: $path"
}

require_value() {
  local value="$1"
  local label="$2"

  [[ -n "$value" ]] || fail "$label is required."
}

require_environment_name() {
  require_value "$ENVIRONMENT" "--env or LB_ENV"

  case "$ENVIRONMENT" in
    dev|prod)
      ;;
    *)
      fail "Unsupported environment '$ENVIRONMENT'. Use dev or prod."
      ;;
  esac
}

require_azure_target() {
  require_environment_name
  require_value "$AZ_SUBSCRIPTION_ID" "--subscription or LB_SUBSCRIPTION_ID"
  require_value "$RESOURCE_GROUP" "--resource-group or LB_RESOURCE_GROUP"
}

ensure_azure_context() {
  require_command az
  require_azure_target

  az account show >/dev/null 2>&1 || fail "Azure CLI is not logged in. Run 'az login' first."
  az account set --subscription "$AZ_SUBSCRIPTION_ID" >/dev/null
  az group show --subscription "$AZ_SUBSCRIPTION_ID" --name "$RESOURCE_GROUP" >/dev/null
}

ensure_bicep_available() {
  require_command az
  az bicep version >/dev/null
}

deployment_name() {
  printf 'leaguebrief-%s-infra\n' "$ENVIRONMENT"
}

deployment_outputs_json() {
  az deployment group show \
    --subscription "$AZ_SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --name "$(deployment_name)" \
    --query properties.outputs \
    --output json
}

extract_output_value() {
  local outputs_json="$1"
  local output_name="$2"

  printf '%s' "$outputs_json" | jq -er --arg output_name "$output_name" '.[$output_name].value'
}

function_artifact_root() {
  local component="$1"

  printf '%s/%s/%s\n' "$ARTIFACTS_ROOT" "$ENVIRONMENT" "$component"
}

function_package_dir() {
  local component="$1"

  printf '%s/package\n' "$(function_artifact_root "$component")"
}

function_zip_path() {
  local component="$1"

  printf '%s/%s.zip\n' "$(function_artifact_root "$component")" "$component"
}

ensure_python_sources_exist() {
  local source_dir="$1"

  find "$source_dir" -type f -name '*.py' -print -quit | grep -q . || fail "No Python source files found under $source_dir."
}

clean_package_dir() {
  local package_dir="$1"

  find "$package_dir" -type d \( \
    -name '.venv' -o \
    -name '__pycache__' -o \
    -name '.pytest_cache' -o \
    -name '.mypy_cache' -o \
    -name '.ruff_cache' -o \
    -name 'node_modules' \
  \) -prune -exec rm -rf {} +

  find "$package_dir" -type f \( \
    -name '.DS_Store' -o \
    -name '.gitkeep' \
  \) -delete
}

package_python_function_app() {
  local component="$1"
  local source_dir="$2"
  local artifact_root
  local package_dir
  local zip_path
  local venv_dir

  require_environment_name
  require_command python3
  require_command zip
  require_directory "$source_dir" "Source directory"
  require_file "$source_dir/host.json" "Azure Functions host.json"
  require_file "$source_dir/requirements.txt" "Python requirements file"
  ensure_python_sources_exist "$source_dir"

  artifact_root="$(function_artifact_root "$component")"
  package_dir="$(function_package_dir "$component")"
  zip_path="$(function_zip_path "$component")"
  venv_dir="${artifact_root}/.venv"

  rm -rf "$artifact_root"
  mkdir -p "$package_dir"

  cp -R "$source_dir"/. "$package_dir"
  clean_package_dir "$package_dir"

  python3 -m venv "$venv_dir"
  "$venv_dir/bin/pip" install --upgrade pip >/dev/null

  if [[ -s "$source_dir/requirements.txt" ]]; then
    mkdir -p "$package_dir/.python_packages/lib/site-packages"
    "$venv_dir/bin/pip" install \
      --requirement "$source_dir/requirements.txt" \
      --target "$package_dir/.python_packages/lib/site-packages"
  fi

  rm -f "$zip_path"
  (
    cd "$package_dir"
    zip -qr "$zip_path" .
  )

  log "Created ${component} package at $zip_path"
}
