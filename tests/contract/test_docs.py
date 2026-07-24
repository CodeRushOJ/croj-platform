import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


class DocumentationContractTest(unittest.TestCase):
    def test_required_operator_pages_exist_and_are_navigable(self):
        required = (
            "index.md",
            "guide/quickstart.md",
            "architecture/platform.md",
            "operations/troubleshooting.md",
            "operations/backup-restore.md",
            "releases/index.md",
            "project/history.md",
        )
        for relative_path in required:
            self.assertTrue((DOCS / relative_path).is_file(), f"missing docs page: {relative_path}")

        config = (DOCS / ".vitepress/config.mts").read_text()
        for path in ("/guide/quickstart", "/architecture/platform", "/operations/troubleshooting"):
            self.assertIn(path, config)
        self.assertIn("withMermaid", config)
        self.assertIn("superpowers/**", config)

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
        self.assertIn("croj-frontend", readme)
        self.assertIn("croj-backend", readme)

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
