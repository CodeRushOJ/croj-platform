#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"
# shellcheck disable=SC1091
source "$CODERUSHOJ_ROOT/config/versions.env"

require_command curl
require_command kubectl
require_command shasum

readonly cluster_name="${CODERUSHOJ_CLUSTER_NAME:-}"
[[ "$cluster_name" =~ ^croj-product-e2e-[0-9]+-[0-9]+$ ]] \
  || die "CODERUSHOJ_CLUSTER_NAME is not an owned product E2E cluster"
[[ "$(kubectl config current-context)" == "kind-$cluster_name" ]] \
  || die "kubectl context is not the owned product E2E cluster"

readonly manifest_root="https://raw.githubusercontent.com/projectcalico/calico/$CALICO_VERSION/manifests"
download_dir="$(mktemp -d)"
readonly download_dir

cleanup() {
  rm -rf "$download_dir"
}
trap cleanup EXIT

download_verified() {
  local name="$1"
  local expected_sha256="$2"
  local target="$download_dir/$name"
  local actual_sha256

  curl -4 --fail --silent --show-error --location \
    "$manifest_root/$name" --output "$target"
  actual_sha256="$(shasum -a 256 "$target" | awk '{print $1}')"
  [[ "$actual_sha256" == "$expected_sha256" ]] \
    || die "Calico manifest checksum mismatch: $name"
}

download_verified v1_crd_projectcalico_org.yaml "$CALICO_CRDS_SHA256"
download_verified tigera-operator.yaml "$CALICO_OPERATOR_SHA256"

log "installing checksum-pinned Calico $CALICO_VERSION"
kubectl apply --server-side --filename "$download_dir/v1_crd_projectcalico_org.yaml"
kubectl apply --server-side --filename "$download_dir/tigera-operator.yaml"
kubectl wait --namespace tigera-operator --for=condition=Available \
  deployment/tigera-operator --timeout=180s
kubectl apply --filename "$CODERUSHOJ_ROOT/config/calico/installation.yaml"
tigerastatus_present="false"
for _ in $(seq 1 90); do
  if kubectl get tigerastatus calico >/dev/null 2>&1; then
    tigerastatus_present="true"
    break
  fi
  sleep 2
done
[[ "$tigerastatus_present" == "true" ]] \
  || die "Calico operator did not create tigerastatus/calico"
kubectl wait --for=condition=Available tigerastatus/calico --timeout=300s
kubectl wait --for=condition=Ready nodes --all --timeout=300s

log "Calico networking and NetworkPolicy enforcement are ready"
