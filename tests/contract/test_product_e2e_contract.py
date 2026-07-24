import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
PRODUCT_E2E = ROOT / "tests/e2e/product.sh"
NETWORK_E2E = ROOT / "tests/e2e/network-policy.sh"
DEPLOY = ROOT / "scripts/deploy-product-e2e.sh"
CLEANUP = ROOT / "scripts/cleanup-product-e2e.sh"
INSTALL_NETWORKING = ROOT / "scripts/install-kind-networking.sh"
KIND_CONFIG = ROOT / "config/kind/product-e2e.yaml"


class ProductE2EContractTest(unittest.TestCase):
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
        self.assertIn("- name: Collect redacted product E2E diagnostics", workflow)
        self.assertIn("if: failure()", workflow)
        self.assertIn("scripts/diagnostics.sh", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertIn(
            "product-e2e-diagnostics-${{ github.run_id }}-${{ github.run_attempt }}",
            workflow,
        )

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

    def test_product_flow_proves_headless_sandbox_discovery_on_both_workers(self):
        script = PRODUCT_E2E.read_text()
        self.assertIn("endpointslices.discovery.k8s.io", script)
        self.assertIn("sandbox-workers", script)
        self.assertIn("ready_sandbox_endpoints", script)
        self.assertIn("sandbox_worker_nodes", script)
        self.assertIn("coderushoj.io/sandbox=true", script)

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
