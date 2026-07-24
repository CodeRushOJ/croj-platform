import os
import pathlib
import shutil
import stat
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
    "scripts/checkout-sources.sh",
    "scripts/build-dev-images.sh",
    "scripts/load-dev-images.sh",
    "scripts/verify-test-bundle-contract.sh",
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

    def test_diagnostics_are_restricted_and_omit_application_logs(self):
        contents = (ROOT / "scripts/diagnostics.sh").read_text()
        self.assertIn("umask 077", contents)
        self.assertNotIn("kubectl logs", contents)
        self.assertNotIn("pods-logs.txt", contents)
        self.assertNotIn("redacted diagnostics", contents)
        self.assertIn("sensitive diagnostics", contents)

    def test_diagnostics_atomically_replace_unsafe_latest_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            project = pathlib.Path(directory) / "project"
            scripts = project / "scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts/diagnostics.sh", scripts / "diagnostics.sh")
            shutil.copy2(ROOT / "scripts/lib.sh", scripts / "lib.sh")

            mock_bin = pathlib.Path(directory) / "bin"
            mock_bin.mkdir()
            mock = "#!/usr/bin/env bash\nprintf 'mock diagnostic output\\n'\n"
            for command in ("kubectl", "helm"):
                executable = mock_bin / command
                executable.write_text(mock)
                executable.chmod(0o755)

            diagnostics_root = project / ".workspace/diagnostics"
            latest = diagnostics_root / "latest"
            latest.mkdir(parents=True)
            latest.chmod(0o755)
            stale_log = latest / "pods-logs.txt"
            stale_log.write_text("historical application secret\n")
            stale_log.chmod(0o644)

            env = os.environ.copy()
            env["PATH"] = f"{mock_bin}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                ["bash", str(scripts / "diagnostics.sh")],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse(stale_log.exists())
            self.assertEqual(
                0o700,
                stat.S_IMODE(latest.stat().st_mode),
            )
            files = [path for path in latest.iterdir() if path.is_file()]
            self.assertTrue(files, "diagnostics bundle has no files")
            for path in files:
                with self.subTest(path=path.name):
                    self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual([], list(diagnostics_root.glob(".latest.*")))

    def test_diagnostics_cleanup_retries_failed_bundle_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            project = pathlib.Path(directory) / "project"
            scripts = project / "scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts/diagnostics.sh", scripts / "diagnostics.sh")
            shutil.copy2(ROOT / "scripts/lib.sh", scripts / "lib.sh")

            mock_bin = pathlib.Path(directory) / "bin"
            mock_bin.mkdir()
            mock = "#!/usr/bin/env bash\nprintf 'mock diagnostic output\\n'\n"
            for command in ("kubectl", "helm"):
                executable = mock_bin / command
                executable.write_text(mock)
                executable.chmod(0o755)

            real_mv = shutil.which("mv")
            self.assertIsNotNone(real_mv)
            mv_attempts = pathlib.Path(directory) / "mv-attempts"
            fake_mv = mock_bin / "mv"
            fake_mv.write_text(
                "#!/usr/bin/env bash\n"
                "set -Eeuo pipefail\n"
                f"attempts_file={str(mv_attempts)!r}\n"
                'if [[ "${2:-}" == */latest ]]; then\n'
                '  attempts="$(cat "$attempts_file" 2>/dev/null || printf 0)"\n'
                '  attempts="$((attempts + 1))"\n'
                '  printf "%s\\n" "$attempts" >"$attempts_file"\n'
                '  if (( attempts <= 2 )); then exit 1; fi\n'
                "fi\n"
                f'exec {real_mv!r} "$@"\n'
            )
            fake_mv.chmod(0o755)

            diagnostics_root = project / ".workspace/diagnostics"
            latest = diagnostics_root / "latest"
            latest.mkdir(parents=True)
            sentinel = latest / "sentinel.txt"
            sentinel.write_text("previous diagnostics\n")

            env = os.environ.copy()
            env["PATH"] = f"{mock_bin}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                ["bash", str(scripts / "diagnostics.sh")],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertTrue(sentinel.exists(), "old diagnostics bundle was not restored")
            self.assertEqual([], list(diagnostics_root.glob(".latest.*")))

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
