#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

usage() {
  cat <<'EOF'
Usage: package-api.sh --env <dev|prod>

Builds a clean local deployment package for the LeagueBrief API Function App.

Environment variable fallbacks:
- LB_ENV
EOF
}

parse_common_args "$@"

if [[ "$SHOW_HELP" -eq 1 ]]; then
  usage
  exit 0
fi

source_dir="${REPO_ROOT}/apps/api"
package_python_function_app "api" "$source_dir"
