#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

readonly REPOSITORIES=(
  ".github"
  "croj-frontend"
  "croj-backend"
  "croj-judging-server"
  "croj-sandbox"
)
readonly DESTINATION="${CODERUSHOJ_REPOS_DIR:-$CODERUSHOJ_ROOT/.workspace/repos}"

mode="clone"
case "${1:-}" in
  "") ;;
  --print) mode="print" ;;
  --update) mode="update" ;;
  *) die "usage: $0 [--print|--update]" ;;
esac

if [[ "$mode" == "print" ]]; then
  printf '%s\n' "${REPOSITORIES[@]}"
  exit 0
fi

require_command git
mkdir -p "$DESTINATION"

for repository in "${REPOSITORIES[@]}"; do
  repository_dir="$DESTINATION/$repository"
  repository_url="https://github.com/CodeRushOJ/$repository.git"

  if [[ -d "$repository_dir/.git" ]]; then
    if [[ "$mode" == "update" ]]; then
      log "fetching $repository"
      git -C "$repository_dir" fetch --prune origin
    else
      log "keeping existing clone $repository"
    fi
    continue
  fi

  [[ ! -e "$repository_dir" ]] || die "$repository_dir exists but is not a Git repository"
  log "cloning $repository"
  git clone "$repository_url" "$repository_dir"
done
