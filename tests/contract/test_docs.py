import json
import pathlib
import re
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


class DocumentationContractTest(unittest.TestCase):
    def test_required_operator_pages_exist_and_are_navigable(self):
        required = (
            "index.md",
            "guide/quickstart.md",
            "guide/application-deployment.md",
            "guide/sandbox-deployment.md",
            "guide/github-pages.md",
            "architecture/platform.md",
            "operations/troubleshooting.md",
            "operations/backup-restore.md",
            "releases/index.md",
            "project/history.md",
        )
        for relative_path in required:
            self.assertTrue((DOCS / relative_path).is_file(), f"missing docs page: {relative_path}")

        config = (DOCS / ".vitepress/config.mts").read_text()
        for path in (
            "/guide/quickstart",
            "/guide/application-deployment",
            "/guide/sandbox-deployment",
            "/guide/github-pages",
            "/architecture/platform",
            "/operations/product-e2e",
            "/operations/troubleshooting",
        ):
            self.assertIn(path, config)
        self.assertIn("withMermaid", config)
        self.assertIn("superpowers/**", config)

    def test_docs_default_to_project_pages_and_allow_custom_domain_base(self):
        config = (DOCS / ".vitepress/config.mts").read_text()
        self.assertIn("CODERUSHOJ_DOCS_BASE", config)
        self.assertIn("'/croj-platform/'", config)
        self.assertIn("base: docsBase", config)
        self.assertIn("startsWith('/')", config)
        self.assertIn("endsWith('/')", config)

        pages_guide = (DOCS / "guide/github-pages.md").read_text()
        for contract in (
            "https://coderushoj.github.io/croj-platform/",
            "CODERUSHOJ_DOCS_BASE",
            "Settings → Pages",
            "GitHub Actions",
            "Kubernetes Gateway",
        ):
            self.assertIn(contract, pages_guide)

    def test_pages_workflow_builds_pull_requests_and_deploys_only_trusted_refs(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text()
        for trigger in ("pull_request:", "branches: [main]", "workflow_dispatch:"):
            self.assertIn(trigger, workflow)
        self.assertNotIn("pull_request_target", workflow)

        for action in (
            "actions/checkout",
            "actions/setup-node",
            "actions/configure-pages",
            "actions/upload-pages-artifact",
            "actions/deploy-pages",
        ):
            self.assertRegex(workflow, rf"uses: {re.escape(action)}@[0-9a-f]{{40}}")

        self.assertIn("contents: read", workflow)
        self.assertIn("pages: write", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("name: github-pages", workflow)
        self.assertIn("url: ${{ steps.deployment.outputs.page_url }}", workflow)
        self.assertIn("github.event_name != 'pull_request'", workflow)
        self.assertIn("CODERUSHOJ_DOCS_BASE", workflow)
        self.assertIn("/croj-platform/", workflow)
        self.assertIn("path: docs/.vitepress/dist", workflow)
        self.assertIn("group: pages-${{ github.repository }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertNotIn("pages-${{ github.ref }}", workflow)

    def test_quickstart_has_docker_and_kubernetes_paths(self):
        quickstart = (DOCS / "guide/quickstart.md").read_text()
        for command in (
            "docker compose up -d",
            "make cluster-up",
            "make deploy",
            "make smoke",
            "helm upgrade",
            "helm rollback",
        ):
            self.assertIn(command, quickstart)
        self.assertIn("docker buildx", quickstart)

    def test_operations_cover_every_stateful_dependency(self):
        troubleshooting = (DOCS / "operations/troubleshooting.md").read_text()
        backup = (DOCS / "operations/backup-restore.md").read_text()
        for component in ("MySQL", "Redis", "RocketMQ", "SeaweedFS", "Envoy Gateway"):
            self.assertIn(component, troubleshooting)
        self.assertIn("恢复验证", backup)
        self.assertIn("SELECT 1", backup)

    def test_gateway_controller_crds_and_rollback_boundaries_are_explicit(self):
        quickstart = (DOCS / "guide/quickstart.md").read_text()
        troubleshooting = (DOCS / "operations/troubleshooting.md").read_text()
        combined = quickstart + troubleshooting
        for statement in (
            "Envoy Gateway controller 与 CRD 不属于两个应用 Helm release",
            "scripts/install-gateway.sh",
            "kubectl get crd",
            "回滚应用 Chart 不会回滚 Envoy Gateway controller 或 CRD",
            "不得在普通应用回滚中删除 Gateway API 或 Envoy Gateway CRD",
        ):
            self.assertIn(statement, combined)

    def test_external_api_network_flag_and_atomic_diagnostics_are_documented(self):
        quickstart = (DOCS / "guide/quickstart.md").read_text()
        troubleshooting = (DOCS / "operations/troubleshooting.md").read_text()
        self.assertIn("applications.judgingExternalAPIEnabled", quickstart)
        self.assertIn("judgingServer.externalAPI.enabled", quickstart)
        for sequence in (
            "启用顺序：infra → application",
            "禁用顺序：application → infra",
            "启用失败回滚：application → infra",
            "禁用失败回滚：infra → application",
        ):
            self.assertIn(sequence, quickstart)
        for mechanism in (
            "fcntl.flock",
            ".publish.flock",
            "legacy `.publish.lock/`",
            "Python 3",
            "Linux/macOS",
            "journal/previous recovery",
            "不可变 bundle",
            "atomic pointer publish",
        ):
            self.assertIn(mechanism, troubleshooting)
        self.assertNotIn("原子替换 `.workspace/diagnostics/latest/`", troubleshooting)
        self.assertIn("pods-logs.txt", troubleshooting)

    def test_architecture_and_release_history_are_explicit(self):
        architecture = (DOCS / "architecture/platform.md").read_text()
        self.assertIn("```mermaid", architecture)
        self.assertIn("Kubernetes Service/Endpoint", architecture)
        releases = (DOCS / "releases/index.md").read_text()
        history = (DOCS / "project/history.md").read_text()
        self.assertIn("CHANGELOG.md", releases)
        self.assertIn("2025", history)
        self.assertIn("历史原型", history)

    def test_docs_package_build_script_is_present(self):
        package = (DOCS / "package.json").read_text()
        self.assertIn('"build": "vitepress build"', package)
        dockerfile = (DOCS / "Dockerfile").read_text()
        self.assertIn("pnpm build", dockerfile)
        self.assertIn("pnpm-workspace.yaml", dockerfile)
        self.assertIn("CODERUSHOJ_DOCS_LAST_UPDATED=false", dockerfile)
        self.assertIn("CODERUSHOJ_DOCS_BASE=/", dockerfile)
        self.assertGreaterEqual(dockerfile.count("@sha256:"), 2)
        self.assertIn("USER 101:101", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertNotIn(":latest", dockerfile)
        dockerignore = (DOCS / ".dockerignore").read_text()
        self.assertIn("node_modules", dockerignore)
        self.assertIn(".vitepress/dist", dockerignore)
        config = (DOCS / ".vitepress/config.mts").read_text()
        self.assertIn("CODERUSHOJ_DOCS_LAST_UPDATED", config)

    def test_root_readme_points_to_quickstart(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("docs/guide/quickstart.md", readme)
        self.assertIn("docs/guide/application-deployment.md", readme)
        self.assertIn("docs/guide/sandbox-deployment.md", readme)
        self.assertIn("docs/guide/github-pages.md", readme)
        self.assertIn("croj-frontend", readme)
        self.assertIn("croj-backend", readme)

    def test_application_deployment_is_copy_safe_and_matches_the_current_chart(self):
        deployment = (DOCS / "guide/application-deployment.md").read_text()
        for contract in (
            "applications.enabled",
            "secrets.name",
            "scripts/generate-secrets.sh",
            "values-production.yaml",
            "images.backend.digest",
            "images.frontend.digest",
            "images.judgingServer.digest",
            "images.sandbox.digest",
            "images.docs.digest",
            "BACKEND_INTERNAL_URL",
            "SANDBOX_GRPC_TARGET",
            "sandbox-workers",
            "TestBundle",
            "adminBootstrap.enabled",
            "scripts/install-gateway.sh",
            "judge-database-dsn",
            "external-source-keys-json",
            "judge-callback-keys-json",
            "migrate-external-judge-schema",
            "coderushoj_judge",
            "helm upgrade --install",
            "helm rollback",
        ):
            self.assertIn(contract, deployment)
        self.assertNotIn("replace-with-real-password", deployment)
        self.assertNotIn("backend.existingSecret.name", deployment)

    def test_sandbox_deployment_documents_current_security_and_discovery(self):
        deployment = (DOCS / "guide/sandbox-deployment.md").read_text()
        for contract in (
            "sandbox-workers",
            "dns:///sandbox-workers:50051",
            "round_robin",
            "EndpointSlice",
            "CROJ_SANDBOX_INSTANCE_ID",
            "coderushoj.io/sandbox=true",
            "values-kind-app.yaml",
            "values-production.yaml",
            "images.sandbox.digest",
            "privileged",
            "hostPID",
            "/usr/bin/nsenter",
            "Calico",
            "NetworkPolicy",
            "maxConcurrency",
            "EndpointSlice",
            "两个",
            "getent ahostsv4 sandbox-workers",
            "SANDBOX_ALLOW_LEGACY_ENDPOINT_SLICE",
        ):
                self.assertIn(contract, deployment)

    def test_product_e2e_documents_v2_scoring_spj_and_optional_real_webhook(self):
        operations = (DOCS / "operations/product-e2e.md").read_text()
        troubleshooting = (DOCS / "operations/troubleshooting.md").read_text()
        for contract in (
            "manifest v2",
            "OI",
            "30/100",
            "special judge",
            "CODERUSHOJ_E2E_WEBHOOK_URL",
            "CODERUSHOJ_E2E_WEBHOOK_ASSERT_URL",
            "CODERUSHOJ_E2E_WEBHOOK_ASSERT_TOKEN",
            "X-CodeRushOJ-Signature",
            "bodyBase64",
            "未配置",
        ):
            self.assertIn(contract, operations)
        for contract in (
            "migrate-external-judge-schema",
            "coderushoj_judge",
            "sandbox-workers",
            "EndpointSlice",
            "getent ahostsv4",
        ):
            self.assertIn(contract, troubleshooting)

    def test_source_lock_workflow_is_documented(self):
        readme = (ROOT / "README.md").read_text()
        quickstart = (DOCS / "guide/quickstart.md").read_text()
        combined = readme + quickstart
        for value in (
            "config/source-lock.json",
            "make source-verify",
            "make source-checkout",
            "make images-build",
            "make images-load",
            "40 位",
            ".workspace/sources",
        ):
            self.assertIn(value, combined)
        self.assertIn("不会创建或启动 Kind 集群", combined)
        self.assertIn("当前平台 checkout", combined)

        lock = json.loads((ROOT / "config/source-lock.json").read_text())
        self.assertEqual(
            {"frontend", "backend", "judging-server", "sandbox"},
            set(lock["sources"]),
        )
        self.assertNotIn("docs", lock["sources"])

    def test_docs_links_build(self):
        if not (DOCS / "pnpm-lock.yaml").is_file():
            self.skipTest("pnpm lockfile has not been generated")
        result = subprocess.run(
            ["pnpm", "build"],
            cwd=DOCS,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
