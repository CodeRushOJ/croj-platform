#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

lock_file="$CODERUSHOJ_ROOT/config/source-lock.json"
cluster_name="${CODERUSHOJ_CLUSTER_NAME:-coderushoj}"

while (($# > 0)); do
  case "$1" in
    --lock)
      (($# >= 2)) || die "--lock requires a path"
      lock_file="$2"
      shift 2
      ;;
    --cluster)
      (($# >= 2)) || die "--cluster requires a name"
      cluster_name="$2"
      shift 2
      ;;
    *) die "usage: $0 [--lock PATH] [--cluster NAME]" ;;
  esac
done

[[ "$cluster_name" =~ ^[a-z0-9][a-z0-9.-]*$ ]] || die "cluster name contains unsupported characters"
require_command docker
require_command kind
require_command python3
python3 "$SCRIPT_DIR/verify-source-lock.py" validate --lock "$lock_file" >/dev/null

images=()
while IFS=$'\t' read -r _component _repository _commit _context _dockerfile image; do
  docker image inspect "$image" >/dev/null || die "development image is not available locally: $image"
  images+=("$image")
done < <(python3 "$SCRIPT_DIR/verify-source-lock.py" rows --lock "$lock_file")

log "loading ${#images[@]} locked development images into Kind cluster $cluster_name"
kind load docker-image "${images[@]}" --name "$cluster_name"
