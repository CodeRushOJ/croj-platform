#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command kubectl
require_command node
require_command npm

readonly cluster_name="${CODERUSHOJ_CLUSTER_NAME:-}"
readonly expected_context="kind-$cluster_name"
readonly state_root="$CODERUSHOJ_ROOT/.workspace/product-e2e/$cluster_name"
readonly secret_root="$state_root/secrets"
readonly browser_root="$CODERUSHOJ_ROOT/tests/e2e/browser"
readonly artifact_root="$CODERUSHOJ_ROOT/artifacts/product-e2e-browser"

[[ "$cluster_name" =~ ^croj-product-e2e-[0-9]+-[0-9]+$ ]] \
  || die "CODERUSHOJ_CLUSTER_NAME is not an owned product E2E cluster"
[[ "$(kubectl config current-context)" == "$expected_context" ]] \
  || die "kubectl context is not the owned product E2E cluster"
for secret_file in admin-username admin-password; do
  [[ -s "$secret_root/$secret_file" ]] \
    || die "missing browser product E2E secret file: $secret_file"
done
[[ -d "$browser_root/node_modules/@playwright/test" ]] \
  || die "browser product E2E dependencies are not installed"

mkdir -p "$artifact_root"
chmod 700 "$state_root" "$secret_root"
export CODERUSHOJ_E2E_BROWSER_BASE_URL="${CODERUSHOJ_E2E_BROWSER_BASE_URL:-http://coderushoj.local:8080}"
export CODERUSHOJ_E2E_CLUSTER_NAME="$cluster_name"
export CODERUSHOJ_E2E_SECRET_ROOT="$secret_root"

log "running the real Chromium product journey through Envoy Gateway"
npm run test:product --prefix "$browser_root"
