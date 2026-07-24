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

    def test_first_release_version_and_notes_match_shipped_platform(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertEqual("0.1.0", version)
        for chart in ("charts/coderushoj/Chart.yaml", "charts/coderushoj-infra/Chart.yaml"):
            manifest = self.read(chart)
            self.assertIn("version: 0.1.0", manifest)
            self.assertIn('appVersion: "0.1.0"', manifest)

        changelog = self.read("CHANGELOG.md")
        unreleased = changelog.split("## [Unreleased]", 1)[1].split("## [0.1.0]", 1)[0]
        self.assertEqual("", unreleased.strip())
        self.assertIn("## [0.1.0] - 2026-07-24", changelog)
        release = changelog.split("## [0.1.0] - 2026-07-24", 1)[1].split("\n## [", 1)[0]
        for shipped_fact in (
            "source-lock.json",
            "Mailpit",
            "sandbox-workers",
            "TestBundle v1",
            "NetworkPolicy",
            "尚未执行完整 Kind 端到端判题验收",
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
