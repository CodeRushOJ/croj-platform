#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command helm
require_command kubectl

readonly namespace="coderushoj"

deployment_failed() {
  "$SCRIPT_DIR/diagnostics.sh" "$namespace" || true
}
trap deployment_failed ERR

kubectl cluster-info >/dev/null
"$SCRIPT_DIR/install-gateway.sh"
"$SCRIPT_DIR/generate-secrets.sh" "$namespace"

log "installing pinned stateful dependencies"
helm upgrade --install coderushoj-infra "$CODERUSHOJ_ROOT/charts/coderushoj-infra" \
  --namespace "$namespace" \
  --create-namespace \
  --rollback-on-failure \
  --wait \
  --timeout 12m

log "installing CodeRushOJ routes"
helm upgrade --install coderushoj "$CODERUSHOJ_ROOT/charts/coderushoj" \
  --namespace "$namespace" \
  --values "$CODERUSHOJ_ROOT/charts/coderushoj/values-kind.yaml" \
  --rollback-on-failure \
  --wait \
  --timeout 5m

trap - ERR
log "CodeRushOJ platform dependencies are deployed"
