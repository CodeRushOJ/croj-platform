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
require_command git
require_command kind
require_command python3
python3 "$SCRIPT_DIR/verify-source-lock.py" validate --lock "$lock_file" >/dev/null
platform_revision="$(current_platform_revision)"

images=()
record_count=0
while IFS= read -r -d '' _component; do
  IFS= read -r -d '' _repository || die "source lock record is truncated after component"
  IFS= read -r -d '' _commit || die "source lock record is truncated after repository"
  IFS= read -r -d '' _context || die "source lock record is truncated after commit"
  IFS= read -r -d '' _dockerfile || die "source lock record is truncated after context"
  IFS= read -r -d '' image || die "source lock record is truncated after dockerfile"
  record_count=$((record_count + 1))
  expected_provenance="$_commit"$'\n'"$_repository"
  actual_provenance="$(
    docker image inspect \
      --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}{{ "\n" }}{{ index .Config.Labels "org.opencontainers.image.source" }}' \
      "$image"
  )" || die "development image is not available locally: $image"
  [[ "$actual_provenance" == "$expected_provenance" ]] || \
    die "development image provenance does not match source lock: $image"
  images+=("$image")
done < <(python3 "$SCRIPT_DIR/verify-source-lock.py" "records" --lock "$lock_file")
[[ "$record_count" -eq 4 ]] || die "source lock yielded $record_count records, expected 4"

expected_docs_provenance="$platform_revision"$'\n'"$CODERUSHOJ_PLATFORM_REPOSITORY"
actual_docs_provenance="$(
  docker image inspect \
    --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}{{ "\n" }}{{ index .Config.Labels "org.opencontainers.image.source" }}' \
    "$CODERUSHOJ_DOCS_DEV_IMAGE"
)" || die "development image is not available locally: $CODERUSHOJ_DOCS_DEV_IMAGE"
[[ "$actual_docs_provenance" == "$expected_docs_provenance" ]] || \
  die "development image provenance does not match the current platform checkout: $CODERUSHOJ_DOCS_DEV_IMAGE"
images+=("$CODERUSHOJ_DOCS_DEV_IMAGE")

log "loading ${#images[@]} development images into Kind cluster $cluster_name"
kind load docker-image "${images[@]}" --name "$cluster_name"
