#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command helm
require_command kubectl

readonly namespace="${CODERUSHOJ_NAMESPACE:-coderushoj}"
readonly release_name="${CODERUSHOJ_RELEASE_NAME:-coderushoj}"
readonly job_name="${release_name}-admin-bootstrap"
readonly chart="$CODERUSHOJ_ROOT/charts/coderushoj"
readonly secret_dir="$CODERUSHOJ_ROOT/.workspace/secrets"
readonly bootstrap_secret_name="${CODERUSHOJ_BOOTSTRAP_ADMIN_SECRET_NAME:-coderushoj-admin-bootstrap-secret}"

rerun=false
case "${1:-}" in
  "") ;;
  --rerun) rerun=true ;;
  *) die "usage: $0 [--rerun]" ;;
esac

kubectl cluster-info >/dev/null

if kubectl get job "$job_name" --namespace "$namespace" >/dev/null 2>&1; then
  if [[ "$rerun" == "true" ]]; then
    log "deleting the previous $namespace/$job_name before the explicit rerun"
    kubectl delete job "$job_name" --namespace "$namespace" --wait=true >/dev/null
  else
    log "$namespace/$job_name already exists; waiting for its authoritative result"
  fi
fi

if ! kubectl get job "$job_name" --namespace "$namespace" >/dev/null 2>&1; then
  "$SCRIPT_DIR/generate-secrets.sh" "$namespace"
  kubectl create secret generic "$bootstrap_secret_name" \
    --namespace "$namespace" \
    --from-file=username="$secret_dir/bootstrap-admin-username" \
    --from-file=email="$secret_dir/bootstrap-admin-email" \
    --from-file=password="$secret_dir/bootstrap-admin-password" \
    --dry-run=client \
    --output=yaml \
    | kubectl apply --filename - >/dev/null
  log "creating the one-shot administrator bootstrap Job"
  helm template "$release_name" "$chart" \
    --namespace "$namespace" \
    --values "$chart/values-kind.yaml" \
    --values "$chart/values-kind-app.yaml" \
    --set bootstrapAdmin.enabled=true \
    --set-string bootstrapAdmin.secretName="$bootstrap_secret_name" \
    --show-only templates/admin-bootstrap-job.yaml \
    | kubectl apply --filename - >/dev/null
fi

if ! kubectl wait \
  --namespace "$namespace" \
  --for=condition=complete \
  "job/$job_name" \
  --timeout=6m; then
  kubectl logs --namespace "$namespace" "job/$job_name" --all-containers=true --prefix=true || true
  die "administrator bootstrap failed; rerun with --rerun after correcting the reported configuration"
fi

log "administrator bootstrap completed; local username is admin"
log "the generated password remains only in $secret_dir/bootstrap-admin-password"
log "delete $namespace/$bootstrap_secret_name after verifying login"
