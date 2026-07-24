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
    --sources-root)
      (($# >= 2)) || die "--sources-root requires a directory"
      sources_root="$2"
      shift 2
      ;;
    *) die "usage: $0 [--lock PATH] [--sources-root DIRECTORY]" ;;
  esac
done

require_command go
require_command mktemp
require_command python3
python3 "$SCRIPT_DIR/verify-source-lock.py" validate --lock "$lock_file" >/dev/null

backend_commit=""
judging_commit=""
while IFS= read -r -d '' component; do
  IFS= read -r -d '' _repository || die "source lock record is truncated after component"
  IFS= read -r -d '' commit || die "source lock record is truncated after repository"
  IFS= read -r -d '' _context || die "source lock record is truncated after commit"
  IFS= read -r -d '' _dockerfile || die "source lock record is truncated after context"
  IFS= read -r -d '' _image || die "source lock record is truncated after dockerfile"
  case "$component" in
    backend) backend_commit="$commit" ;;
    judging-server) judging_commit="$commit" ;;
  esac
done < <(python3 "$SCRIPT_DIR/verify-source-lock.py" records --lock "$lock_file")

[[ -n "$backend_commit" ]] || die "source lock does not identify backend"
[[ -n "$judging_commit" ]] || die "source lock does not identify judging-server"

sources_root="$(cd "$sources_root" && pwd)"
backend_root="$sources_root/backend/$backend_commit"
judging_root="$sources_root/judging-server/$judging_commit"
[[ -x "$backend_root/mvnw" ]] || die "backend Maven wrapper is missing: $backend_root/mvnw"
[[ -f "$judging_root/go.mod" ]] || die "judging-server go.mod is missing: $judging_root/go.mod"

contract_directory="$(mktemp -d "${TMPDIR:-/tmp}/coderushoj-test-bundle.XXXXXX")"
[[ -d "$contract_directory" ]] || die "failed to create contract workspace"
cleanup() {
  case "$contract_directory" in
    "${TMPDIR:-/tmp}"/coderushoj-test-bundle.*) rm -rf "$contract_directory" ;;
    *) die "refusing to remove unexpected contract workspace: $contract_directory" ;;
  esac
}
trap cleanup EXIT

artifact="$contract_directory/test-bundle-v1.zip"
log "exporting TestBundle v1 from backend $backend_commit"
(
  cd "$backend_root"
  ./mvnw \
    --batch-mode \
    --no-transfer-progress \
    -Dtest=TestBundleContractExportTest \
    "-Dcroj.contract.output=$artifact" \
    test
)
[[ -s "$artifact" ]] || die "backend contract export did not produce a non-empty artifact"

log "consuming the exact backend artifact with judging-server $judging_commit"
(
  cd "$judging_root"
  CROJ_BACKEND_TEST_BUNDLE_V1="$artifact" \
    go test -race -count=1 ./internal/bundle
)
log "TestBundle v1 producer-to-consumer contract passed"
