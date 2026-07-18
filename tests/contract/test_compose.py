import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yaml"


class ComposeContractTest(unittest.TestCase):
    def test_compose_has_pinned_healthy_dependencies(self):
        self.assertTrue(COMPOSE.is_file(), "compose.yaml is missing")
        contents = COMPOSE.read_text()
        for service in ("mysql:", "redis:", "rocketmq-namesrv:", "rocketmq-broker:", "seaweedfs:"):
            self.assertIn(service, contents)
        for image in (
            "mysql:8.4.10",
            "redis:8.6.2-alpine",
            "apache/rocketmq:5.5.0",
            "chrislusf/seaweedfs:4.39",
        ):
            self.assertIn(image, contents)
        self.assertNotIn(":latest", contents)
        self.assertGreaterEqual(contents.count("healthcheck:"), 5)
        self.assertIn("secrets:", contents)

    def test_secret_generator_supports_files_only_mode(self):
        contents = (ROOT / "scripts/generate-secrets.sh").read_text()
        self.assertIn("--files-only", contents)

    @unittest.skipUnless(shutil.which("docker"), "Docker CLI is unavailable")
    def test_compose_configuration_parses_when_plugin_is_installed(self):
        version = subprocess.run(
            ["docker", "compose", "version"],
            text=True,
            capture_output=True,
            check=False,
        )
        if version.returncode != 0:
            self.skipTest("Docker Compose plugin is not installed")
        result = subprocess.run(
            ["docker", "compose", "--file", str(COMPOSE), "config", "--quiet"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
