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

log "creating the isolated external Judge database before application startup"
# The quoted program is evaluated inside the MySQL container, where the
# image-provided MYSQL_* environment exists.
# shellcheck disable=SC2016
kubectl exec --namespace "$namespace" statefulset/coderushoj-infra-mysql -- \
  /bin/sh -ec '
    case "$MYSQL_USER" in
      *[!A-Za-z0-9_.-]*|"") exit 64 ;;
    esac
    MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql \
      --protocol=TCP --host=127.0.0.1 --user=root --batch --skip-column-names \
      --execute="CREATE DATABASE IF NOT EXISTS coderushoj_judge CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; GRANT ALL PRIVILEGES ON coderushoj_judge.* TO '\''$MYSQL_USER'\''@'\''%'\'';"
  '

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

if [[ -n "${CODERUSHOJ_E2E_WEBHOOK_URL:-}" ]]; then
  log "provisioning the external product E2E webhook through the real admin binary"
  callback_output="$(
    kubectl exec --namespace "$namespace" deployment/croj-judging-server -- \
      /app/judge-admin callback create \
      --tenant "$tenant_id" \
      --url "$CODERUSHOJ_E2E_WEBHOOK_URL"
  )"
  callback_id="$(
    printf '%s\n' "$callback_output" \
      | sed -n 's/^Callback created: //p'
  )"
  callback_secret="$(
    printf '%s\n' "$callback_output" \
      | sed -n 's/^Callback secret (shown once): //p'
  )"
  [[ "$callback_id" =~ ^[a-z2-7]{26}$ ]] \
    || die "judge-admin returned an invalid callback ID"
  [[ "$callback_secret" == croj_whsec_* ]] \
    || die "judge-admin returned an invalid callback secret"
  printf '%s' "$callback_id" >"$secret_root/callback-id"
  printf '%s' "$callback_secret" >"$secret_root/callback-secret"
  chmod 600 "$secret_root/callback-id" "$secret_root/callback-secret"
  unset callback_output callback_id callback_secret
fi

trap - ERR
log "product E2E deployment and operator bootstrap are ready"
