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
active_lock_directory=""

release_checkout_lock() {
  local owner=""
  if [[ -z "$active_lock_directory" || ! -d "$active_lock_directory" ]]; then
    active_lock_directory=""
    return
  fi
  if [[ -f "$active_lock_directory/owner" ]]; then
    owner="$(cat "$active_lock_directory/owner")"
  fi
  if [[ -z "$owner" || "$owner" == "$$" ]]; then
    rm -f -- "$active_lock_directory/owner"
    rmdir "$active_lock_directory" 2>/dev/null || true
  fi
  active_lock_directory=""
}

cleanup() {
  if [[ -n "$active_temporary_directory" && -d "$active_temporary_directory" ]]; then
    case "$active_temporary_directory" in
      "$sources_root/.tmp/"*) rm -rf -- "$active_temporary_directory" ;;
      *) log "refusing to remove unexpected temporary path: $active_temporary_directory" ;;
    esac
  fi
  release_checkout_lock
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

acquire_checkout_lock() {
  local lock_directory="$1"
  local attempts=0
  local owner=""
  local stale_directory=""

  while ! mkdir "$lock_directory" 2>/dev/null; do
    owner="$(cat "$lock_directory/owner" 2>/dev/null || true)"
    if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
      stale_directory="${lock_directory}.stale.$$.$attempts"
      if mv "$lock_directory" "$stale_directory" 2>/dev/null; then
        rm -f -- "$stale_directory/owner"
        rmdir "$stale_directory" 2>/dev/null || \
          die "stale checkout lock contains unexpected files: $stale_directory"
        continue
      fi
    fi
    attempts=$((attempts + 1))
    [[ "$attempts" -lt 6000 ]] || die "timed out waiting for checkout lock: $lock_directory"
    sleep 0.05
  done

  active_lock_directory="$lock_directory"
  printf '%s\n' "$$" > "$active_lock_directory/owner"
}

record_count=0
while IFS= read -r -d '' component; do
  IFS= read -r -d '' repository || die "source lock record is truncated after component"
  IFS= read -r -d '' commit || die "source lock record is truncated after repository"
  IFS= read -r -d '' context || die "source lock record is truncated after commit"
  IFS= read -r -d '' dockerfile || die "source lock record is truncated after context"
  IFS= read -r -d '' _image || die "source lock record is truncated after dockerfile"
  record_count=$((record_count + 1))
  component_root="$sources_root/$component"
  checkout_directory="$component_root/$commit"
  lock_directory="$component_root/.${commit}.lock"
  mkdir -p "$component_root"

  if [[ -e "$checkout_directory" ]]; then
    verify_checkout "$component" "$commit" "$context" "$dockerfile" "$checkout_directory"
    log "reusing $component at $commit"
    continue
  fi

  acquire_checkout_lock "$lock_directory"
  if [[ -e "$checkout_directory" ]]; then
    verify_checkout "$component" "$commit" "$context" "$dockerfile" "$checkout_directory"
    log "reusing $component at $commit after concurrent publish"
    release_checkout_lock
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
  verify_checkout "$component" "$commit" "$context" "$dockerfile" "$checkout_directory"
  release_checkout_lock
done < <(python3 "$SCRIPT_DIR/verify-source-lock.py" "records" --lock "$lock_file")
[[ "$record_count" -eq 5 ]] || die "source lock yielded $record_count records, expected 5"
