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

require_command git
require_command python3
python3 "$SCRIPT_DIR/verify-source-lock.py" validate --lock "$lock_file" >/dev/null

mkdir -p "$sources_root/.tmp"
sources_root="$(cd "$sources_root" && pwd)"
active_temporary_directory=""

cleanup() {
  if [[ -n "$active_temporary_directory" && -d "$active_temporary_directory" ]]; then
    case "$active_temporary_directory" in
      "$sources_root/.tmp/"*) rm -rf -- "$active_temporary_directory" ;;
      *) log "refusing to remove unexpected temporary path: $active_temporary_directory" ;;
    esac
  fi
}
trap cleanup EXIT

verify_checkout() {
  local component="$1"
  local commit="$2"
  local context="$3"
  local dockerfile="$4"
  local checkout_directory="$5"
  local actual_commit

  [[ -d "$checkout_directory/.git" ]] || die "$component checkout is not a Git repository: $checkout_directory"
  actual_commit="$(git -C "$checkout_directory" rev-parse HEAD)"
  [[ "$actual_commit" == "$commit" ]] || die "$component checkout has $actual_commit, expected $commit"
  if git -C "$checkout_directory" symbolic-ref --quiet HEAD >/dev/null; then
    die "$component checkout is not detached: $checkout_directory"
  fi
  [[ -z "$(git -C "$checkout_directory" status --porcelain --untracked-files=all)" ]] || \
    die "$component checkout is not clean: $checkout_directory"
  [[ -f "$checkout_directory/$context/$dockerfile" ]] || \
    die "$component Dockerfile is missing: $checkout_directory/$context/$dockerfile"
}

while IFS=$'\t' read -r component repository commit context dockerfile _image; do
  component_root="$sources_root/$component"
  checkout_directory="$component_root/$commit"
  mkdir -p "$component_root"

  if [[ -e "$checkout_directory" ]]; then
    verify_checkout "$component" "$commit" "$context" "$dockerfile" "$checkout_directory"
    log "reusing $component at $commit"
    continue
  fi

  active_temporary_directory="$(mktemp -d "$sources_root/.tmp/${component}.${commit}.XXXXXX")"
  log "fetching $component at $commit"
  git -C "$active_temporary_directory" init --quiet
  git -C "$active_temporary_directory" remote add origin "$repository"
  git -C "$active_temporary_directory" fetch --quiet --depth=1 origin "$commit"
  git -C "$active_temporary_directory" -c advice.detachedHead=false checkout --quiet --detach FETCH_HEAD
  verify_checkout "$component" "$commit" "$context" "$dockerfile" "$active_temporary_directory"
  mv "$active_temporary_directory" "$checkout_directory"
  active_temporary_directory=""
done < <(python3 "$SCRIPT_DIR/verify-source-lock.py" rows --lock "$lock_file")
