import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build-production-image-manifest.py"
COMPONENTS = {
    "frontend": "ghcr.io/coderushoj/croj-frontend",
    "backend": "ghcr.io/coderushoj/croj-backend",
    "judging-server": "ghcr.io/coderushoj/croj-judging-server",
    "sandbox": "ghcr.io/coderushoj/croj-sandbox",
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
        lock = {
            "schemaVersion": 1,
            "sources": {
                component: {"commit": revision}
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
            )
        self.manifests["docs"] = self.write_manifest(
            "docs",
            "ghcr.io/coderushoj/coderushoj-docs",
            "a" * 40,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self, component, repository, revision, **overrides):
        payload = {
            "repository": repository,
            "tag": "v1.0.0",
            "revision": revision,
            "digest": "sha256:" + component.encode().hex().ljust(64, "0")[:64],
            "platforms": ["linux/amd64", "linux/arm64"],
        }
        payload.update(overrides)
        path = self.base / f"{component}.json"
        path.write_text(json.dumps(payload))
        return path

    def run_script(self):
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
        for component, path in self.manifests.items():
            command.extend(["--manifest", f"{component}={path}"])
        return subprocess.run(command, text=True, capture_output=True, check=False)

    def test_generates_digest_only_helm_values_and_auditable_json(self):
        result = self.run_script()
        self.assertEqual(0, result.returncode, result.stderr)

        payload = json.loads((self.output / "production-images.json").read_text())
        self.assertEqual(1, payload["schemaVersion"])
        self.assertEqual("1.0.0", payload["version"])
        self.assertEqual(self.revisions["backend"], payload["images"]["backend"]["revision"])
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


if __name__ == "__main__":
    unittest.main()
