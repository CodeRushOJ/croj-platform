#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

[[ "$#" -eq 7 ]] || die "usage: $0 COMPONENT REPOSITORY COMMIT CONTEXT DOCKERFILE CHECKOUT_DIRECTORY SOURCES_ROOT"
component="$1"
repository="$2"
commit="$3"
context="$4"
dockerfile="$5"
checkout_directory="$6"
sources_root="$7"
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
  local directory="$1"
  local actual_commit

  [[ -d "$directory/.git" ]] || die "$component checkout is not a Git repository: $directory"
  actual_commit="$(git -C "$directory" rev-parse HEAD)"
  [[ "$actual_commit" == "$commit" ]] || die "$component checkout has $actual_commit, expected $commit"
  if git -C "$directory" symbolic-ref --quiet HEAD >/dev/null; then
    die "$component checkout is not detached: $directory"
  fi
  [[ -z "$(git -C "$directory" status --porcelain --untracked-files=all)" ]] || \
    die "$component checkout is not clean: $directory"
  [[ -f "$directory/$context/$dockerfile" ]] || \
    die "$component Dockerfile is missing: $directory/$context/$dockerfile"
}

if [[ -e "$checkout_directory" ]]; then
  verify_checkout "$checkout_directory"
  log "reusing $component at $commit after concurrent publish"
  exit 0
fi

active_temporary_directory="$(mktemp -d "$sources_root/.tmp/${component}.${commit}.XXXXXX")"
log "fetching $component at $commit"
git -C "$active_temporary_directory" init --quiet
git -C "$active_temporary_directory" remote add origin "$repository"
git -C "$active_temporary_directory" fetch --quiet --depth=1 origin "$commit"
git -C "$active_temporary_directory" -c advice.detachedHead=false checkout --quiet --detach FETCH_HEAD
verify_checkout "$active_temporary_directory"
mv "$active_temporary_directory" "$checkout_directory"
active_temporary_directory=""
verify_checkout "$checkout_directory"
