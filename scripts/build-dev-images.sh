#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

lock_file="$CODERUSHOJ_ROOT/config/source-lock.json"
sources_root="${CODERUSHOJ_SOURCES_DIR:-$CODERUSHOJ_ROOT/.workspace/sources}"

while (($# > 0)); do
  case "$1" in
    --lock)
      (($# >= 2)) || die "--lock requires a path"
      lock_file="$2"
      shift 2
      ;;
    --root)
      (($# >= 2)) || die "--root requires a path"
      sources_root="$2"
      shift 2
      ;;
    *) die "usage: $0 [--lock PATH] [--root DIRECTORY]" ;;
  esac
done

require_command docker
require_command python3
"$SCRIPT_DIR/checkout-sources.sh" --lock "$lock_file" --root "$sources_root"
sources_root="$(cd "$sources_root" && pwd)"

record_count=0
while IFS= read -r -d '' component; do
  IFS= read -r -d '' repository || die "source lock record is truncated after component"
  IFS= read -r -d '' commit || die "source lock record is truncated after repository"
  IFS= read -r -d '' context || die "source lock record is truncated after commit"
  IFS= read -r -d '' dockerfile || die "source lock record is truncated after context"
  IFS= read -r -d '' image || die "source lock record is truncated after dockerfile"
  record_count=$((record_count + 1))
  build_context="$(cd "$sources_root/$component/$commit/$context" && pwd)"
  log "building $image from $component@$commit"
  docker buildx build \
    --load \
    --tag "$image" \
    --build-arg "VCS_REF=$commit" \
    --label "org.opencontainers.image.revision=$commit" \
    --label "org.opencontainers.image.source=$repository" \
    --file "$build_context/$dockerfile" \
    "$build_context"
done < <(python3 "$SCRIPT_DIR/verify-source-lock.py" "records" --lock "$lock_file")
[[ "$record_count" -eq 5 ]] || die "source lock yielded $record_count records, expected 5"
