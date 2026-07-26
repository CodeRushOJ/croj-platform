import json
import hashlib
import io
import os
import pathlib
import stat
import subprocess
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build-production-image-manifest.py"
VERIFY_RELEASE_SCRIPT = ROOT / "scripts" / "verify-release-assets.py"
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
        detect_release = workflow.index("Detect and verify existing release")
        registry_login = workflow.index("Log in to GHCR")
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
        self.assertLess(detect_release, registry_login)
        self.assertLess(download, validate)
        self.assertLess(download, verify_downloads)
        self.assertLess(verify_downloads, validate)
        self.assertLess(validate, detect_release)
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

    def test_release_is_a_resumable_fail_closed_transaction(self):
        workflow = RELEASE_WORKFLOW.read_text()
        detect_release = workflow.index("Detect and verify existing release")
        create_draft = workflow.index("Create verified draft GitHub Release")
        promote_docs = workflow.index("Publish verified documentation version tag")
        publish_release = workflow.index("Publish verified GitHub Release")
        draft_transaction = workflow[create_draft:promote_docs]
        promotion = workflow[promote_docs:publish_release]
        publication = workflow[publish_release:]

        self.assertNotIn("gh release " + "delete", workflow)
        self.assertIn("verify-release-assets.py", workflow[detect_release:create_draft])
        self.assertIn("steps.release-state.outputs.state == 'fresh'", workflow)
        self.assertIn("--draft", draft_transaction)
        self.assertIn('.state == "draft"', draft_transaction)
        self.assertNotIn("release delete", draft_transaction)
        self.assertNotIn("--asset-directory dist", workflow)
        self.assertIn(
            'gh release download "$GITHUB_REF_NAME"',
            draft_transaction,
        )
        self.assertIn(
            '--dir "$RUNNER_TEMP/created-release-assets"',
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
        self.assertIn("RECOVERED_DOCS_DIGEST", promotion)

        self.assertIn("gh release edit", publication)
        self.assertIn("--draft=false", publication)
        self.assertIn('.state == "published"', publication)

    def test_fresh_draft_is_verified_from_redownloaded_remote_assets(self):
        gh_log = self.base / "gh-commands"
        verifier_log = self.base / "verifier-commands"
        runner_temp = self.base / "runner"
        runner_temp.mkdir()
        result = self.run_workflow_step(
            "Create verified draft GitHub Release",
            {
                "gh": """
printf '%s\n' "$*" >> "$TEST_GH_LOG"
if [[ "$1" == "api" ]]; then
  printf '{"draft":true}\n'
fi
exit 0
""",
                "python3": """
printf '%s\n' "$*" >> "$TEST_VERIFIER_LOG"
printf '{"state":"draft"}\n'
""",
            },
            {
                "GH_TOKEN": "contract-test-token",
                "GITHUB_REPOSITORY": "CodeRushOJ/croj-platform",
                "GITHUB_REF_NAME": "v1.0.2",
                "GITHUB_SHA": "a" * 40,
                "RUNNER_TEMP": str(runner_temp),
                "TEST_GH_LOG": str(gh_log),
                "TEST_VERIFIER_LOG": str(verifier_log),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            "release download v1.0.2 --repo CodeRushOJ/croj-platform "
            f"--dir {runner_temp}/created-release-assets",
            gh_log.read_text(),
        )
        self.assertIn(
            f"--asset-directory {runner_temp}/created-release-assets",
            verifier_log.read_text(),
        )
        self.assertNotIn("--asset-directory dist", verifier_log.read_text())

    def test_final_publication_verifies_the_state_specific_remote_assets(self):
        for state, directory in (
            ("fresh", "created-release-assets"),
            ("draft", "existing-release-assets"),
        ):
            with self.subTest(state=state):
                gh_log = self.base / f"{state}-gh-commands"
                verifier_log = self.base / f"{state}-verifier-commands"
                runner_temp = self.base / f"{state}-runner"
                runner_temp.mkdir()
                result = self.run_workflow_step(
                    "Publish verified GitHub Release",
                    {
                        "gh": """
printf '%s\n' "$*" >> "$TEST_GH_LOG"
if [[ "$1" == "api" ]]; then
  printf '{"draft":false,"immutable":true}\n'
fi
exit 0
""",
                        "python3": """
printf '%s\n' "$*" >> "$TEST_VERIFIER_LOG"
printf '{"state":"published"}\n'
""",
                    },
                    {
                        "GH_TOKEN": "contract-test-token",
                        "GITHUB_REPOSITORY": "CodeRushOJ/croj-platform",
                        "GITHUB_REF_NAME": "v1.0.2",
                        "GITHUB_SHA": "a" * 40,
                        "RELEASE_STATE": state,
                        "RUNNER_TEMP": str(runner_temp),
                        "TEST_GH_LOG": str(gh_log),
                        "TEST_VERIFIER_LOG": str(verifier_log),
                    },
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(
                    f"--asset-directory {runner_temp}/{directory}",
                    verifier_log.read_text(),
                )
                self.assertNotIn("--asset-directory dist", verifier_log.read_text())

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
                "RELEASE_STATE": "fresh",
                "FRESH_DOCS_DIGEST": "sha256:" + "a" * 64,
                "RECOVERED_DOCS_DIGEST": "",
                "TEST_COMMAND_LOG": str(command_log),
            },
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertNotIn("imagetools create", command_log.read_text())

    def test_draft_resume_promotes_the_recovered_digest_not_a_rebuild(self):
        command_log = self.base / "docker-commands"
        inspect_count = self.base / "inspect-count"
        recovered_digest = "sha256:" + "d" * 64
        result = self.run_workflow_step(
            "Publish verified documentation version tag",
            {
                "docker": """
printf '%s\n' "$*" >> "$TEST_COMMAND_LOG"
if [[ "$*" == buildx\\ imagetools\\ inspect* ]]; then
  count=0
  if [[ -f "$TEST_INSPECT_COUNT" ]]; then
    count="$(<"$TEST_INSPECT_COUNT")"
  fi
  count=$((count + 1))
  printf '%s\n' "$count" > "$TEST_INSPECT_COUNT"
  if [[ "$count" == 1 ]]; then
    printf 'manifest unknown\n' >&2
    exit 1
  fi
  printf 'Digest: %s\n' "$RECOVERED_DOCS_DIGEST"
  exit 0
fi
exit 0
""",
            },
            {
                "DOCS_IMAGE": "ghcr.io/coderushoj/coderushoj-docs",
                "GITHUB_REF_NAME": "v1.0.2",
                "RELEASE_STATE": "draft",
                "FRESH_DOCS_DIGEST": "sha256:" + "b" * 64,
                "RECOVERED_DOCS_DIGEST": recovered_digest,
                "TEST_COMMAND_LOG": str(command_log),
                "TEST_INSPECT_COUNT": str(inspect_count),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        commands = command_log.read_text()
        self.assertIn(
            "imagetools create --tag "
            "ghcr.io/coderushoj/coderushoj-docs:v1.0.2 "
            f"ghcr.io/coderushoj/coderushoj-docs@{recovered_digest}",
            commands,
        )
        self.assertNotIn("sha256:" + "b" * 64, commands)

    def test_published_rerun_does_not_edit_or_delete_the_release(self):
        command_log = self.base / "gh-commands"
        result = self.run_workflow_step(
            "Publish verified GitHub Release",
            {
                "gh": """
printf '%s\n' "$*" >> "$TEST_COMMAND_LOG"
exit 90
""",
            },
            {
                "GH_TOKEN": "contract-test-token",
                "GITHUB_REPOSITORY": "CodeRushOJ/croj-platform",
                "GITHUB_REF_NAME": "v1.0.2",
                "RELEASE_STATE": "published",
                "TEST_COMMAND_LOG": str(command_log),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(command_log.exists() and command_log.read_text())


class ExistingReleaseAssetTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.temporary.name)
        self.assets = self.base / "assets"
        self.assets.mkdir()
        self.version = "1.0.0"
        self.tag = "v1.0.0"
        self.revision = "a" * 40
        self.docs_digest = "sha256:" + "d" * 64
        self.version_file = self.base / "VERSION"
        self.version_file.write_text(self.version + "\n")
        self.lock = self.base / "source-lock.json"
        self.lock_payload = {
            "schemaVersion": 3,
            "sources": {
                component: {
                    "commit": str(index) * 40,
                    "releaseTag": {
                        "frontend": "v1.0.1",
                        "backend": "v1.0.3",
                        "judging-server": "v1.0.2",
                        "sandbox": "v1.0.2",
                    }[component],
                }
                for index, component in enumerate(COMPONENTS, start=1)
            },
        }
        self.lock.write_text(json.dumps(self.lock_payload))
        self.changelog = self.base / "CHANGELOG.md"
        self.changelog.write_text(
            "# Changelog\n\n"
            "## [1.0.0]\n\n"
            "### Features\n\n"
            "Recovered release.\n\n"
            "## [0.9.0]\n\n"
            "Previous release.\n"
        )
        self.chart_directories = {}
        for chart_name in ("coderushoj", "coderushoj-infra"):
            chart_directory = self.base / chart_name
            chart_directory.mkdir()
            (chart_directory / "Chart.yaml").write_text(
                "apiVersion: v2\n"
                f"name: {chart_name}\n"
                f"version: {self.version}\n"
                f"appVersion: {self.version}\n"
            )
            (chart_directory / "values.yaml").write_text("replicaCount: 1\n")
            self.chart_directories[chart_name] = chart_directory
            self.write_chart_archive(chart_name)

        images = {}
        for index, (component, repository) in enumerate(COMPONENTS.items(), start=1):
            images[component] = {
                "repository": repository,
                "tag": self.lock_payload["sources"][component]["releaseTag"],
                "revision": self.lock_payload["sources"][component]["commit"],
                "digest": "sha256:" + str(index) * 64,
                "platforms": ["linux/amd64", "linux/arm64"],
            }
        images["docs"] = {
            "repository": "ghcr.io/coderushoj/coderushoj-docs",
            "tag": self.tag,
            "revision": self.revision,
            "digest": self.docs_digest,
            "platforms": ["linux/amd64", "linux/arm64"],
        }
        self.production_images = {
            "schemaVersion": 1,
            "version": self.version,
            "images": images,
        }
        (self.assets / "production-images.json").write_text(
            json.dumps(self.production_images, indent=2, sort_keys=True) + "\n"
        )
        (self.assets / "docs-image.json").write_text(
            json.dumps(images["docs"], indent=2, sort_keys=True) + "\n"
        )
        yaml_lines = ["images:"]
        chart_keys = {
            "frontend": "frontend",
            "backend": "backend",
            "judging-server": "judgingServer",
            "sandbox": "sandbox",
            "docs": "docs",
        }
        for component in (
            "frontend",
            "backend",
            "judging-server",
            "sandbox",
            "docs",
        ):
            yaml_lines.extend(
                (
                    f"  {chart_keys[component]}:",
                    '    tag: ""',
                    f'    digest: "{images[component]["digest"]}"',
                )
            )
        (self.assets / "production-images.yaml").write_text(
            "\n".join(yaml_lines) + "\n"
        )
        (self.assets / "production-render.yaml").write_text(
            "apiVersion: v1\nkind: List\nitems: []\n"
        )
        (self.assets / "release-notes.md").write_text(
            "## [1.0.0]\n\n### Features\n\nRecovered release.\n\n"
        )
        self.preflight = self.base / "component-images.json"
        self.preflight.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "version": self.version,
                    "images": {
                        component: images[component] for component in COMPONENTS
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        self.helm = self.base / "helm"
        self.helm.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'printf "apiVersion: v1\\nkind: List\\nitems: []\\n"\n'
        )
        self.helm.chmod(self.helm.stat().st_mode | stat.S_IXUSR)
        self.write_checksums()
        self.release_json = self.base / "release.json"
        self.write_release_json(draft=True, immutable=False)

    def tearDown(self):
        self.temporary.cleanup()

    def write_chart_archive(self, chart_name):
        archive = self.assets / f"{chart_name}-{self.version}.tgz"
        with tarfile.open(archive, "w:gz") as package:
            for path in sorted(self.chart_directories[chart_name].iterdir()):
                data = path.read_bytes()
                info = tarfile.TarInfo(f"{chart_name}/{path.name}")
                info.size = len(data)
                info.mode = 0o644
                package.addfile(info, io.BytesIO(data))

    def write_checksums(self):
        checksum_file = self.assets / "SHA256SUMS"
        names = sorted(path.name for path in self.assets.iterdir())
        checksum_file.write_text(
            "".join(
                f"{hashlib.sha256((self.assets / name).read_bytes()).hexdigest()}  ./{name}\n"
                for name in names
            )
        )

    def write_release_json(self, *, draft, immutable, author="github-actions[bot]"):
        assets = [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "state": "uploaded",
                "digest": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
            }
            for path in sorted(self.assets.iterdir())
        ]
        self.release_json.write_text(
            json.dumps(
                {
                    "tag_name": self.tag,
                    "name": f"CodeRushOJ {self.tag}",
                    "draft": draft,
                    "prerelease": False,
                    "immutable": immutable,
                    "author": {"login": author},
                    "assets": assets,
                }
            )
        )

    def run_verifier(self):
        return subprocess.run(
            [
                "python3",
                str(VERIFY_RELEASE_SCRIPT),
                "--release-json",
                str(self.release_json),
                "--asset-directory",
                str(self.assets),
                "--version-file",
                str(self.version_file),
                "--source-lock",
                str(self.lock),
                "--component-preflight",
                str(self.preflight),
                "--platform-revision",
                self.revision,
                "--changelog",
                str(self.changelog),
                "--application-chart",
                str(self.chart_directories["coderushoj"]),
                "--infrastructure-chart",
                str(self.chart_directories["coderushoj-infra"]),
                "--helm",
                str(self.helm),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_accepts_exact_draft_and_returns_its_docs_digest(self):
        result = self.run_verifier()
        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("draft", output["state"])
        self.assertEqual(self.docs_digest, output["docsDigest"])

    def test_accepts_exact_immutable_published_release(self):
        self.write_release_json(draft=False, immutable=True)
        result = self.run_verifier()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("published", json.loads(result.stdout)["state"])

    def test_rejects_public_release_with_mismatched_author_or_mutability(self):
        for immutable, author in (
            (False, "github-actions[bot]"),
            (True, "octocat"),
        ):
            with self.subTest(immutable=immutable, author=author):
                self.write_release_json(
                    draft=False,
                    immutable=immutable,
                    author=author,
                )
                result = self.run_verifier()
                self.assertNotEqual(0, result.returncode)

    def test_rejects_release_asset_metadata_without_server_digest(self):
        payload = json.loads(self.release_json.read_text())
        del payload["assets"][0]["digest"]
        self.release_json.write_text(json.dumps(payload))
        result = self.run_verifier()
        self.assertNotEqual(0, result.returncode)

    def test_rejects_asset_checksum_manifest_and_chart_drift(self):
        cases = (
            "extra-asset",
            "checksum",
            "manifest",
            "component-digest",
            "notes",
            "render",
            "chart",
        )
        for case in cases:
            with self.subTest(case=case):
                original_assets = {
                    path.name: path.read_bytes() for path in self.assets.iterdir()
                }
                if case == "extra-asset":
                    (self.assets / "unexpected.txt").write_text("unexpected")
                elif case == "checksum":
                    (self.assets / "release-notes.md").write_text("tampered")
                elif case == "manifest":
                    payload = json.loads(
                        (self.assets / "production-images.json").read_text()
                    )
                    payload["images"]["docs"]["revision"] = "f" * 40
                    (self.assets / "production-images.json").write_text(
                        json.dumps(payload)
                    )
                    self.write_checksums()
                elif case == "component-digest":
                    payload = json.loads(
                        (self.assets / "production-images.json").read_text()
                    )
                    payload["images"]["frontend"]["digest"] = "sha256:" + "f" * 64
                    (self.assets / "production-images.json").write_text(
                        json.dumps(payload)
                    )
                    self.write_checksums()
                elif case == "notes":
                    (self.assets / "release-notes.md").write_text(
                        "## [1.0.0]\n\nTampered notes.\n"
                    )
                    self.write_checksums()
                elif case == "render":
                    (self.assets / "production-render.yaml").write_text(
                        "apiVersion: v1\nkind: ConfigMap\nmetadata: {}\n"
                    )
                    self.write_checksums()
                else:
                    (self.chart_directories["coderushoj"] / "values.yaml").write_text(
                        "replicaCount: 2\n"
                    )
                self.write_release_json(draft=True, immutable=False)
                result = self.run_verifier()
                self.assertNotEqual(0, result.returncode)
                for path in list(self.assets.iterdir()):
                    path.unlink()
                for name, data in original_assets.items():
                    (self.assets / name).write_bytes(data)
                (self.chart_directories["coderushoj"] / "values.yaml").write_text(
                    "replicaCount: 1\n"
                )


if __name__ == "__main__":
    unittest.main()
