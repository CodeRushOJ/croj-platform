#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

readonly CLUSTER_NAME="coderushoj"
stop_runtime="false"

case "${1:-}" in
  "") ;;
  --stop-runtime) stop_runtime="true" ;;
  *) die "usage: $0 [--stop-runtime]" ;;
esac

require_command kind

if kind get clusters 2>/dev/null | grep -Fxq "$CLUSTER_NAME"; then
  log "deleting Kind cluster $CLUSTER_NAME"
  kind delete cluster --name "$CLUSTER_NAME"
else
  log "Kind cluster $CLUSTER_NAME does not exist"
fi

if [[ "$stop_runtime" == "true" ]]; then
  require_command colima
  if colima status >/dev/null 2>&1; then
    log "stopping Colima"
    colima stop
  fi
fi
