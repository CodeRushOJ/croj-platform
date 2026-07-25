import pathlib
import json
import re
import stat
import subprocess
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
PRODUCT_E2E = ROOT / "tests/e2e/product.sh"
NETWORK_E2E = ROOT / "tests/e2e/network-policy.sh"
DEPLOY = ROOT / "scripts/deploy-product-e2e.sh"
CLEANUP = ROOT / "scripts/cleanup-product-e2e.sh"
INSTALL_NETWORKING = ROOT / "scripts/install-kind-networking.sh"
CAPTURE_FAILURE_LOGS = ROOT / "scripts/capture-product-e2e-logs.sh"
KIND_CONFIG = ROOT / "config/kind/product-e2e.yaml"
BROWSER_E2E_ROOT = ROOT / "tests/e2e/browser"
BROWSER_PACKAGE = BROWSER_E2E_ROOT / "package.json"
BROWSER_LOCK = BROWSER_E2E_ROOT / "package-lock.json"
BROWSER_CONFIG = BROWSER_E2E_ROOT / "playwright.config.js"
BROWSER_SPEC = BROWSER_E2E_ROOT / "product.spec.js"
BROWSER_RUNNER = ROOT / "scripts/run-browser-product-e2e.sh"
BUNDLE_FIXTURE_BUILDER = ROOT / "tests/e2e/build-test-bundle-fixture.py"
PRODUCT_E2E_DOC = ROOT / "docs/operations/product-e2e.md"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"


class ProductE2EContractTest(unittest.TestCase):
    def test_product_http_calls_are_bounded_and_readiness_is_observable(self):
        product = PRODUCT_E2E.read_text()
        self.assertIn('readonly curl_connect_timeout_seconds="5"', product)
        self.assertIn('readonly curl_max_time_seconds="30"', product)
        self.assertIn("curl_bounded()", product)
        self.assertIn(
            '--connect-timeout "$curl_connect_timeout_seconds"',
            product,
        )
        self.assertIn('--max-time "$curl_max_time_seconds"', product)
        self.assertIn("curl_probe()", product)
        self.assertIn("--connect-timeout 2", product)
        self.assertIn("--max-time 5", product)
        self.assertIn('log "waiting for HTTP readiness: $host$endpoint"', product)
        self.assertIn('log "HTTP readiness confirmed: $host$endpoint"', product)
        raw_curl_calls = [
            line
            for line in product.splitlines()
            if re.search(r"\bcurl\s", line)
            and "require_command curl" not in line
            and "command curl" not in line
        ]
        self.assertEqual(
            [],
            raw_curl_calls,
            "business and readiness requests must use a bounded curl helper",
        )

    def test_product_gate_builds_locked_sources_and_owns_one_disposable_cluster(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("platform-product-e2e:", workflow)
        self.assertIn("scripts/checkout-sources.sh", workflow)
        self.assertIn("scripts/build-dev-images.sh", workflow)
        self.assertIn("kind create cluster", workflow)
        self.assertIn('--name "$CROJ_E2E_CLUSTER_NAME"', workflow)
        self.assertIn("--config config/kind/product-e2e.yaml", workflow)
        self.assertIn('scripts/load-dev-images.sh --cluster "$CROJ_E2E_CLUSTER_NAME"', workflow)
        self.assertIn("scripts/deploy-product-e2e.sh", workflow)
        self.assertIn("tests/e2e/product.sh", workflow)
        self.assertIn("tests/e2e/network-policy.sh", workflow)
        self.assertNotIn(
            "kind create cluster --name coderushoj --config config/kind/product-e2e.yaml",
            workflow,
        )

        cleanup_step = workflow.split("- name: Delete owned product E2E cluster", 1)[1]
        self.assertIn("if: always()", cleanup_step)
        self.assertIn(
            'scripts/cleanup-product-e2e.sh "$CROJ_E2E_CLUSTER_NAME"',
            cleanup_step,
        )

    def test_product_gate_always_collects_redacted_failure_diagnostics(self):
        workflow = WORKFLOW.read_text()
        deploy = DEPLOY.read_text()
        self.assertIn("- name: Collect redacted product E2E diagnostics", workflow)
        self.assertIn("if: failure()", workflow)
        self.assertIn("scripts/capture-product-e2e-logs.sh", workflow)
        self.assertIn("scripts/diagnostics.sh", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertIn(
            "product-e2e-diagnostics-${{ github.run_id }}-${{ github.run_attempt }}",
            workflow,
        )
        self.assertIn("capture-product-e2e-logs.sh", deploy)
        self.assertIn(".workspace/product-e2e/", workflow)
        self.assertNotIn(
            "--rollback-on-failure",
            deploy.split(
                'log "deploying real application images and the one-shot SUPER_ADMIN bootstrap"',
                1,
            )[1],
        )
        capture = CAPTURE_FAILURE_LOGS.read_text()
        self.assertIn('logs "$pod"', capture)
        self.assertIn("--previous", capture)
        self.assertIn("REDACTED SENSITIVE LOG LINE", capture)

    def test_product_gate_requires_an_smtp_banner_before_requesting_email(self):
        product = PRODUCT_E2E.read_text()
        self.assertIn('source "$ROOT_DIR/config/versions.env"', product)
        self.assertIn('readonly smtp_probe_pod="coderushoj-smtp-protocol-probe"', product)
        self.assertIn(
            'CODERUSHOJ_E2E_NETWORK_PROBE_IMAGE:-$E2E_NETWORK_PROBE_IMAGE',
            product,
        )
        self.assertIn('--image="$network_probe_image"', product)
        self.assertIn("--image-pull-policy=IfNotPresent", product)
        self.assertIn(
            '\'{"spec":{"automountServiceAccountToken":false}}\'',
            product,
        )
        self.assertIn(
            "app.kubernetes.io/component=backend",
            product,
        )
        self.assertIn("Mailpit ESMTP Service ready", product)
        self.assertLess(
            product.index("Mailpit ESMTP Service ready"),
            product.index("/api/email/code?email="),
        )

    def test_captcha_fixtures_json_decode_redis_strings_and_fail_closed(self):
        product = PRODUCT_E2E.read_text()
        captcha_shell = product.split(
            "# This is an intentional white-box anti-bot fixture:",
            1,
        )[1].split("jq -n", 1)[0]
        self.assertIn('captcha_code_json="$(', captcha_shell)
        self.assertIn(
            'jq -er \'if type == "string" and length > 0 then . else error(',
            captcha_shell,
        )
        self.assertIn(
            'die "captcha value in Redis was not a non-empty JSON string"',
            captcha_shell,
        )
        self.assertNotIn("tr -d", captcha_shell)

        browser = BROWSER_SPEC.read_text()
        captcha_browser = browser.split(
            "const readCaptchaCode",
            1,
        )[1].split("\ntest(", 1)[0]
        self.assertIn("JSON.parse(redisValue)", captcha_browser)
        self.assertIn('typeof captchaCode !== "string"', captcha_browser)
        self.assertIn("captchaCode.length === 0", captcha_browser)
        self.assertIn(
            'throw new Error("Redis captcha value must be a non-empty JSON string")',
            captcha_browser,
        )
        self.assertNotIn(".trim()", captcha_browser)

    def test_backend_failure_output_is_allowlisted_and_never_dumps_response_data(self):
        product = PRODUCT_E2E.read_text()
        assertion = "assert_result_success() {" + product.split(
            "assert_result_success() {",
            1,
        )[1].split(
            "\n}",
            1,
        )[0] + "\n}"
        self.assertIn("backend response summary", assertion)
        self.assertIn('if type == "boolean" then . else null end', assertion)
        self.assertIn('if type == "number" then . else null end', assertion)
        self.assertIn("messagePresent", assertion)
        self.assertNotIn(".[0:256]", assertion)
        self.assertNotIn("cat ", assertion)
        self.assertNotIn(".data", assertion)

        harness = "\n".join(
            (
                "set -Eeuo pipefail",
                "die() { printf 'failure\\n' >&2; return 1; }",
                assertion,
                'assert_result_success "$1"',
            )
        )
        responses = (
            (
                {
                    "success": {"token": "NESTED_SUCCESS_SECRET"},
                    "code": {"password": "NESTED_CODE_SECRET"},
                    "message": "MESSAGE_SECRET",
                    "data": {"token": "DATA_SECRET"},
                },
                (
                    '"success":null',
                    '"code":null',
                    '"messagePresent":true',
                ),
            ),
            (
                {"success": False, "code": 40003, "msg": "SECOND_MESSAGE_SECRET"},
                (
                    '"success":false',
                    '"code":40003',
                    '"messagePresent":true',
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            response_path = pathlib.Path(directory) / "response.json"
            for response, expected in responses:
                response_path.write_text(json.dumps(response))
                completed = subprocess.run(
                    ["bash", "-c", harness, "bash", str(response_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(0, completed.returncode)
                for fragment in expected:
                    self.assertIn(fragment, completed.stderr)
                for marker in (
                    "NESTED_SUCCESS_SECRET",
                    "NESTED_CODE_SECRET",
                    "MESSAGE_SECRET",
                    "SECOND_MESSAGE_SECRET",
                    "DATA_SECRET",
                ):
                    self.assertNotIn(marker, completed.stderr)

    def test_product_gate_installs_and_runs_pinned_chromium_after_api_seed(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("- name: Set up Node.js for browser product E2E", workflow)
        self.assertIn("node-version: '24.15.0'", workflow)
        self.assertIn("cache: npm", workflow)
        self.assertIn(
            "cache-dependency-path: tests/e2e/browser/package-lock.json",
            workflow,
        )
        self.assertIn("npm ci --prefix tests/e2e/browser", workflow)
        self.assertIn(
            "npx --prefix tests/e2e/browser playwright install --with-deps chromium",
            workflow,
        )
        self.assertIn("scripts/run-browser-product-e2e.sh", workflow)
        self.assertLess(
            workflow.index("tests/e2e/product.sh"),
            workflow.index("scripts/run-browser-product-e2e.sh"),
        )

        package = json.loads(BROWSER_PACKAGE.read_text())
        lock = json.loads(BROWSER_LOCK.read_text())
        playwright_version = package["devDependencies"]["@playwright/test"]
        self.assertRegex(playwright_version, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(
            playwright_version,
            lock["packages"]["node_modules/@playwright/test"]["version"],
        )

    def test_browser_failures_retain_playwright_evidence_as_an_actions_artifact(self):
        workflow = WORKFLOW.read_text()
        self.assertTrue(BROWSER_CONFIG.is_file(), "Playwright config is missing")
        config = BROWSER_CONFIG.read_text()
        self.assertIn("- name: Upload browser product E2E evidence", workflow)
        browser_upload = workflow.split(
            "- name: Upload browser product E2E evidence",
            1,
        )[1].split("- name:", 1)[0]
        self.assertIn("if: failure()", browser_upload)
        self.assertIn("actions/upload-artifact@", browser_upload)
        self.assertIn(
            "product-e2e-browser-${{ github.run_id }}-${{ github.run_attempt }}",
            browser_upload,
        )
        self.assertIn("artifacts/product-e2e-browser/", browser_upload)
        self.assertIn("trace: 'retain-on-failure'", config)
        self.assertIn("screenshot: 'only-on-failure'", config)
        self.assertIn("video: 'retain-on-failure'", config)
        self.assertIn("artifacts/product-e2e-browser/test-results", config)
        self.assertIn("artifacts/product-e2e-browser/report", config)

    def test_browser_runner_is_owned_cluster_scoped_and_never_injects_auth(self):
        self.assertTrue(BROWSER_RUNNER.is_file(), "browser product E2E runner is missing")
        runner = BROWSER_RUNNER.read_text()
        self.assertTrue(runner.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -Eeuo pipefail", runner)
        self.assertIn(r"^croj-product-e2e-[0-9]+-[0-9]+$", runner)
        self.assertIn("kubectl config current-context", runner)
        self.assertIn('"kind-$cluster_name"', runner)
        self.assertIn("admin-username", runner)
        self.assertIn("admin-password", runner)
        self.assertIn("npm run test:product", runner)
        self.assertNotIn("localStorage", runner)
        self.assertNotIn("Authorization:", runner)
        self.assertNotRegex(runner.lower(), r"\bmock\b")
        result = subprocess.run(
            ["bash", "-n", str(BROWSER_RUNNER)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_browser_config_targets_the_real_gateway_with_stable_failure_capture(self):
        self.assertTrue(BROWSER_CONFIG.is_file(), "Playwright config is missing")
        config = BROWSER_CONFIG.read_text()
        self.assertIn("http://coderushoj.local:8080", config)
        self.assertIn("MAP coderushoj.local 127.0.0.1", config)
        self.assertIn("fullyParallel: false", config)
        self.assertIn("workers: 1", config)
        self.assertIn("forbidOnly: true", config)
        self.assertIn("globalTimeout:", config)
        self.assertNotIn("webServer:", config)

    def test_browser_journey_drives_real_product_paths_without_network_stubs(self):
        self.assertTrue(BROWSER_SPEC.is_file(), "browser product E2E spec is missing")
        spec = BROWSER_SPEC.read_text()
        for visible_contract in (
            "用户名或邮箱",
            "验证码",
            "A+B Problem",
            "提交代码",
            "提交解答",
            "ACCEPTED",
            "Product E2E announcement",
            "Real three-node Kind acceptance.",
            "A+B product discussion",
            "A+B product solution",
            "Product E2E contest",
            "题目导入",
            "选择题目包",
            "测试包管理",
            "题目 ID",
        ):
            with self.subTest(visible_contract=visible_contract):
                self.assertIn(visible_contract, spec)
        self.assertIn("/api/captcha", spec)
        self.assertIn("/api/user/login", spec)
        self.assertIn("/api/submission", spec)
        self.assertIn("getByRole", spec)
        self.assertIn("getByLabel", spec)
        self.assertNotIn("page.route(", spec)
        self.assertNotIn("route.fulfill(", spec)
        self.assertNotIn("setTimeout(", spec)
        self.assertNotRegex(spec.lower(), r"\bmock\b")
        self.assertNotRegex(spec.lower(), r"\bmysql\b")

    def test_browser_product_gate_and_failure_evidence_are_documented(self):
        operations = PRODUCT_E2E_DOC.read_text()
        readme = README.read_text()
        changelog = CHANGELOG.read_text()
        for contract in (
            "Playwright",
            "Chromium",
            "真实登录",
            "题目列表",
            "ACCEPTED",
            "公告",
            "题解",
            "比赛详情",
            "题目导入",
            "TestBundle",
            "trace",
            "screenshot",
            "video",
            "run-browser-product-e2e.sh",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, operations)
        self.assertIn("浏览器", readme)
        self.assertIn("Playwright", readme)
        self.assertIn("Chromium", changelog)
        self.assertIn("浏览器", changelog)

    def test_product_kind_cluster_has_three_nodes_and_a_policy_capable_cni(self):
        config = KIND_CONFIG.read_text()
        self.assertNotRegex(config, r"(?m)^name:")
        self.assertEqual(1, config.count("role: control-plane"))
        self.assertEqual(2, config.count("role: worker"))
        self.assertIn("disableDefaultCNI: true", config)
        self.assertIn("podSubnet: 192.168.0.0/16", config)
        self.assertEqual(2, config.count('coderushoj.io/judge-worker: "true"'))
        self.assertEqual(2, config.count('coderushoj.io/sandbox: "true"'))

    def test_network_installer_is_version_and_checksum_pinned(self):
        script = INSTALL_NETWORKING.read_text()
        versions = (ROOT / "config/versions.env").read_text()
        self.assertIn("CALICO_VERSION=", versions)
        self.assertRegex(versions, r"CALICO_CRDS_SHA256=[0-9a-f]{64}")
        self.assertRegex(versions, r"CALICO_OPERATOR_SHA256=[0-9a-f]{64}")
        self.assertIn("actual_sha256", script)
        self.assertIn("shasum -a 256", script)
        self.assertIn("config/calico/installation.yaml", script)
        self.assertIn("kubectl wait", script)
        self.assertIn("tigerastatus_present", script)
        self.assertIn("kubectl get tigerastatus calico", script)
        self.assertIn(r"^croj-product-e2e-[0-9]+-[0-9]+$", script)
        self.assertIn('"kind-$cluster_name"', script)
        self.assertIn("kubectl config current-context", script)
        self.assertNotIn("/latest/", script)

    def test_cleanup_refuses_non_e2e_names_and_only_deletes_the_exact_name(self):
        script = CLEANUP.read_text()
        self.assertIn(r"^croj-product-e2e-[0-9]+-[0-9]+$", script)
        self.assertIn('kind delete cluster --name "$cluster_name"', script)
        self.assertNotIn("kind delete clusters", script)
        self.assertNotIn("kind delete cluster --name coderushoj", script)

    def test_cluster_runtime_scripts_fail_closed_on_context_ownership(self):
        for path in (PRODUCT_E2E, NETWORK_E2E, DEPLOY, INSTALL_NETWORKING):
            with self.subTest(path=path):
                script = path.read_text()
                self.assertIn(r"^croj-product-e2e-[0-9]+-[0-9]+$", script)
                self.assertIn("kubectl config current-context", script)
                self.assertIn('"kind-$cluster_name"', script)

    def test_black_box_flow_uses_real_product_and_external_judge_contracts(self):
        script = PRODUCT_E2E.read_text()
        for endpoint in (
            "/api/captcha",
            "/api/user/login",
            "/api/v1/admin/problem-imports/preflight",
            "/api/v1/admin/problem-imports/${import_job_id}/commit",
            "/api/problem/list",
            "/api/v1/admin/problems/${problem_id}/versions",
            "/api/submission",
            "/api/v1/admin/announcements",
            "/api/v1/forum/posts",
            "/api/v1/problems/${problem_id}/solutions",
            "/api/v1/admin/contests",
            "/api/v1/bundles",
            "/api/v1/judge-jobs",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, script)
        self.assertIn("/api/v1/messages", script)
        self.assertIn("/api/actuator/health/readiness", script)
        self.assertIn("/readyz", script)
        self.assertIn("captchaCode:", script)
        self.assertIn("white-box anti-bot fixture", script)
        self.assertNotRegex(script.lower(), r"\bmock\b")
        self.assertNotIn("mysql ", script)
        self.assertNotIn("mysql_result", script)

    def test_product_flow_uploads_and_publishes_an_admin_test_bundle_with_etags(self):
        script = PRODUCT_E2E.read_text()
        bundle_endpoint = (
            "/api/v1/admin/problems/${manual_problem_id}/versions/"
            "${manual_version_id}/test-bundle"
        )
        self.assertIn('"/api/problem"', script)
        self.assertIn(
            '"/api/v1/admin/problems/${manual_problem_id}/versions"',
            script,
        )
        self.assertIn(f'manual_bundle_endpoint="{bundle_endpoint}"', script)
        self.assertGreaterEqual(
            script.count('"$gateway_url$manual_bundle_endpoint"'),
            2,
        )
        self.assertIn('"$gateway_url$manual_bundle_endpoint/publish"', script)
        self.assertRegex(
            script,
            r"(?s)manual_metadata_status=.*?--request GET.*?"
            r'"\$gateway_url\$manual_bundle_endpoint"',
        )
        self.assertRegex(
            script,
            r"(?s)manual_upload_status=.*?--request PUT.*?"
            r'"\$gateway_url\$manual_bundle_endpoint"',
        )
        self.assertRegex(
            script,
            r"(?s)manual_publish_status=.*?--request POST.*?"
            r'"\$gateway_url\$manual_bundle_endpoint/publish"',
        )
        self.assertGreaterEqual(script.count('If-Match: $manual_bundle_etag'), 1)
        self.assertGreaterEqual(script.count('If-Match: $uploaded_bundle_etag'), 1)
        self.assertIn("manual-test-bundle.zip", script)
        self.assertIn("timeLimitMillis", script)
        self.assertIn("memoryLimitMiB", script)
        self.assertIn("manual_draft_title", script)
        self.assertRegex(
            script,
            r'(?s)manual-problem-update\.json.*?"/api/problem".*?'
            r'"\$run_dir/admin\.headers"',
        )
        self.assertIn("manual-public-old-title-list.json", script)
        self.assertIn("manual-public-new-title-list.json", script)
        self.assertIn("manual-admin-draft-detail.json", script)

    def test_announcement_admin_page_uses_the_backend_items_contract(self):
        script = PRODUCT_E2E.read_text()
        self.assertIn(
            "'.data.items[] | select(.id == $id) | .version'",
            script,
        )
        self.assertNotIn(
            "'.data.records[] | select(.id == $id) | .version'",
            script,
        )

    def test_manual_test_bundle_builder_preserves_declared_paths_and_regular_modes(self):
        self.assertTrue(BUNDLE_FIXTURE_BUILDER.is_file())
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "bundle"
            (root / "cases").mkdir(parents=True)
            expected = {
                "manifest.json": b'{"schemaVersion":1}\n',
                "cases/1.in": b"20 22\n",
                "cases/1.out": b"42\n",
            }
            for name, content in expected.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            archive = pathlib.Path(directory) / "bundle.zip"
            subprocess.run(
                [
                    "python3",
                    str(BUNDLE_FIXTURE_BUILDER),
                    str(root),
                    str(archive),
                    *expected,
                ],
                check=True,
            )
            with zipfile.ZipFile(archive) as fixture:
                self.assertEqual(list(expected), fixture.namelist())
                for entry in fixture.infolist():
                    self.assertEqual(zipfile.ZIP_DEFLATED, entry.compress_type)
                    self.assertEqual(stat.S_IFREG, stat.S_IFMT(entry.external_attr >> 16))
                    self.assertEqual((1980, 1, 1, 0, 0, 0), entry.date_time)
                    self.assertEqual(expected[entry.filename], fixture.read(entry))
            unsafe = subprocess.run(
                [
                    "python3",
                    str(BUNDLE_FIXTURE_BUILDER),
                    str(root),
                    str(archive),
                    "../manifest.json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, unsafe.returncode)

        product = PRODUCT_E2E.read_text()
        self.assertIn('"$SCRIPT_DIR/build-test-bundle-fixture.py"', product)
        self.assertNotIn("python3 -m zipfile -c", product)

    def test_product_flow_proves_headless_sandbox_discovery_on_both_workers(self):
        script = PRODUCT_E2E.read_text()
        self.assertIn("endpointslices.discovery.k8s.io", script)
        self.assertIn("sandbox-workers", script)
        self.assertIn("ready_sandbox_endpoints", script)
        self.assertIn("sandbox_worker_nodes", script)
        self.assertIn("coderushoj.io/sandbox=true", script)
        self.assertIn("sandbox_dns_addresses", script)
        self.assertIn("getent ahostsv4 sandbox-workers", script)
        self.assertIn("SANDBOX_GRPC_TARGET", script)
        self.assertIn("SANDBOX_ALLOW_LEGACY_ENDPOINT_SLICE", script)
        self.assertIn("dns:///sandbox-workers.coderushoj.svc.cluster.local:50051", script)

    def test_external_flow_exercises_manifest_v2_oi_and_special_judge(self):
        script = PRODUCT_E2E.read_text()
        idempotency_keys = re.findall(
            r'--header "Idempotency-Key: ([^"]+)"',
            script,
        )
        self.assertGreaterEqual(len(idempotency_keys), 6)
        for key in idempotency_keys:
            with self.subTest(idempotency_key=key):
                self.assertGreaterEqual(len(key), 16)
                self.assertLessEqual(len(key), 128)
                self.assertTrue(all(0x21 <= ord(character) <= 0x7E for character in key))
        for fixture in ("bundle-oi", "bundle-spj"):
            self.assertIn(fixture, script)
            self.assertTrue((ROOT / "tests/e2e" / fixture).is_dir())
        oi_manifest = json.loads(
            (ROOT / "tests/e2e/bundle-oi/manifest.json").read_text()
        )
        spj_manifest = json.loads(
            (ROOT / "tests/e2e/bundle-spj/manifest.template.json").read_text()
        )
        self.assertEqual(2, oi_manifest["schemaVersion"])
        self.assertEqual("OI", oi_manifest["judgeMode"])
        self.assertEqual(100, oi_manifest["totalScore"])
        self.assertEqual("special", spj_manifest["checker"])
        self.assertIn(".result.score == 30", script)
        self.assertIn(".result.totalScore == 100", script)
        self.assertIn("sourceSha256", script)
        self.assertIn("special judge job", script)

    def test_product_oi_callback_is_visible_in_public_and_admin_scoreboards(self):
        script = PRODUCT_E2E.read_text()
        operations = PRODUCT_E2E_DOC.read_text()
        oi_manifest = json.loads(
            (ROOT / "tests/e2e/bundle-oi/manifest.json").read_text()
        )
        oi_problem_create = script[
            script.index('log "publishing an OI v2 problem')
            : script.index("oi_problem_id=")
        ]
        self.assertIn(
            f'timeLimit:{oi_manifest["limits"]["timeLimitMillis"]}',
            oi_problem_create,
        )
        self.assertIn(
            f'memoryLimit:{oi_manifest["limits"]["memoryLimitMiB"]}',
            oi_problem_create,
        )
        self.assertIn(
            f'totalScore:{oi_manifest["totalScore"]}',
            oi_problem_create,
        )
        self.assertIn("product-oi-submission.json", script)
        self.assertIn(
            '"/api/v1/contests/${oi_contest_id}/scoreboard"',
            script,
        )
        self.assertIn(
            '"/api/v1/admin/contests/${oi_contest_id}/scoreboard"',
            script,
        )
        for contract in (
            ".data.ruleType == \"OI\"",
            ".data.maximumScore == 100",
            ".username == $username",
            ".totalScore == 30",
            ".scoredProblems == 1",
            ".maximumScore == 100",
            ".score == 30",
            ".submissionId == $submissionId",
            ".achievedAt != null",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, script)
        self.assertIn("OI 排行榜", operations)
        self.assertIn("/api/v1/contests/{contestId}/scoreboard", operations)
        self.assertIn("/api/v1/admin/contests/{contestId}/scoreboard", operations)

    def test_webhook_e2e_is_explicit_fail_closed_and_signature_checked(self):
        script = PRODUCT_E2E.read_text()
        deploy = DEPLOY.read_text()
        workflow = WORKFLOW.read_text()
        for token in (
            "CODERUSHOJ_E2E_WEBHOOK_URL",
            "CODERUSHOJ_E2E_WEBHOOK_ASSERT_URL",
            "CODERUSHOJ_E2E_WEBHOOK_ASSERT_TOKEN",
        ):
            self.assertIn(token, script)
            self.assertIn(token, workflow)
        self.assertIn("/app/judge-admin callback create", deploy)
        self.assertIn("callback-id", deploy)
        self.assertIn("callback-secret", deploy)
        self.assertIn("X-CodeRushOJ-Signature", script)
        self.assertIn("X-CodeRushOJ-Event-Id", script)
        self.assertIn("webhook signature", script)

    def test_external_tenant_is_provisioned_with_the_real_admin_binary(self):
        deploy = DEPLOY.read_text()
        self.assertIn("/app/judge-admin tenant create", deploy)
        self.assertIn("/app/judge-admin api-key create", deploy)
        for scope in (
            "capabilities:read",
            "bundle:write",
            "bundle:read",
            "job:submit",
            "job:read",
        ):
            self.assertIn(scope, deploy)
        self.assertNotRegex(deploy.lower(), r"\bmock\b")

    def test_judge_database_bootstrap_uses_mysql_tcp_not_an_image_specific_socket(self):
        deploy = DEPLOY.read_text()
        self.assertIn("CREATE DATABASE IF NOT EXISTS coderushoj_judge", deploy)
        self.assertIn("--protocol=TCP", deploy)
        self.assertIn("--host=127.0.0.1", deploy)

    def test_e2e_scripts_are_strict_and_parse(self):
        for path in (
            PRODUCT_E2E,
            NETWORK_E2E,
            DEPLOY,
            CLEANUP,
            INSTALL_NETWORKING,
        ):
            with self.subTest(path=path):
                contents = path.read_text()
                self.assertTrue(contents.startswith("#!/usr/bin/env bash\n"))
                self.assertIn("set -Eeuo pipefail", contents)
                result = subprocess.run(
                    ["bash", "-n", str(path)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_workflow_actions_are_commit_pinned(self):
        workflow = WORKFLOW.read_text()
        for reference in re.findall(r"uses:\s+([^\s#]+)", workflow):
            with self.subTest(reference=reference):
                self.assertRegex(
                    reference,
                    r"@(?:[0-9a-f]{40}|docker://[^@\s]+@sha256:[0-9a-f]{64})$",
                )


if __name__ == "__main__":
    unittest.main()
