#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command kubectl
require_command helm

readonly namespace="${1:-coderushoj}"
readonly diagnostics_dir="$CODERUSHOJ_ROOT/.workspace/diagnostics/latest"

mkdir -p "$diagnostics_dir"
kubectl get nodes -o wide >"$diagnostics_dir/nodes.txt" 2>&1 || true
kubectl get pods,svc,pvc,job -n "$namespace" -o wide >"$diagnostics_dir/workloads.txt" 2>&1 || true
kubectl get gateway,httproute -n "$namespace" -o yaml >"$diagnostics_dir/gateway.yaml" 2>&1 || true
kubectl get events -n "$namespace" --sort-by=.metadata.creationTimestamp >"$diagnostics_dir/events.txt" 2>&1 || true
kubectl describe pods -n "$namespace" >"$diagnostics_dir/pods-describe.txt" 2>&1 || true
kubectl logs -n "$namespace" \
  --selector='app.kubernetes.io/instance' \
  --all-containers=true \
  --prefix=true \
  --tail=-1 >"$diagnostics_dir/pods-logs.txt" 2>&1 || true
helm list -A >"$diagnostics_dir/helm.txt" 2>&1 || true

log "redacted diagnostics written to $diagnostics_dir"
