#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command kubectl
require_command helm

readonly namespace="${1:-coderushoj}"
readonly diagnostics_root="$CODERUSHOJ_ROOT/.workspace/diagnostics"
readonly diagnostics_dir="$CODERUSHOJ_ROOT/.workspace/diagnostics/latest"

staging_dir=""
old_bundle=""

cleanup() {
  if [[ -n "$staging_dir" && ( -d "$staging_dir" || -L "$staging_dir" ) ]]; then
    rm -rf "$staging_dir"
  fi
  if [[ -n "$old_bundle" && ( -e "$old_bundle" || -L "$old_bundle" ) ]]; then
    if [[ ! -e "$diagnostics_dir" && ! -L "$diagnostics_dir" ]]; then
      mv "$old_bundle" "$diagnostics_dir" || true
    else
      rm -rf "$old_bundle"
    fi
  fi
}

handle_signal() {
  exit "$1"
}

trap cleanup EXIT
trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM

umask 077
mkdir -p "$diagnostics_root"
chmod 700 "$diagnostics_root"
staging_dir="$(mktemp -d "$diagnostics_root/.latest.XXXXXX")"
chmod 700 "$staging_dir"

kubectl get nodes -o wide >"$staging_dir/nodes.txt" 2>&1 || true
kubectl get pods,svc,pvc,job -n "$namespace" -o wide >"$staging_dir/workloads.txt" 2>&1 || true
kubectl get gateway,httproute -n "$namespace" -o yaml >"$staging_dir/gateway.yaml" 2>&1 || true
kubectl get events -n "$namespace" --sort-by=.metadata.creationTimestamp >"$staging_dir/events.txt" 2>&1 || true
kubectl describe pods -n "$namespace" >"$staging_dir/pods-describe.txt" 2>&1 || true
helm list -A >"$staging_dir/helm.txt" 2>&1 || true
chmod 600 "$staging_dir"/*

if [[ -e "$diagnostics_dir" || -L "$diagnostics_dir" ]]; then
  old_bundle="$diagnostics_root/.latest.previous.$$"
  mv "$diagnostics_dir" "$old_bundle"
fi

if ! mv "$staging_dir" "$diagnostics_dir"; then
  if [[ -n "$old_bundle" && ( -e "$old_bundle" || -L "$old_bundle" ) ]]; then
    if mv "$old_bundle" "$diagnostics_dir"; then
      old_bundle=""
    fi
  fi
  die "failed to publish diagnostics bundle"
fi
staging_dir=""

if [[ -n "$old_bundle" ]]; then
  rm -rf "$old_bundle"
  old_bundle=""
fi

log "sensitive diagnostics written with restricted permissions to $diagnostics_dir"
