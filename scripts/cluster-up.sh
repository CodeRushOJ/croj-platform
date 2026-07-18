#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

readonly CLUSTER_NAME="coderushoj"
readonly CLUSTER_CONFIG="$CODERUSHOJ_ROOT/config/kind/cluster.yaml"
readonly dns_primary="${CODERUSHOJ_DNS_PRIMARY:-223.5.5.5}"
readonly dns_secondary="${CODERUSHOJ_DNS_SECONDARY:-1.1.1.1}"

for command_name in colima docker kind kubectl; do
  require_command "$command_name"
done

write_failure_diagnostics() {
  diagnostics_dir="$CODERUSHOJ_ROOT/.workspace/diagnostics/cluster-up"
  mkdir -p "$diagnostics_dir"
  kubectl get nodes -o wide >"$diagnostics_dir/nodes.txt" 2>&1 || true
  kubectl get pods -A -o wide >"$diagnostics_dir/pods.txt" 2>&1 || true
  kubectl get events -A --sort-by=.metadata.creationTimestamp >"$diagnostics_dir/events.txt" 2>&1 || true
  log "cluster diagnostics written to $diagnostics_dir"
}
trap 'write_failure_diagnostics' ERR

ensure_colima_dns() {
  if colima ssh -- test -s /etc/resolv.conf; then
    return
  fi

  log "repairing the Colima guest DNS resolver"
  colima ssh -- sudo mkdir -p /run/systemd/resolve
  printf 'nameserver %s\nnameserver %s\noptions timeout:2 attempts:2\n' \
    "$dns_primary" "$dns_secondary" \
    | colima ssh -- sudo tee /run/systemd/resolve/stub-resolv.conf >/dev/null
  colima ssh -- test -s /etc/resolv.conf \
    || die "Colima guest DNS resolver is unavailable"
}

if ! colima status >/dev/null 2>&1; then
  log "starting Colima with 6 CPUs, 8 GiB memory, and a 50 GiB disk"
  colima start --cpu 6 --memory 8 --disk 50 --arch aarch64 --vm-type vz \
    --dns "$dns_primary" --dns "$dns_secondary"
else
  log "using the running Colima instance"
fi

ensure_colima_dns

if kind get clusters 2>/dev/null | grep -Fxq "$CLUSTER_NAME"; then
  log "Kind cluster $CLUSTER_NAME already exists"
else
  log "creating three-node Kind cluster $CLUSTER_NAME"
  kind create cluster --name "$CLUSTER_NAME" --config "$CLUSTER_CONFIG"
fi

kubectl config use-context "kind-$CLUSTER_NAME" >/dev/null
kubectl wait --for=condition=Ready nodes --all --timeout=240s

node_count="$(kubectl get nodes --no-headers | wc -l | tr -d ' ')"
[[ "$node_count" == "3" ]] || die "expected 3 Kubernetes nodes, found $node_count"

judge_worker_count="$(kubectl get nodes -l coderushoj.io/judge-worker=true --no-headers | wc -l | tr -d ' ')"
[[ "$judge_worker_count" == "2" ]] || die "expected 2 judge workers, found $judge_worker_count"

trap - ERR
log "cluster $CLUSTER_NAME is ready"
