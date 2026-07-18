import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = (
    "scripts/lib.sh",
    "scripts/bootstrap.sh",
    "scripts/clone-repositories.sh",
    "scripts/cluster-up.sh",
    "scripts/cluster-down.sh",
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
