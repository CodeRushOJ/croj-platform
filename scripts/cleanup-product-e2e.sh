#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

readonly cluster_name="${1:-}"
[[ "$cluster_name" =~ ^croj-product-e2e-[0-9]+-[0-9]+$ ]] \
  || die "refusing to delete a cluster not owned by product E2E"

require_command kind
if kind get clusters 2>/dev/null | grep -Fxq "$cluster_name"; then
  log "deleting owned product E2E cluster $cluster_name"
  kind delete cluster --name "$cluster_name"
else
  log "owned product E2E cluster $cluster_name does not exist"
fi
