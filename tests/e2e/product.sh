#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/lib.sh
source "$ROOT_DIR/scripts/lib.sh"

require_command curl
require_command jq
require_command kubectl
require_command python3

readonly namespace="coderushoj"
readonly cluster_name="${CODERUSHOJ_CLUSTER_NAME:-}"
readonly state_root="$ROOT_DIR/.workspace/product-e2e/$cluster_name"
readonly secret_root="$state_root/secrets"
readonly primary_host="coderushoj.local"
readonly judge_host="judge.coderushoj.local"
readonly docs_host="docs.coderushoj.local"
readonly gateway_url="${CODERUSHOJ_E2E_GATEWAY_URL:-http://127.0.0.1:8080}"
run_dir="$(mktemp -d "$state_root/run.XXXXXX")"
readonly run_dir
port_forward_pid=""

cleanup() {
  if [[ -n "$port_forward_pid" ]] && kill -0 "$port_forward_pid" 2>/dev/null; then
    kill "$port_forward_pid" 2>/dev/null || true
    wait "$port_forward_pid" 2>/dev/null || true
  fi
  rm -rf "$run_dir"
}
trap cleanup EXIT

[[ "$cluster_name" =~ ^croj-product-e2e-[0-9]+-[0-9]+$ ]] \
  || die "CODERUSHOJ_CLUSTER_NAME is not an owned product E2E cluster"
[[ "$(kubectl config current-context)" == "kind-$cluster_name" ]] \
  || die "kubectl context is not the owned product E2E cluster"
for secret_file in admin-username admin-email admin-password external-api-key; do
  [[ -s "$secret_root/$secret_file" ]] || die "missing product E2E secret file: $secret_file"
done
chmod 700 "$state_root" "$secret_root" "$run_dir"

request_json() {
  local output="$1"
  local host="$2"
  local method="$3"
  local endpoint="$4"
  local header_file="$5"
  local body_file="$6"
  shift 6
  local status
  local -a arguments=(
    --silent
    --show-error
    --output "$output"
    --write-out "%{http_code}"
    --request "$method"
    --header "Host: $host"
    --header "Accept: application/json"
  )
  if [[ -n "$header_file" ]]; then
    arguments+=(--header "@$header_file")
  fi
  if [[ -n "$body_file" ]]; then
    arguments+=(
      --header "Content-Type: application/json"
      --data-binary "@$body_file"
    )
  fi
  arguments+=("$@" "$gateway_url$endpoint")
  status="$(curl "${arguments[@]}")"
  [[ "$status" =~ ^2[0-9][0-9]$ ]] \
    || die "$method $endpoint returned HTTP $status"
}

assert_result_success() {
  local response="$1"
  jq -e '.success == true and .code == 20000' "$response" >/dev/null \
    || die "backend returned an unsuccessful product response"
}

wait_for_http() {
  local host="$1"
  local endpoint="$2"
  local attempts=60
  while ((attempts > 0)); do
    if curl --silent --show-error --fail \
      --header "Host: $host" \
      "$gateway_url$endpoint" >/dev/null 2>&1; then
      return
    fi
    attempts=$((attempts - 1))
    sleep 2
  done
  die "timed out waiting for $host$endpoint"
}

wait_for_http "$primary_host" "/api/actuator/health/readiness"
wait_for_http "$primary_host" "/"
wait_for_http "$docs_host" "/"
wait_for_http "$judge_host" "/readyz"

log "verifying real SMTP delivery through Mailpit"
kubectl port-forward --namespace "$namespace" \
  service/coderushoj-infra-mailpit 18025:8025 \
  --address 127.0.0.1 >"$run_dir/mailpit-port-forward.log" 2>&1 &
port_forward_pid="$!"
for _ in $(seq 1 30); do
  if curl --silent --show-error --fail \
    "http://127.0.0.1:18025/api/v1/messages" \
    --output "$run_dir/mail-before.json"; then
    break
  fi
  sleep 1
done
[[ -s "$run_dir/mail-before.json" ]] || die "Mailpit API did not become ready"
mail_before="$(jq -r '.total // .messages_count // (.messages | length)' "$run_dir/mail-before.json")"
request_json "$run_dir/email-code.json" "$primary_host" POST \
  "/api/email/code?email=e2e-mail@coderushoj.invalid&username=e2e-mail-user" "" ""
assert_result_success "$run_dir/email-code.json"
mail_delivered="false"
for _ in $(seq 1 30); do
  curl --silent --show-error --fail \
    "http://127.0.0.1:18025/api/v1/messages" \
    --output "$run_dir/mail-after.json"
  mail_after="$(jq -r '.total // .messages_count // (.messages | length)' "$run_dir/mail-after.json")"
  if ((mail_after > mail_before)); then
    mail_delivered="true"
    break
  fi
  sleep 1
done
[[ "$mail_delivered" == "true" ]] || die "Mailpit did not receive the product email"

log "logging in as the bootstrapped SUPER_ADMIN through the real HTTP API"
captcha_status="$(
  curl --silent --show-error \
    --dump-header "$run_dir/captcha.headers" \
    --output "$run_dir/captcha.jpg" \
    --write-out "%{http_code}" \
    --header "Host: $primary_host" \
    "$gateway_url/api/captcha"
)"
[[ "$captcha_status" == "200" ]] || die "captcha endpoint returned HTTP $captcha_status"
captcha_key="$(
  awk 'BEGIN {IGNORECASE=1} /^Captcha-Key:/ {gsub("\\r", ""); sub(/^[^:]+:[[:space:]]*/, ""); print}' \
    "$run_dir/captcha.headers"
)"
[[ -n "$captcha_key" ]] || die "captcha response omitted Captcha-Key"

# This is an intentional white-box anti-bot fixture: the test reads the value
# stored by the real captcha endpoint from the real test-cluster Redis, then
# exercises the unchanged production login API. No bypass exists in the app.
# shellcheck disable=SC2016
captcha_code="$(
  kubectl exec --namespace "$namespace" statefulset/coderushoj-infra-redis -- \
    /bin/sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli --raw GET "$1"' \
    sh "captchaCode:$captcha_key"
)"
captcha_code="$(tr -d '\r\n' <<<"$captcha_code")"
[[ -n "$captcha_code" ]] || die "captcha value was absent from Redis"

jq -n \
  --arg account "$(cat "$secret_root/admin-username")" \
  --arg password "$(cat "$secret_root/admin-password")" \
  --arg captcha "$captcha_code" \
  --arg captchaKey "$captcha_key" \
  '{account:$account,password:$password,captcha:$captcha,captchaKey:$captchaKey,rememberMe:false}' \
  >"$run_dir/login-request.json"
request_json "$run_dir/login-response.json" "$primary_host" POST \
  "/api/user/login" "" "$run_dir/login-request.json"
assert_result_success "$run_dir/login-response.json"
jwt="$(jq -er '.data.token | select(length > 20)' "$run_dir/login-response.json")"
printf 'Authorization: Bearer %s\n' "$jwt" >"$run_dir/admin.headers"
chmod 600 "$run_dir/admin.headers"
unset jwt captcha_code

log "creating, uploading, and publishing a TestBundle through the admin HTTP API"
manual_problem_title="Manual TestBundle $cluster_name"
jq -n --arg title "$manual_problem_title" '{
  title:$title,
  description:"Add two integers.",
  inputDescription:"Two integers.",
  outputDescription:"Their sum.",
  hints:["Use 64-bit integers."],
  samples:[{input:"20 22",output:"42",explanation:"20 + 22 = 42"}],
  timeLimit:1000,
  memoryLimit:64,
  difficulty:1,
  isSpecialJudge:false,
  specialJudgeCode:null,
  specialJudgeLanguage:null,
  judgeMode:0,
  totalScore:null,
  source:"platform-product-e2e",
  status:1,
  tagIds:[]
}' >"$run_dir/manual-problem-create.json"
request_json "$run_dir/manual-problem-created.json" "$primary_host" POST \
  "/api/problem" "$run_dir/admin.headers" "$run_dir/manual-problem-create.json"
assert_result_success "$run_dir/manual-problem-created.json"
manual_problem_id="$(jq -er '.data' "$run_dir/manual-problem-created.json")"

request_json "$run_dir/manual-problem-versions.json" "$primary_host" GET \
  "/api/v1/admin/problems/${manual_problem_id}/versions" \
  "$run_dir/admin.headers" ""
assert_result_success "$run_dir/manual-problem-versions.json"
manual_version_id="$(
  jq -er '
    .data
    | map(select(.state == "DRAFT" and .attached == false))
    | select(length == 1)
    | .[0].versionId
  ' "$run_dir/manual-problem-versions.json"
)"
manual_list_etag="$(
  jq -er '
    .data
    | map(select(.state == "DRAFT" and .attached == false))
    | select(length == 1)
    | .[0].etag
  ' "$run_dir/manual-problem-versions.json"
)"

manual_bundle_endpoint="/api/v1/admin/problems/${manual_problem_id}/versions/${manual_version_id}/test-bundle"
manual_metadata_status="$(
  curl --silent --show-error \
    --dump-header "$run_dir/manual-bundle-metadata.headers" \
    --output "$run_dir/manual-bundle-metadata.json" \
    --write-out "%{http_code}" \
    --request GET \
    --header "Host: $primary_host" \
    --header "@$run_dir/admin.headers" \
    "$gateway_url$manual_bundle_endpoint"
)"
[[ "$manual_metadata_status" == "200" ]] \
  || die "manual TestBundle metadata returned HTTP $manual_metadata_status"
assert_result_success "$run_dir/manual-bundle-metadata.json"
manual_bundle_etag="$(
  awk 'BEGIN {IGNORECASE=1} /^ETag:/ {gsub("\r", ""); sub(/^[^:]+:[[:space:]]*/, ""); print}' \
    "$run_dir/manual-bundle-metadata.headers"
)"
[[ "$manual_bundle_etag" == "$(jq -er '.data.etag' "$run_dir/manual-bundle-metadata.json")" ]] \
  || die "manual TestBundle metadata body and ETag header disagree"
[[ "$manual_bundle_etag" == "$manual_list_etag" ]] \
  || die "manual TestBundle version list and metadata ETags disagree"

manual_bundle_dir="$run_dir/manual-test-bundle"
mkdir -p "$manual_bundle_dir/cases"
jq -nc '{
  schemaVersion:1,
  judgeMode:"ACM",
  checker:"exact",
  limits:{timeLimitMillis:1000,memoryLimitMiB:64},
  cases:[
    {id:"1",input:"cases/1.in",output:"cases/1.out",weight:1},
    {id:"2",input:"cases/2.in",output:"cases/2.out",weight:1}
  ]
}' >"$manual_bundle_dir/manifest.json"
printf '20 22\n' >"$manual_bundle_dir/cases/1.in"
printf '42\n' >"$manual_bundle_dir/cases/1.out"
printf '500 17\n' >"$manual_bundle_dir/cases/2.in"
printf '517\n' >"$manual_bundle_dir/cases/2.out"
manual_bundle_zip="$run_dir/manual-test-bundle.zip"
(
  cd "$manual_bundle_dir"
  python3 -m zipfile -c "$manual_bundle_zip" \
    manifest.json cases/1.in cases/1.out cases/2.in cases/2.out
)

manual_upload_status="$(
  curl --silent --show-error \
    --dump-header "$run_dir/manual-bundle-uploaded.headers" \
    --output "$run_dir/manual-bundle-uploaded.json" \
    --write-out "%{http_code}" \
    --request PUT \
    --header "Host: $primary_host" \
    --header "@$run_dir/admin.headers" \
    --header "If-Match: $manual_bundle_etag" \
    --form "file=@$manual_bundle_zip;type=application/zip" \
    "$gateway_url$manual_bundle_endpoint"
)"
[[ "$manual_upload_status" == "200" ]] \
  || die "manual TestBundle upload returned HTTP $manual_upload_status"
assert_result_success "$run_dir/manual-bundle-uploaded.json"
uploaded_bundle_etag="$(
  awk 'BEGIN {IGNORECASE=1} /^ETag:/ {gsub("\r", ""); sub(/^[^:]+:[[:space:]]*/, ""); print}' \
    "$run_dir/manual-bundle-uploaded.headers"
)"
[[ "$uploaded_bundle_etag" != "$manual_bundle_etag" ]] \
  || die "manual TestBundle upload did not advance the strong ETag"
jq -e --arg etag "$uploaded_bundle_etag" '
  .data.state == "DRAFT"
  and .data.attached == true
  and (.data.sha256 | test("^[0-9a-f]{64}$"))
  and .data.etag == $etag
' "$run_dir/manual-bundle-uploaded.json" >/dev/null \
  || die "manual TestBundle upload did not return attached metadata and a new ETag"

manual_publish_status="$(
  curl --silent --show-error \
    --dump-header "$run_dir/manual-bundle-published.headers" \
    --output "$run_dir/manual-bundle-published.json" \
    --write-out "%{http_code}" \
    --request POST \
    --header "Host: $primary_host" \
    --header "@$run_dir/admin.headers" \
    --header "If-Match: $uploaded_bundle_etag" \
    "$gateway_url$manual_bundle_endpoint/publish"
)"
[[ "$manual_publish_status" == "200" ]] \
  || die "manual TestBundle publication returned HTTP $manual_publish_status"
assert_result_success "$run_dir/manual-bundle-published.json"
published_bundle_etag="$(
  awk 'BEGIN {IGNORECASE=1} /^ETag:/ {gsub("\r", ""); sub(/^[^:]+:[[:space:]]*/, ""); print}' \
    "$run_dir/manual-bundle-published.headers"
)"
[[ "$published_bundle_etag" != "$uploaded_bundle_etag" ]] \
  || die "manual TestBundle publication did not advance the strong ETag"
jq -e --arg etag "$published_bundle_etag" '
  .data.state == "PUBLISHED"
  and .data.attached == true
  and .data.etag == $etag
' "$run_dir/manual-bundle-published.json" >/dev/null \
  || die "manual TestBundle publication did not return published metadata"

request_json "$run_dir/manual-problem-public.json" "$primary_host" GET \
  "/api/problem/${manual_problem_id}" "" ""
assert_result_success "$run_dir/manual-problem-public.json"
jq -e --argjson id "$manual_problem_id" --arg title "$manual_problem_title" \
  '.data.id == $id and .data.title == $title and .data.status == 0' \
  "$run_dir/manual-problem-public.json" >/dev/null \
  || die "manually published TestBundle problem is not publicly visible"

log "verifying public reads remain pinned while an administrator edits a new draft"
manual_draft_title="Manual Draft $cluster_name"
jq -n --argjson id "$manual_problem_id" --arg title "$manual_draft_title" '{
  id:$id,
  title:$title,
  description:"Draft changes must not leak.",
  inputDescription:"Two signed integers.",
  outputDescription:"Their sum.",
  hints:["This hint belongs only to version 2."],
  samples:[{input:"40 2",output:"42",explanation:"draft sample"}],
  timeLimit:1500,
  memoryLimit:128,
  difficulty:3,
  isSpecialJudge:false,
  specialJudgeCode:null,
  specialJudgeLanguage:null,
  judgeMode:0,
  totalScore:null,
  source:"platform-product-e2e-draft",
  status:0,
  tagIds:[]
}' >"$run_dir/manual-problem-update.json"
request_json "$run_dir/manual-problem-updated.json" "$primary_host" PUT \
  "/api/problem" "$run_dir/admin.headers" "$run_dir/manual-problem-update.json"
assert_result_success "$run_dir/manual-problem-updated.json"
jq -e '.data == true' "$run_dir/manual-problem-updated.json" >/dev/null \
  || die "administrator problem edit did not create a new draft"

request_json "$run_dir/manual-admin-draft-detail.json" "$primary_host" GET \
  "/api/problem/${manual_problem_id}" "$run_dir/admin.headers" ""
assert_result_success "$run_dir/manual-admin-draft-detail.json"
jq -e --arg title "$manual_draft_title" \
  '.data.title == $title and .data.difficulty == 3' \
  "$run_dir/manual-admin-draft-detail.json" >/dev/null \
  || die "administrator cannot see the edited draft"

request_json "$run_dir/manual-admin-draft-versions.json" "$primary_host" GET \
  "/api/v1/admin/problems/${manual_problem_id}/versions" \
  "$run_dir/admin.headers" ""
assert_result_success "$run_dir/manual-admin-draft-versions.json"
jq -e '
  (.data | map(select(.state == "PUBLISHED")) | length) == 1
  and (.data | map(select(.state == "DRAFT" and .attached == false)) | length) == 1
' "$run_dir/manual-admin-draft-versions.json" >/dev/null \
  || die "administrator version list does not expose one published and one draft snapshot"

request_json "$run_dir/manual-public-stable-detail.json" "$primary_host" GET \
  "/api/problem/${manual_problem_id}" "" ""
assert_result_success "$run_dir/manual-public-stable-detail.json"
jq -e --arg title "$manual_problem_title" \
  '.data.title == $title and .data.difficulty == 1 and .data.status == 0' \
  "$run_dir/manual-public-stable-detail.json" >/dev/null \
  || die "anonymous detail leaked the unpublished draft"

jq -n --arg keyword "$manual_problem_title" \
  '{keyword:$keyword,difficulty:1,status:0,current:1,size:10}' \
  >"$run_dir/manual-public-old-title-query.json"
request_json "$run_dir/manual-public-old-title-list.json" "$primary_host" POST \
  "/api/problem/list" "" "$run_dir/manual-public-old-title-query.json"
assert_result_success "$run_dir/manual-public-old-title-list.json"
jq -e --argjson id "$manual_problem_id" --arg title "$manual_problem_title" '
  [.data.records[] | select(.id == $id and .title == $title)]
  | length == 1
' "$run_dir/manual-public-old-title-list.json" >/dev/null \
  || die "anonymous list lost the published title and difficulty projection"

jq -n --arg keyword "$manual_draft_title" \
  '{keyword:$keyword,difficulty:3,status:0,current:1,size:10}' \
  >"$run_dir/manual-public-new-title-query.json"
request_json "$run_dir/manual-public-new-title-list.json" "$primary_host" POST \
  "/api/problem/list" "" "$run_dir/manual-public-new-title-query.json"
assert_result_success "$run_dir/manual-public-new-title-list.json"
jq -e --argjson id "$manual_problem_id" \
  '[.data.records[] | select(.id == $id)] | length == 0' \
  "$run_dir/manual-public-new-title-list.json" >/dev/null \
  || die "anonymous list leaked the unpublished draft title or difficulty"

backend_commit="$(
  python3 -c 'import json; print(json.load(open("config/source-lock.json"))["sources"]["backend"]["commit"])'
)"
readonly backend_commit
readonly sources_root="${CODERUSHOJ_SOURCES_DIR:-$ROOT_DIR/.workspace/sources}"
readonly fps_package="$sources_root/backend/$backend_commit/src/test/resources/problem-import/freeproblemset/fps-zhblue-A+B.xml"
[[ -s "$fps_package" ]] || die "locked Backend FPS fixture is missing"

log "importing and publishing the real locked FPS package"
preflight_status="$(
  curl --silent --show-error \
    --output "$run_dir/import-preflight.json" \
    --write-out "%{http_code}" \
    --request POST \
    --header "Host: $primary_host" \
    --header "@$run_dir/admin.headers" \
    --form "file=@$fps_package;type=application/xml" \
    "$gateway_url/api/v1/admin/problem-imports/preflight"
)"
[[ "$preflight_status" =~ ^2[0-9][0-9]$ ]] \
  || die "FPS preflight returned HTTP $preflight_status"
assert_result_success "$run_dir/import-preflight.json"
jq -e '
  .data.detectedFormat == "FPS_XML"
  and .data.problemCount == 1
  and .data.testCaseCount >= 2
  and (.data.errors | length) == 0
' "$run_dir/import-preflight.json" >/dev/null \
  || die "FPS preflight did not validate one real problem package"
import_job_id="$(jq -er '.data.jobId' "$run_dir/import-preflight.json")"
request_json "$run_dir/import-commit.json" "$primary_host" POST \
  "/api/v1/admin/problem-imports/${import_job_id}/commit" \
  "$run_dir/admin.headers" ""
assert_result_success "$run_dir/import-commit.json"
jq -e '.data.status == "COMMITTED" and .data.importedCount == 1' \
  "$run_dir/import-commit.json" >/dev/null \
  || die "FPS commit did not publish exactly one TestBundle-backed problem"

jq -n '{keyword:"A+B Problem",status:0,current:1,size:10}' \
  >"$run_dir/problem-query.json"
request_json "$run_dir/problem-list.json" "$primary_host" POST \
  "/api/problem/list" "$run_dir/admin.headers" "$run_dir/problem-query.json"
assert_result_success "$run_dir/problem-list.json"
jq -e '[.data.records[] | select(.title == "A+B Problem")] | length == 1' \
  "$run_dir/problem-list.json" >/dev/null \
  || die "the imported problem was not uniquely discoverable through the product list"
problem_id="$(
  jq -er '[.data.records[] | select(.title == "A+B Problem")][0].id' \
    "$run_dir/problem-list.json"
)"

# The immutable version ID is intentionally obtained from the admin product
# contract, never by reading the database.
request_json "$run_dir/problem-versions.json" "$primary_host" GET \
  "/api/v1/admin/problems/${problem_id}/versions" "$run_dir/admin.headers" ""
assert_result_success "$run_dir/problem-versions.json"
problem_version_id="$(
  jq -er '
    (.data | if type == "array" then . else .records end)
    | map(select(((.state // .status) | ascii_upcase) == "PUBLISHED"))
    | select(length == 1)
    | .[0]
    | (.versionId // .id)
  ' "$run_dir/problem-versions.json"
)"

log "publishing global announcement, problem discussion, solution, and contest"
jq -n \
  '{title:"Product E2E announcement",contentMarkdown:"Real three-node Kind acceptance.",pinned:true,pinOrder:1}' \
  >"$run_dir/announcement-create.json"
request_json "$run_dir/announcement-created.json" "$primary_host" POST \
  "/api/v1/admin/announcements" "$run_dir/admin.headers" \
  "$run_dir/announcement-create.json"
assert_result_success "$run_dir/announcement-created.json"
announcement_id="$(jq -er '.data' "$run_dir/announcement-created.json")"
request_json "$run_dir/announcement-admin-list.json" "$primary_host" GET \
  "/api/v1/admin/announcements?page=1&size=20" "$run_dir/admin.headers" ""
assert_result_success "$run_dir/announcement-admin-list.json"
announcement_version="$(
  jq -er --argjson id "$announcement_id" \
    '.data.records[] | select(.id == $id) | .version' \
    "$run_dir/announcement-admin-list.json"
)"
jq -n '{expiresAt:null}' >"$run_dir/announcement-publish.json"
request_json "$run_dir/announcement-published.json" "$primary_host" POST \
  "/api/v1/admin/announcements/${announcement_id}/publish" \
  "$run_dir/admin.headers" "$run_dir/announcement-publish.json" \
  --header "If-Match: \"$announcement_version\""
assert_result_success "$run_dir/announcement-published.json"
request_json "$run_dir/announcement-current.json" "$primary_host" GET \
  "/api/v1/announcements/current?limit=5" "" ""
assert_result_success "$run_dir/announcement-current.json"
jq -e --argjson id "$announcement_id" \
  '.data | any(.id == $id)' "$run_dir/announcement-current.json" >/dev/null \
  || die "published global announcement is not publicly visible"

request_json "$run_dir/categories.json" "$primary_host" GET \
  "/api/v1/forum/categories" "" ""
assert_result_success "$run_dir/categories.json"
category_id="$(
  jq -er '.data | map(select(.slug == "problems")) | select(length == 1) | .[0].id' \
    "$run_dir/categories.json"
)"
jq -n --argjson categoryId "$category_id" --argjson resourceId "$problem_id" \
  '{categoryId:$categoryId,resourceType:"PROBLEM",resourceId:$resourceId,title:"A+B product discussion",contentMarkdown:"Bound to the imported problem."}' \
  >"$run_dir/forum-create.json"
request_json "$run_dir/forum-created.json" "$primary_host" POST \
  "/api/v1/forum/posts" "$run_dir/admin.headers" "$run_dir/forum-create.json"
assert_result_success "$run_dir/forum-created.json"
forum_post_id="$(jq -er '.data' "$run_dir/forum-created.json")"
request_json "$run_dir/forum-list.json" "$primary_host" GET \
  "/api/v1/forum/posts?resourceType=PROBLEM&resourceId=$problem_id&current=1&size=20" "" ""
assert_result_success "$run_dir/forum-list.json"
jq -e --argjson id "$forum_post_id" '.data.records | any(.id == $id)' \
  "$run_dir/forum-list.json" >/dev/null \
  || die "problem-linked discussion is not publicly visible"

jq -n '{title:"A+B product solution",contentMarkdown:"Read two integers and print their sum."}' \
  >"$run_dir/solution-create.json"
request_json "$run_dir/solution-created.json" "$primary_host" POST \
  "/api/v1/problems/${problem_id}/solutions" "$run_dir/admin.headers" \
  "$run_dir/solution-create.json"
assert_result_success "$run_dir/solution-created.json"
solution_id="$(jq -er '.data' "$run_dir/solution-created.json")"
request_json "$run_dir/solution-list.json" "$primary_host" GET \
  "/api/v1/problems/${problem_id}/solutions?current=1&size=20" "" ""
assert_result_success "$run_dir/solution-list.json"
jq -e --argjson id "$solution_id" '.data.records | any(.id == $id)' \
  "$run_dir/solution-list.json" >/dev/null \
  || die "published problem solution is not publicly visible"

contest_times="$(
  python3 -c '
import datetime, json
now = datetime.datetime.now(datetime.timezone.utc)
fmt = lambda value: value.isoformat(timespec="seconds").replace("+00:00", "Z")
print(json.dumps({
  "registrationOpensAt": fmt(now - datetime.timedelta(minutes=5)),
  "registrationClosesAt": fmt(now + datetime.timedelta(minutes=20)),
  "startsAt": fmt(now + datetime.timedelta(minutes=30)),
  "freezeAt": fmt(now + datetime.timedelta(minutes=60)),
  "endsAt": fmt(now + datetime.timedelta(minutes=90)),
}))
'
)"
jq -n --argjson times "$contest_times" \
  '$times + {title:"Product E2E contest",descriptionMarkdown:"Real contest detail.",ruleType:"ACM",visibility:"PUBLIC"}' \
  >"$run_dir/contest-create.json"
request_json "$run_dir/contest-created.json" "$primary_host" POST \
  "/api/v1/admin/contests" "$run_dir/admin.headers" "$run_dir/contest-create.json"
assert_result_success "$run_dir/contest-created.json"
contest_id="$(jq -er '.data' "$run_dir/contest-created.json")"
jq -n --argjson problemId "$problem_id" --argjson problemVersionId "$problem_version_id" \
  '{problems:[{problemId:$problemId,problemVersionId:$problemVersionId,label:"A",score:100}]}' \
  >"$run_dir/contest-problems.json"
request_json "$run_dir/contest-arranged.json" "$primary_host" PUT \
  "/api/v1/admin/contests/${contest_id}/problems" "$run_dir/admin.headers" \
  "$run_dir/contest-problems.json"
assert_result_success "$run_dir/contest-arranged.json"
request_json "$run_dir/contest-published.json" "$primary_host" POST \
  "/api/v1/admin/contests/${contest_id}/publish" "$run_dir/admin.headers" ""
assert_result_success "$run_dir/contest-published.json"
request_json "$run_dir/contest-detail.json" "$primary_host" GET \
  "/api/v1/contests/${contest_id}" "" ""
assert_result_success "$run_dir/contest-detail.json"
jq -e --argjson id "$contest_id" \
  '.data.contest.id == $id and .data.contest.lifecycle == "PUBLISHED"' \
  "$run_dir/contest-detail.json" >/dev/null \
  || die "published contest detail is not publicly visible"

log "submitting real product code and waiting for an ACCEPTED backend terminal result"
jq -n --argjson problemId "$problem_id" \
  --arg code '#include <iostream>
int main(){long long a,b; while(std::cin>>a>>b){std::cout<<a+b; if(a!=500 || b!=17) std::cout<<"\n";}}' \
  '{problemId:$problemId,language:"cpp",code:$code}' \
  >"$run_dir/submission-create.json"
request_json "$run_dir/submission-created.json" "$primary_host" POST \
  "/api/submission" "$run_dir/admin.headers" "$run_dir/submission-create.json"
assert_result_success "$run_dir/submission-created.json"
submission_id="$(jq -er '.data' "$run_dir/submission-created.json")"
submission_terminal="false"
for _ in $(seq 1 150); do
  request_json "$run_dir/submission.json" "$primary_host" GET \
    "/api/submission/${submission_id}" "$run_dir/admin.headers" ""
  assert_result_success "$run_dir/submission.json"
  submission_status="$(jq -er '.data.status' "$run_dir/submission.json")"
  if ((submission_status != 0)); then
    submission_terminal="true"
    break
  fi
  sleep 2
done
[[ "$submission_terminal" == "true" ]] || die "product submission never reached a terminal state"
jq -e '.data.status == 1 and .data.statusText == "通过"' \
  "$run_dir/submission.json" >/dev/null \
  || die "correct product submission did not reach ACCEPTED"

log "uploading a real external bundle and polling the asynchronous REST job"
printf 'Authorization: Bearer %s\n' "$(cat "$secret_root/external-api-key")" \
  >"$run_dir/external.headers"
chmod 600 "$run_dir/external.headers"
request_json "$run_dir/capabilities.json" "$judge_host" GET \
  "/api/v1/capabilities" "$run_dir/external.headers" ""
jq -e '.apiVersion == "v1" and (.languages | any(.id == "cpp"))' \
  "$run_dir/capabilities.json" >/dev/null \
  || die "external judge capabilities do not advertise C++"

bundle_zip="$run_dir/external-test-bundle.zip"
(
  cd "$SCRIPT_DIR/bundle"
  python3 -m zipfile -c "$bundle_zip" manifest.json 1.in 1.out 2.in 2.out
)
bundle_status="$(
  curl --silent --show-error \
    --output "$run_dir/bundle-created.json" \
    --write-out "%{http_code}" \
    --request POST \
    --header "Host: $judge_host" \
    --header "@$run_dir/external.headers" \
    --header "Idempotency-Key: product-e2e-bundle" \
    --form "bundle=@$bundle_zip;type=application/zip" \
    "$gateway_url/api/v1/bundles"
)"
[[ "$bundle_status" == "200" || "$bundle_status" == "201" ]] \
  || die "external bundle upload returned HTTP $bundle_status"
bundle_id="$(jq -er '.bundleId' "$run_dir/bundle-created.json")"

jq -n --arg bundleId "$bundle_id" \
  --arg sourceCode '#include <iostream>
int main(){std::cout<<"42\n";}' \
  '{bundleId:$bundleId,language:"cpp",sourceCode:$sourceCode,stopOnFailure:true,clientReference:"product-e2e-external"}' \
  >"$run_dir/external-job-request.json"
request_json "$run_dir/external-job-created.json" "$judge_host" POST \
  "/api/v1/judge-jobs" "$run_dir/external.headers" \
  "$run_dir/external-job-request.json" \
  --header "Idempotency-Key: product-e2e-job"
external_job_id="$(jq -er '.jobId' "$run_dir/external-job-created.json")"
external_terminal="false"
for _ in $(seq 1 150); do
  request_json "$run_dir/external-job.json" "$judge_host" GET \
    "/api/v1/judge-jobs/${external_job_id}" "$run_dir/external.headers" ""
  external_status="$(jq -er '.status' "$run_dir/external-job.json")"
  case "$external_status" in
    SUCCEEDED | FAILED | CANCELLED)
      external_terminal="true"
      break
      ;;
  esac
  sleep 2
done
[[ "$external_terminal" == "true" ]] || die "external judge job never reached a terminal state"
jq -e '
  .status == "SUCCEEDED"
  and .result.verdict == "ACCEPTED"
  and .result.compileStatus == "SUCCEEDED"
  and (.result.cases | length) == 2
  and (.result.cases | all(.verdict == "ACCEPTED"))
' "$run_dir/external-job.json" >/dev/null \
  || die "external job did not compile once and accept both sandbox cases"

service_cluster_ip="$(
  kubectl get service sandbox-workers --namespace "$namespace" \
    --output=jsonpath='{.spec.clusterIP}'
)"
[[ "$service_cluster_ip" == "None" ]] \
  || die "sandbox-workers must remain a headless Service"

kubectl get endpointslices.discovery.k8s.io \
  --namespace "$namespace" \
  --selector kubernetes.io/service-name=sandbox-workers \
  --output=json >"$run_dir/sandbox-endpointslices.json"
ready_sandbox_endpoints="$(
  jq -r '[.items[].endpoints[] | select(.conditions.ready == true)] | length' \
    "$run_dir/sandbox-endpointslices.json"
)"
sandbox_worker_nodes="$(
  jq -r '
    [.items[].endpoints[]
      | select(.conditions.ready == true)
      | .nodeName]
    | map(select(type == "string" and length > 0))
    | unique
    | length
  ' "$run_dir/sandbox-endpointslices.json"
)"
((ready_sandbox_endpoints >= 2)) \
  || die "sandbox-workers EndpointSlices expose fewer than two ready endpoints"
[[ "$sandbox_worker_nodes" == "2" ]] \
  || die "ready sandbox endpoints are not distributed across both worker nodes"
while IFS= read -r sandbox_node; do
  [[ "$(
    kubectl get node "$sandbox_node" \
      --output=jsonpath='{.metadata.labels.coderushoj\\.io/sandbox}'
  )" == "true" ]] || die "sandbox endpoint is not hosted on a sandbox worker node"
done < <(
  jq -r '
    [.items[].endpoints[]
      | select(.conditions.ready == true)
      | .nodeName]
    | unique[]
  ' "$run_dir/sandbox-endpointslices.json"
)
[[ "$(
  kubectl get nodes --selector coderushoj.io/sandbox=true \
    --output=jsonpath='{.items[*].metadata.name}' \
    | wc -w | tr -d ' '
)" == "2" ]] || die "the cluster does not have exactly two sandbox worker nodes"

wait_for_http "$primary_host" "/api/actuator/health/readiness"
wait_for_http "$judge_host" "/readyz"
log "real three-node product and external judge E2E: PASS"
