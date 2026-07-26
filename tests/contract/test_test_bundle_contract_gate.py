import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify-test-bundle-contract.sh"
VALIDATOR = ROOT / "scripts/verify-source-lock.py"


class TestBundleContractGateTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.temporary_directory.name)
        self.sources = self.base / "sources"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.lock = self.base / "source-lock.json"
        self.backend_commit = "b" * 40
        self.judging_commit = "c" * 40
        repositories = {
            "frontend": (
                "croj-frontend",
                "a" * 40,
                "ghcr.io/coderushoj/croj-frontend:dev",
                "image-artifact.json",
            ),
            "backend": (
                "croj-backend",
                self.backend_commit,
                "ghcr.io/coderushoj/croj-backend:dev",
                "backend-image.json",
            ),
            "judging-server": (
                "croj-judging-server",
                self.judging_commit,
                "ghcr.io/coderushoj/croj-judging-server:dev",
                "judging-server-image.json",
            ),
            "sandbox": (
                "croj-sandbox",
                "d" * 40,
                "ghcr.io/coderushoj/croj-sandbox:dev",
                "sandbox-image.json",
            ),
        }
        sources = {}
        for component, (repository, commit, image, release_manifest_asset) in repositories.items():
            sources[component] = {
                "repository": f"https://github.com/CodeRushOJ/{repository}.git",
                "commit": commit,
                "releaseTag": "v1.0.0",
                "context": ".",
                "dockerfile": "Dockerfile",
                "image": image,
                "releaseManifestAsset": release_manifest_asset,
                "releaseManifestSha256": "e" * 64,
            }
        self.lock.write_text(json.dumps({"schemaVersion": 3, "sources": sources}))

        self.backend = self.sources / "backend" / self.backend_commit
        self.judging = self.sources / "judging-server" / self.judging_commit
        self.backend.mkdir(parents=True)
        self.judging.mkdir(parents=True)
        (self.judging / "go.mod").write_text("module example.test/judging\n")
        self.maven_arguments = self.base / "maven-arguments"
        self.go_arguments = self.base / "go-arguments"
        self.go_artifact = self.base / "go-artifact"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_executable(self, path, contents):
        path.write_text("#!/usr/bin/env bash\nset -Eeuo pipefail\n" + contents)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def environment(self):
        environment = os.environ.copy()
        environment["PATH"] = f"{self.bin}{os.pathsep}{environment['PATH']}"
        environment["TEST_MAVEN_ARGUMENTS"] = str(self.maven_arguments)
        environment["TEST_GO_ARGUMENTS"] = str(self.go_arguments)
        environment["TEST_GO_ARTIFACT"] = str(self.go_artifact)
        return environment

    def run_gate(self):
        return subprocess.run(
            [
                str(SCRIPT),
                "--lock",
                str(self.lock),
                "--sources-root",
                str(self.sources),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=self.environment(),
        )

    def test_runs_backend_export_then_judging_consumer_against_exact_artifact(self):
        self.write_executable(
            self.backend / "mvnw",
            """
printf '%s\\n' "$@" > "$TEST_MAVEN_ARGUMENTS"
for argument in "$@"; do
  case "$argument" in
    -Dcroj.contract.output=*) output="${argument#*=}" ;;
  esac
done
[[ -n "${output:-}" ]]
mkdir -p "$(dirname "$output")"
printf 'backend-produced-zip' > "$output"
""",
        )
        self.write_executable(
            self.bin / "go",
            """
printf '%s\\n' "$@" > "$TEST_GO_ARGUMENTS"
[[ -n "${CROJ_BACKEND_TEST_BUNDLE_V1:-}" ]]
cp "$CROJ_BACKEND_TEST_BUNDLE_V1" "$TEST_GO_ARTIFACT"
""",
        )

        result = self.run_gate()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("-Dtest=TestBundleContractExportTest", self.maven_arguments.read_text())
        self.assertIn("-Dcroj.contract.output=", self.maven_arguments.read_text())
        self.assertEqual("test\n-race\n-count=1\n./internal/bundle\n", self.go_arguments.read_text())
        self.assertEqual(b"backend-produced-zip", self.go_artifact.read_bytes())

    def test_fails_closed_when_backend_export_does_not_create_an_artifact(self):
        self.write_executable(
            self.backend / "mvnw",
            'printf "%s\\n" "$@" > "$TEST_MAVEN_ARGUMENTS"\n',
        )
        self.write_executable(self.bin / "go", "exit 0\n")

        result = self.run_gate()

        self.assertNotEqual(0, result.returncode)
        self.assertIn("did not produce", result.stderr)


if __name__ == "__main__":
    unittest.main()
