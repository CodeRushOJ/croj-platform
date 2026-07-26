import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build-production-image-manifest.py"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"
COMPONENTS = {
    "frontend": "ghcr.io/coderushoj/croj-frontend",
    "backend": "ghcr.io/coderushoj/croj-backend",
    "judging-server": "ghcr.io/coderushoj/croj-judging-server",
    "sandbox": "ghcr.io/coderushoj/croj-sandbox",
}
RELEASE_MANIFESTS = {
    "frontend": (
        "image-artifact.json",
        "5af165529a4b8882dc492acf9886c424cf2aaebd43a7a77ea3c76018674d9a17",
    ),
    "backend": (
        "backend-image.json",
        "9474f05787b758d76e6115a6c8af329ab30203d141f11996558897b074d505ed",
    ),
    "judging-server": (
        "judging-server-image.json",
        "813d063d844fb0e19554fa15589d24c6052dbd85aa3cafc1dfdb4b5af2c71fbd",
    ),
    "sandbox": (
        "sandbox-image.json",
        "3b729035b7a7760ed25d86905c4db2da76bb21886df2798b0db0f4cdeb14e0ef",
    ),
}


class ReleaseImageManifestTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.temporary.name)
        self.output = self.base / "output"
        self.revisions = {
            component: str(index) * 40
            for index, component in enumerate(COMPONENTS, start=1)
        }
        self.release_tags = {
            "frontend": "v1.0.1",
            "backend": "v1.0.3",
            "judging-server": "v1.0.2",
            "sandbox": "v1.0.2",
        }
        lock = {
            "schemaVersion": 3,
            "sources": {
                component: {
                    "commit": revision,
                    "releaseTag": self.release_tags[component],
                    "releaseManifestAsset": RELEASE_MANIFESTS[component][0],
                    "releaseManifestSha256": RELEASE_MANIFESTS[component][1],
                }
                for component, revision in self.revisions.items()
            },
        }
        self.lock = self.base / "source-lock.json"
        self.lock.write_text(json.dumps(lock))
        self.manifests = {}
        for component, repository in COMPONENTS.items():
            self.manifests[component] = self.write_manifest(
                component,
                repository,
                self.revisions[component],
                tag=self.release_tags[component],
            )
        self.manifests["docs"] = self.write_manifest(
            "docs",
            "ghcr.io/coderushoj/coderushoj-docs",
            "a" * 40,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(
        self, component, repository, revision, tag="v1.0.0", **overrides
    ):
        payload = {
            "repository": repository,
            "tag": tag,
            "revision": revision,
            "digest": "sha256:" + component.encode().hex().ljust(64, "0")[:64],
            "platforms": ["linux/amd64", "linux/arm64"],
        }
        payload.update(overrides)
        path = self.base / f"{component}.json"
        path.write_text(json.dumps(payload))
        return path

    def run_script(self, *, components_only=False):
        command = [
            "python3",
            str(SCRIPT),
            "--version",
            "1.0.0",
            "--source-lock",
            str(self.lock),
            "--platform-revision",
            "a" * 40,
            "--output-directory",
            str(self.output),
        ]
        if components_only:
            command.append("--components-only")
        for component, path in self.manifests.items():
            if components_only and component == "docs":
                continue
            command.extend(["--manifest", f"{component}={path}"])
        return subprocess.run(command, text=True, capture_output=True, check=False)

    def workflow_step_script(self, step_name):
        lines = RELEASE_WORKFLOW.read_text().splitlines()
        step = lines.index(f"      - name: {step_name}")
        run = lines.index("        run: |", step)
        script_lines = []
        for line in lines[run + 1 :]:
            if line.startswith("      - name: "):
                break
            script_lines.append(line[10:] if line.startswith("          ") else line)
        return "\n".join(script_lines) + "\n"

    def run_workflow_step(self, step_name, executables, environment):
        bin_directory = self.base / "bin"
        bin_directory.mkdir(exist_ok=True)
        for name, contents in executables.items():
            executable = bin_directory / name
            executable.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + contents)
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        run_environment = os.environ.copy()
        run_environment.update(environment)
        run_environment["PATH"] = (
            f"{bin_directory}{os.pathsep}{run_environment['PATH']}"
        )
        return subprocess.run(
            ["bash", "-c", self.workflow_step_script(step_name)],
            cwd=ROOT,
            env=run_environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_generates_digest_only_helm_values_and_auditable_json(self):
        result = self.run_script()
        self.assertEqual(0, result.returncode, result.stderr)

        payload = json.loads((self.output / "production-images.json").read_text())
        self.assertEqual(1, payload["schemaVersion"])
        self.assertEqual("1.0.0", payload["version"])
        self.assertEqual(self.revisions["backend"], payload["images"]["backend"]["revision"])
        self.assertEqual("v1.0.1", payload["images"]["frontend"]["tag"])
        self.assertEqual("v1.0.3", payload["images"]["backend"]["tag"])
        self.assertEqual(
            ["linux/amd64", "linux/arm64"],
            payload["images"]["sandbox"]["platforms"],
        )

        values = (self.output / "production-images.yaml").read_text()
        for chart_key in ("frontend", "backend", "judgingServer", "sandbox", "docs"):
            self.assertIn(f"  {chart_key}:\n    tag: \"\"\n    digest: \"sha256:", values)

    def test_rejects_revision_platform_tag_and_digest_drift(self):
        invalid_cases = (
            ("backend", {"revision": "f" * 40}),
            ("frontend", {"platforms": ["linux/amd64"]}),
            ("sandbox", {"tag": "latest"}),
            ("docs", {"digest": "sha256:not-a-digest"}),
        )
        for component, override in invalid_cases:
            with self.subTest(component=component, override=override):
                original = self.manifests[component].read_text()
                payload = json.loads(original)
                payload.update(override)
                self.manifests[component].write_text(json.dumps(payload))
                result = self.run_script()
                self.assertNotEqual(0, result.returncode)
                self.manifests[component].write_text(original)

    def test_validates_components_before_the_documentation_image_exists(self):
        result = self.run_script(components_only=True)
        self.assertEqual(0, result.returncode, result.stderr)

        payload = json.loads((self.output / "component-images.json").read_text())
        self.assertEqual(set(COMPONENTS), set(payload["images"]))
        self.assertNotIn("docs", payload["images"])
        self.assertFalse((self.output / "production-images.yaml").exists())

    def test_release_downloads_public_release_assets_before_registry_mutation(self):
        workflow = RELEASE_WORKFLOW.read_text()
        self.assertIn(
            "frontend_release_tag=\"$(jq -er "
            "'.sources.frontend.releaseTag' config/source-lock.json)\"",
            workflow,
        )
        self.assertIn(
            "frontend_release_manifest_asset=\"$(jq -er "
            "'.sources.frontend.releaseManifestAsset' config/source-lock.json)\"",
            workflow,
        )
        self.assertIn(
            "frontend_release_manifest_sha256=\"$(jq -er "
            "'.sources.frontend.releaseManifestSha256' config/source-lock.json)\"",
            workflow,
        )
        self.assertIn(
            '"https://github.com/CodeRushOJ/croj-frontend/releases/download/'
            '$frontend_release_tag/$frontend_release_manifest_asset"',
            workflow,
        )
        self.assertIn(
            "printf '%s  %s\\n' \"$expected_sha256\" \"$destination\" "
            "| sha256sum --check --status",
            workflow,
        )
        self.assertNotIn("gh run download", workflow)
        download = workflow.index("Download the four public component release manifests")
        verify_downloads = workflow.index("Verify downloaded release manifest checksums")
        validate = workflow.index("Validate immutable component inputs before publication")
        registry = workflow.index("Verify component registry indexes before publication")
        publish_docs = workflow.index(
            "Build and publish staged multi-architecture documentation image"
        )
        create_draft = workflow.index("Create verified draft GitHub Release")
        promote_docs = workflow.index("Publish verified documentation version tag")
        publish_release = workflow.index("Publish verified GitHub Release")
        self.assertLess(download, validate)
        self.assertLess(download, verify_downloads)
        self.assertLess(verify_downloads, validate)
        self.assertLess(validate, registry)
        self.assertLess(registry, publish_docs)
        self.assertLess(publish_docs, create_draft)
        self.assertLess(create_draft, promote_docs)
        self.assertLess(promote_docs, publish_release)
        self.assertIn(
            "${{ env.DOCS_IMAGE }}:sha-${{ github.sha }}",
            workflow,
        )
        staged_build = workflow[publish_docs:promote_docs]
        self.assertNotIn(
            "${{ env.DOCS_IMAGE }}:${{ github.ref_name }}",
            staged_build,
        )

    def test_release_is_a_fail_closed_draft_promotion_transaction(self):
        workflow = RELEASE_WORKFLOW.read_text()
        create_draft = workflow.index("Create verified draft GitHub Release")
        promote_docs = workflow.index("Publish verified documentation version tag")
        publish_release = workflow.index("Publish verified GitHub Release")
        draft_transaction = workflow[create_draft:promote_docs]
        promotion = workflow[promote_docs:publish_release]
        publication = workflow[publish_release:]

        self.assertIn("--draft", draft_transaction)
        self.assertIn(".draft == true", draft_transaction)
        self.assertIn("existing_release_draft", draft_transaction)
        self.assertIn(
            '[[ "$existing_release_draft" == "true" ]]',
            draft_transaction,
        )
        self.assertIn("gh release delete", draft_transaction)
        self.assertIn(
            "refusing to replace existing published release",
            draft_transaction,
        )

        inspect = promotion.index("docker buildx imagetools inspect")
        compare = promotion.index('[[ "$existing_docs_digest" != "$docs_digest" ]]')
        fail = promotion.index("exit 1", compare)
        create = promotion.index("docker buildx imagetools create")
        self.assertLess(inspect, compare)
        self.assertLess(compare, fail)
        self.assertLess(fail, create)
        self.assertIn(
            "documentation version tag already has verified digest",
            promotion,
        )

        self.assertIn("gh release edit", publication)
        self.assertIn("--draft=false", publication)
        self.assertIn(".draft == false", publication)
        self.assertIn(".immutable == true", publication)

    def test_docs_promotion_does_not_overwrite_an_existing_different_digest(self):
        command_log = self.base / "docker-commands"
        result = self.run_workflow_step(
            "Publish verified documentation version tag",
            {
                "docker": """
printf '%s\n' "$*" >> "$TEST_COMMAND_LOG"
if [[ "$*" == buildx\\ imagetools\\ inspect* ]]; then
  printf 'Digest: sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
  exit 0
fi
exit 0
""",
            },
            {
                "DOCS_IMAGE": "ghcr.io/coderushoj/coderushoj-docs",
                "GITHUB_REF_NAME": "v1.0.2",
                "IMAGE_DIGEST": "sha256:" + "a" * 64,
                "TEST_COMMAND_LOG": str(command_log),
            },
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertNotIn("imagetools create", command_log.read_text())

    def test_draft_creation_does_not_delete_an_existing_published_release(self):
        command_log = self.base / "gh-commands"
        result = self.run_workflow_step(
            "Create verified draft GitHub Release",
            {
                "gh": """
printf '%s\n' "$*" >> "$TEST_COMMAND_LOG"
if [[ "$1" == "api" ]]; then
  printf '{"draft":false}\n'
  exit 0
fi
exit 90
""",
            },
            {
                "GH_TOKEN": "contract-test-token",
                "GITHUB_REPOSITORY": "CodeRushOJ/croj-platform",
                "GITHUB_REF_NAME": "v1.0.2",
                "TEST_COMMAND_LOG": str(command_log),
            },
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to replace existing published release", result.stderr)
        self.assertNotIn("release delete", command_log.read_text())


if __name__ == "__main__":
    unittest.main()
