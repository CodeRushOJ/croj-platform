#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

[[ "$(uname -s)" == "Darwin" ]] || die "the local bootstrap currently supports macOS"
require_command brew

log "installing the pinned host tool set with Homebrew"
HOMEBREW_NO_AUTO_UPDATE=1 brew bundle --file "$CODERUSHOJ_ROOT/Brewfile"

log "cloning missing CodeRushOJ repositories"
"$SCRIPT_DIR/clone-repositories.sh"

log "bootstrap complete"
