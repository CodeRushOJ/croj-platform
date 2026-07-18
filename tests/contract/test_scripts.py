import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = (
    "scripts/lib.sh",
    "scripts/bootstrap.sh",
    "scripts/clone-repositories.sh",
    "scripts/cluster-up.sh",
    "scripts/cluster-down.sh",
    "scripts/install-gateway.sh",
    "scripts/generate-secrets.sh",
    "scripts/diagnostics.sh",
    "scripts/deploy.sh",
    "tests/smoke/platform.sh",
)


class ScriptContractTest(unittest.TestCase):
    def test_shell_scripts_are_strict_and_parse(self):
        for relative_path in SCRIPTS:
            with self.subTest(script=relative_path):
                path = ROOT / relative_path
                self.assertTrue(path.is_file(), f"required script is missing: {relative_path}")
                contents = path.read_text()
                self.assertTrue(contents.startswith("#!/usr/bin/env bash\n"))
                self.assertIn("set -Eeuo pipefail", contents)
                result = subprocess.run(
                    ["bash", "-n", str(path)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_repository_list_is_stable_and_offline(self):
        script = ROOT / "scripts/clone-repositories.sh"
        self.assertTrue(script.is_file(), "clone-repositories.sh is missing")
        result = subprocess.run(
            ["bash", str(script), "--print"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                ".github",
                "croj-frontend",
                "croj-backend",
                "croj-judging-server",
                "croj-sandbox",
            ],
            result.stdout.splitlines(),
        )

    def test_bootstrap_avoids_implicit_homebrew_updates(self):
        contents = (ROOT / "scripts/bootstrap.sh").read_text()
        self.assertIn("HOMEBREW_NO_AUTO_UPDATE=1 brew bundle", contents)

    def test_cluster_up_configures_vm_dns(self):
        contents = (ROOT / "scripts/cluster-up.sh").read_text()
        self.assertIn('--dns "$dns_primary" --dns "$dns_secondary"', contents)
        self.assertIn("/run/systemd/resolve/stub-resolv.conf", contents)
        self.assertIn("colima ssh", contents)

    def test_smoke_test_avoids_quick_exit_pipe_with_pipefail(self):
        contents = (ROOT / "tests/smoke/platform.sh").read_text()
        self.assertNotIn("| grep -Fxq submission-topic", contents)
        self.assertIn("rocketmq_topics=", contents)
        self.assertIn("running_images=", contents)
        self.assertIn("--protocol=TCP --host=127.0.0.1", contents)
        self.assertIn("for mysql_attempt in {1..30}", contents)
        self.assertIn("sleep 2", contents)

    def test_helm_rollback_flag_supports_helm_3_and_4(self):
        lib = ROOT / "scripts/lib.sh"
        for version, expected in (("v3.19.0", "--atomic"), ("v4.2.3", "--rollback-on-failure")):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp_dir:
                fake_helm = pathlib.Path(temp_dir) / "helm"
                fake_helm.write_text(f'#!/usr/bin/env bash\nprintf \'{version}\\n\'\n')
                fake_helm.chmod(0o755)
                result = subprocess.run(
                    ["bash", "-c", f'source "{lib}"; helm_rollback_flag'],
                    env={"PATH": f"{temp_dir}:/usr/bin:/bin"},
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, result.stdout.strip())

    def test_deploy_uses_version_aware_helm_rollback_flag(self):
        deploy = (ROOT / "scripts/deploy.sh").read_text()
        self.assertIn("helm_rollback_flag", deploy)
        self.assertNotIn("  --rollback-on-failure \\\n", deploy)

    @unittest.skipUnless(shutil.which("shellcheck"), "ShellCheck is not installed")
    def test_shellcheck_has_no_findings(self):
        result = subprocess.run(
            ["shellcheck", *[str(ROOT / path) for path in SCRIPTS]],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
