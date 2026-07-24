#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command helm
require_command kubectl
require_command openssl

readonly namespace="coderushoj"
readonly cluster_name="${CODERUSHOJ_CLUSTER_NAME:-}"
readonly expected_context="kind-$cluster_name"
readonly bootstrap_secret="coderushoj-e2e-admin-bootstrap"
readonly state_root="$CODERUSHOJ_ROOT/.workspace/product-e2e/$cluster_name"
readonly secret_root="$state_root/secrets"

[[ "$cluster_name" =~ ^croj-product-e2e-[0-9]+-[0-9]+$ ]] \
  || die "CODERUSHOJ_CLUSTER_NAME is not an owned product E2E cluster"
[[ "$(kubectl config current-context)" == "$expected_context" ]] \
  || die "kubectl context is not the owned product E2E cluster"

deployment_failed() {
  "$SCRIPT_DIR/diagnostics.sh" "$namespace" || true
}
trap deployment_failed ERR

mkdir -p "$secret_root"
chmod 700 "$state_root" "$secret_root"
printf '%s' "e2e-admin" >"$secret_root/admin-username"
printf '%s' "e2e-admin@coderushoj.invalid" >"$secret_root/admin-email"
openssl rand -base64 24 | tr -d '\r\n' >"$secret_root/admin-password"
chmod 600 "$secret_root"/*

"$SCRIPT_DIR/install-gateway.sh"
"$SCRIPT_DIR/generate-secrets.sh" "$namespace"

log "installing product E2E stateful dependencies"
helm upgrade --install coderushoj-infra "$CODERUSHOJ_ROOT/charts/coderushoj-infra" \
  --namespace "$namespace" \
  --create-namespace \
  --rollback-on-failure \
  --wait \
  --wait-for-jobs \
  --timeout 15m

kubectl create secret generic "$bootstrap_secret" \
  --namespace "$namespace" \
  --from-file=username="$secret_root/admin-username" \
  --from-file=email="$secret_root/admin-email" \
  --from-file=password="$secret_root/admin-password" \
  --dry-run=client \
  --output=yaml \
  | kubectl apply --filename - >/dev/null

log "deploying real application images and the one-shot SUPER_ADMIN bootstrap"
helm upgrade --install coderushoj "$CODERUSHOJ_ROOT/charts/coderushoj" \
  --namespace "$namespace" \
  --values "$CODERUSHOJ_ROOT/charts/coderushoj/values-kind.yaml" \
  --values "$CODERUSHOJ_ROOT/charts/coderushoj/values-kind-app.yaml" \
  --set adminBootstrap.enabled=true \
  --set adminBootstrap.secretName="$bootstrap_secret" \
  --rollback-on-failure \
  --wait \
  --wait-for-jobs \
  --timeout 15m
kubectl wait --namespace "$namespace" --for=condition=Complete \
  job/coderushoj-admin-bootstrap --timeout=300s

log "removing bootstrap-only Kubernetes credentials and workload"
helm upgrade coderushoj "$CODERUSHOJ_ROOT/charts/coderushoj" \
  --namespace "$namespace" \
  --values "$CODERUSHOJ_ROOT/charts/coderushoj/values-kind.yaml" \
  --values "$CODERUSHOJ_ROOT/charts/coderushoj/values-kind-app.yaml" \
  --set adminBootstrap.enabled=false \
  --wait \
  --timeout 5m
kubectl delete secret "$bootstrap_secret" --namespace "$namespace" >/dev/null

for deployment in croj-frontend croj-backend croj-judging-server croj-sandbox croj-docs; do
  kubectl rollout status "deployment/$deployment" \
    --namespace "$namespace" --timeout=300s
done

tenant_output="$(
  kubectl exec --namespace "$namespace" deployment/croj-judging-server -- \
    /app/judge-admin tenant create \
    --name product-e2e \
    --max-running 2 \
    --max-queued 10
)"
tenant_id="${tenant_output##*: }"
[[ "$tenant_id" =~ ^[a-z2-7]{26}$ ]] || die "judge-admin returned an invalid tenant ID"

api_key_output="$(
  kubectl exec --namespace "$namespace" deployment/croj-judging-server -- \
    /app/judge-admin api-key create \
    --tenant "$tenant_id" \
    --scopes capabilities:read,bundle:write,bundle:read,job:submit,job:read
)"
api_key="${api_key_output##*: }"
[[ -n "$api_key" ]] || die "judge-admin returned an empty API key"
printf '%s' "$api_key" >"$secret_root/external-api-key"
chmod 600 "$secret_root/external-api-key"

trap - ERR
log "product E2E deployment and operator bootstrap are ready"
