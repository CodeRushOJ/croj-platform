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

    def workflow_action_refs(self, workflow_path):
        return re.findall(
            r"""^\s*(?:-\s*)?uses:\s*['"]?([^'"\s#]+)['"]?\s*(?:#.*)?$""",
            workflow_path.read_text(),
            flags=re.MULTILINE,
        )

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
        corepack_position = workflow.index("corepack enable")
        dependency_install_position = workflow.index("pnpm install --frozen-lockfile")
        static_gate_position = workflow.index(
            "- name: Run the complete static release gate"
        )
        self.assertLess(
            corepack_position,
            static_gate_position,
            "pnpm must be provisioned before make validate invokes the docs build",
        )
        self.assertLess(
            dependency_install_position,
            static_gate_position,
            "locked docs dependencies must exist before make validate invokes pnpm build",
        )
        self.assertIn("CHANGELOG.md", workflow)
        self.assertIn("helm package", workflow)
        self.assertIn("docker/build-push-action", workflow)
        self.assertIn("github.sha", workflow)
        self.assertIn("packages: write", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("attestations: write", workflow)
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
        self.assertEqual("1.0.2", version)
        for chart in ("charts/coderushoj/Chart.yaml", "charts/coderushoj-infra/Chart.yaml"):
            manifest = self.read(chart)
            self.assertIn(f"version: {version}", manifest)
            self.assertIn(f'appVersion: "{version}"', manifest)

        changelog = self.read("CHANGELOG.md")
        release_heading = f"## [{version}] - 2026-07-25"
        unreleased = changelog.split("## [Unreleased]", 1)[1].split(
            release_heading, 1
        )[0]
        for section in ("Features", "Fixes", "Security", "Operations"):
            self.assertIn(f"### {section}", unreleased)
        self.assertNotIn("TBD", unreleased)
        self.assertNotIn("TODO", unreleased)
        self.assertIn(release_heading, changelog)
        release = changelog.split(release_heading, 1)[1].split("\n## [", 1)[0]
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
            self.assertIn(f"### {section}", release)
        self.assertIn("corepack enable", release)
        self.assertIn(
            f"[Unreleased]: https://github.com/CodeRushOJ/croj-platform/compare/v{version}...HEAD",
            changelog,
        )
        self.assertIn(
            f"[{version}]: https://github.com/CodeRushOJ/croj-platform/releases/tag/v{version}",
            changelog,
        )
        self.assertIn(
            "[1.0.0]: https://github.com/CodeRushOJ/croj-platform/tree/v1.0.0",
            changelog,
        )
        self.assertIn(
            "[1.0.1]: https://github.com/CodeRushOJ/croj-platform/tree/v1.0.1",
            changelog,
        )
        prior_patch = changelog.split("## [1.0.1] - 2026-07-25", 1)[1].split(
            "\n## [", 1
        )[0]
        self.assertIn("actions/setup-python", prior_patch)
        prior_release = changelog.split("## [1.0.0] - 2026-07-25", 1)[1].split(
            "\n## [", 1
        )[0]
        for shipped_fact in (
            "source-lock.json",
            "Mailpit",
            "sandbox-workers",
            "TestBundle v2",
            "NetworkPolicy",
            "production-images.yaml",
        ):
            self.assertIn(shipped_fact, prior_release)

    def test_third_party_actions_are_commit_pinned(self):
        workflow_paths = sorted((GITHUB / "workflows").glob("*.yml")) + sorted(
            (GITHUB / "workflows").glob("*.yaml")
        )
        self.assertTrue(workflow_paths)
        external_actions = 0
        for workflow_path in workflow_paths:
            for action_ref in self.workflow_action_refs(workflow_path):
                if action_ref.startswith("./") or action_ref.startswith("docker://"):
                    continue
                external_actions += 1
                self.assertRegex(
                    action_ref,
                    r"^[^@]+@[0-9a-f]{40}$",
                    (
                        "action must be pinned to a full commit SHA in "
                        f"{workflow_path.name}: {action_ref}"
                    ),
                )
        self.assertGreater(external_actions, 0)

    def test_shared_actions_use_one_verified_revision_across_workflows(self):
        revisions = {}
        workflow_paths = sorted((GITHUB / "workflows").glob("*.yml")) + sorted(
            (GITHUB / "workflows").glob("*.yaml")
        )
        for workflow_path in workflow_paths:
            for action_ref in self.workflow_action_refs(workflow_path):
                if action_ref.startswith("./") or action_ref.startswith("docker://"):
                    continue
                action, revision = action_ref.rsplit("@", 1)
                revisions.setdefault(action.lower(), {}).setdefault(revision, []).append(
                    workflow_path.name
                )

        conflicts = {
            action: references
            for action, references in revisions.items()
            if len(references) > 1
        }
        self.assertEqual(
            {},
            conflicts,
            "shared actions must use one already-verified immutable revision",
        )


if __name__ == "__main__":
    unittest.main()
