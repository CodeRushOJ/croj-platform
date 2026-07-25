#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/lib.sh
source "$ROOT_DIR/scripts/lib.sh"
# shellcheck disable=SC1091
source "$ROOT_DIR/config/versions.env"

require_command curl
require_command kubectl

readonly namespace="coderushoj"
readonly cluster_name="${CODERUSHOJ_CLUSTER_NAME:-}"
readonly probe_name="product-e2e-network-probe"
readonly primary_url="${CODERUSHOJ_E2E_GATEWAY_URL:-http://127.0.0.1:8080}"
readonly network_probe_image="${CODERUSHOJ_E2E_NETWORK_PROBE_IMAGE:-$E2E_NETWORK_PROBE_IMAGE}"

[[ "$cluster_name" =~ ^croj-product-e2e-[0-9]+-[0-9]+$ ]] \
  || die "CODERUSHOJ_CLUSTER_NAME is not an owned product E2E cluster"
[[ "$(kubectl config current-context)" == "kind-$cluster_name" ]] \
  || die "kubectl context is not the owned product E2E cluster"

calico_available="$(
  kubectl get tigerastatus calico \
    --output=jsonpath='{.status.conditions[?(@.type=="Available")].status}'
)"
[[ "$calico_available" == "True" ]] \
  || die "Calico is not enforcing Kubernetes NetworkPolicy"

curl --silent --show-error --fail \
  --header "Host: coderushoj.local" \
  "$primary_url/api/actuator/health/readiness" >/dev/null

run_denied_probe() {
  local target="$1"
  kubectl delete pod "$probe_name" --namespace "$namespace" \
    --ignore-not-found --wait=true >/dev/null
  if kubectl run "$probe_name" \
    --namespace "$namespace" \
    --restart=Never \
    --attach \
    --rm \
    --image="$network_probe_image" \
    --image-pull-policy=IfNotPresent \
    --labels=app.kubernetes.io/component=network-policy-probe \
    --command -- \
    curl --silent --show-error --connect-timeout 4 "$target" >/dev/null 2>&1; then
    die "NetworkPolicy unexpectedly allowed unauthorized access to $target"
  fi
}

run_denied_probe "http://croj-backend:7999/api/actuator/health/readiness"
run_denied_probe "telnet://sandbox-workers:50051"

log "Calico enforced Gateway-only backend and judge-only sandbox ingress: PASS"
