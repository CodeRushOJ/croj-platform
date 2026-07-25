#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command awk
require_command kubectl

readonly namespace="${1:-coderushoj}"
readonly cluster_name="${CODERUSHOJ_CLUSTER_NAME:-}"
readonly expected_context="kind-$cluster_name"
readonly output_root="$CODERUSHOJ_ROOT/.workspace/product-e2e/$cluster_name/failure-logs"

[[ "$cluster_name" =~ ^croj-product-e2e-[0-9]+-[0-9]+$ ]] \
  || die "CODERUSHOJ_CLUSTER_NAME is not an owned product E2E cluster"
[[ "$(kubectl config current-context)" == "$expected_context" ]] \
  || die "kubectl context is not the owned product E2E cluster"

umask 077
mkdir -p "$output_root"
chmod 700 "$output_root"

redact_log() {
  awk '
    {
      lowered = tolower($0)
      if (lowered ~ /(authorization|cookie|password|secret|token|api[-_ ]?key|database[_ -]?dsn)/) {
        print "[REDACTED SENSITIVE LOG LINE]"
      } else {
        print
      }
    }
  '
}

while IFS= read -r pod; do
  [[ "$pod" == pod/* ]] || continue
  pod_name="${pod#pod/}"
  while IFS= read -r container; do
    [[ "$container" =~ ^[A-Za-z0-9_.-]+$ ]] || continue
    for mode in current previous; do
      log_args=(
        logs "$pod"
        --namespace "$namespace"
        --container "$container"
        --tail=300
        --timestamps
      )
      if [[ "$mode" == "previous" ]]; then
        log_args+=(--previous)
      fi
      {
        kubectl "${log_args[@]}" 2>&1 || true
      } | redact_log >"$output_root/${pod_name}.${container}.${mode}.log"
      chmod 600 "$output_root/${pod_name}.${container}.${mode}.log"
    done
  done < <(
    kubectl get "$pod" \
      --namespace "$namespace" \
      --output=jsonpath='{range .spec.containers[*]}{.name}{"\n"}{end}'
  )
done < <(
  kubectl get pods \
    --namespace "$namespace" \
    --selector app.kubernetes.io/instance=coderushoj \
    --output=name
)

log "redacted current/previous product logs captured in $output_root"
