import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
GITHUB = ROOT / ".github"


class GovernanceContractTest(unittest.TestCase):
    def read(self, relative_path):
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"missing governance file: {relative_path}")
        return path.read_text()

    def test_issue_forms_capture_delivery_evidence(self):
        for name in ("epic.yml", "feature.yml", "bug.yml", "docs.yml"):
            form = self.read(f".github/ISSUE_TEMPLATE/{name}")
            self.assertIn("description:", form)
            self.assertIn("acceptance", form.lower())
            self.assertIn("tests", form.lower())
            self.assertIn("release", form.lower())

        security = self.read(".github/ISSUE_TEMPLATE/security.yml")
        self.assertIn("Security Policy", security)
        config = self.read(".github/ISSUE_TEMPLATE/config.yml")
        self.assertIn("blank_issues_enabled: false", config)

    def test_pull_requests_require_traceability_and_rollback(self):
        template = self.read(".github/PULL_REQUEST_TEMPLATE.md").lower()
        for requirement in (
            "linked issue",
            "test evidence",
            "screenshots",
            "migration impact",
            "security impact",
            "operational impact",
            "rollback",
            "release note",
        ):
            self.assertIn(requirement, template)

    def test_project_docs_define_milestones_and_release_sections(self):
        milestones = self.read("docs/project/milestones.md")
        for milestone in ("Platform Foundation", "Core OJ", "Contests", "Community", "v1 Hardening"):
            self.assertIn(milestone, milestones)

        process = self.read("docs/project/release-process.md")
        for section in (
            "Features",
            "Fixes",
            "Security",
            "Migrations",
            "Operations",
            "Known Limitations",
            "Upgrade",
            "Rollback",
        ):
            self.assertIn(section, process)
        self.assertIn("SemVer", process)
        self.assertIn("VERSION", process)

        version = (ROOT / "VERSION").read_text().strip()
        changelog = self.read("CHANGELOG.md")
        current_release = changelog.split(f"## [{version}]", 1)[1].split("\n## [", 1)[0]
        for section in (
            "Features",
            "Fixes",
            "Security",
            "Migrations",
            "Operations",
            "Known Limitations",
            "Upgrade",
            "Rollback",
        ):
            self.assertIn(f"### {section}", current_release)

    def test_ci_enforces_tests_docs_security_and_live_smoke(self):
        workflow = self.read(".github/workflows/ci.yml")
        for command in (
            "make validate",
            "pnpm install --frozen-lockfile",
            "pnpm build",
            "trivy fs",
            "kind create cluster",
            "tests/smoke/platform.sh",
            "scripts/diagnostics.sh",
        ):
            self.assertIn(command, workflow)
        self.assertIn("upload-artifact", workflow)

    def test_ci_kubeconform_checks_default_enabled_and_production_renders(self):
        workflow = self.read(".github/workflows/ci.yml")
        self.assertIn("applications.enabled=true", workflow)
        self.assertIn("charts/coderushoj/values-production.yaml", workflow)
        self.assertGreaterEqual(workflow.count("kubeconform"), 4)
        self.assertGreaterEqual(workflow.count("helm template coderushoj "), 3)

    def test_release_is_tag_gated_version_checked_and_immutable(self):
        workflow = self.read(".github/workflows/release.yml")
        self.assertIn("tags:", workflow)
        self.assertIn("'v*'", workflow)
        self.assertIn("VERSION", workflow)
        self.assertIn("CHANGELOG.md", workflow)
        self.assertIn("helm package", workflow)
        self.assertIn("docker/build-push-action", workflow)
        self.assertIn("github.sha", workflow)
        self.assertIn("packages: write", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("docker/setup-qemu-action@", workflow)
        self.assertIn("platforms: linux/amd64,linux/arm64", workflow)
        self.assertIn("actions/attest-build-provenance@", workflow)
        self.assertIn("push-to-registry: true", workflow)
        self.assertIn("production-images.yaml", workflow)
        self.assertIn("production-images.json", workflow)
        self.assertIn("kubeconform", workflow)
        self.assertIn("git fetch --no-tags origin main", workflow)
        self.assertIn('test "$GITHUB_SHA" = "$(git rev-parse origin/main)"', workflow)
        self.assertNotIn(".verification.verified", workflow)

    def test_release_uses_pinned_helm_and_publishes_the_default_docs_tag(self):
        workflow = self.read(".github/workflows/release.yml")
        helm_setup = (
            "uses: azure/setup-helm@"
            "1a275c3b69536ee54be43f2070a358922e12c8d4"
        )
        setup_position = workflow.index(helm_setup)
        package_position = workflow.index("helm package")
        self.assertLess(setup_position, package_position)
        setup_block = workflow[setup_position:package_position]
        self.assertIn("version: v4.2.3", setup_block)

        version = (ROOT / "VERSION").read_text().strip()
        values = self.read("charts/coderushoj/values.yaml")
        docs_images = values.split("images:", 1)[1].split("services:", 1)[0]
        docs_image = docs_images.split("  docs:", 1)[1]
        self.assertIn(f"tag: v{version}", docs_image)
        self.assertIn(
            "${{ env.DOCS_IMAGE }}:${{ github.ref_name }}",
            workflow,
        )

    def test_v1_release_version_and_notes_match_shipped_platform(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertEqual("1.0.0", version)
        for chart in ("charts/coderushoj/Chart.yaml", "charts/coderushoj-infra/Chart.yaml"):
            manifest = self.read(chart)
            self.assertIn("version: 1.0.0", manifest)
            self.assertIn('appVersion: "1.0.0"', manifest)

        changelog = self.read("CHANGELOG.md")
        unreleased = changelog.split("## [Unreleased]", 1)[1].split("## [1.0.0]", 1)[0]
        for section in ("Features", "Fixes", "Security", "Operations"):
            self.assertIn(f"### {section}", unreleased)
        self.assertNotIn("TBD", unreleased)
        self.assertNotIn("TODO", unreleased)
        self.assertIn("## [1.0.0] - 2026-07-25", changelog)
        release = changelog.split("## [1.0.0] - 2026-07-25", 1)[1].split("\n## [", 1)[0]
        for shipped_fact in (
            "source-lock.json",
            "Mailpit",
            "sandbox-workers",
            "TestBundle v2",
            "NetworkPolicy",
            "production-images.yaml",
        ):
            self.assertIn(shipped_fact, release)

    def test_third_party_actions_are_commit_pinned(self):
        for relative_path in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
            workflow = self.read(relative_path)
            for action_ref in re.findall(r"uses:\s+([^\s#]+)", workflow):
                if action_ref.startswith("./"):
                    continue
                self.assertRegex(
                    action_ref,
                    r"^[^@]+@[0-9a-f]{40}$",
                    f"action must be pinned to a full commit SHA: {action_ref}",
                )


if __name__ == "__main__":
    unittest.main()
