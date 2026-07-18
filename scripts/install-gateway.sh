#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command kubectl
require_command curl
require_command shasum

# shellcheck disable=SC1091
source "$CODERUSHOJ_ROOT/config/versions.env"
readonly GATEWAY_NAMESPACE="envoy-gateway-system"
readonly manifest_url="https://github.com/envoyproxy/gateway/releases/download/$ENVOY_GATEWAY_VERSION/install.yaml"
download_dir="$(mktemp -d)"
readonly download_dir
readonly manifest_path="$download_dir/envoy-gateway-install.yaml"

cleanup() {
  rm -rf "$download_dir"
}
trap cleanup EXIT

log "downloading Envoy Gateway $ENVOY_GATEWAY_VERSION manifest"
curl -4 --fail --silent --show-error --location \
  "$manifest_url" \
  --output "$manifest_path"

actual_sha256="$(shasum -a 256 "$manifest_path" | awk '{print $1}')"
readonly actual_sha256
[[ "$actual_sha256" == "$ENVOY_GATEWAY_INSTALL_SHA256" ]] \
  || die "Envoy Gateway manifest checksum mismatch"

log "applying Envoy Gateway CRDs and controller"
kubectl apply --server-side --filename "$manifest_path"

kubectl wait --namespace "$GATEWAY_NAMESPACE" \
  --for=condition=Available deployment/envoy-gateway \
  --timeout=180s

log "Envoy Gateway is ready"
