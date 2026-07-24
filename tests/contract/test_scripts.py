import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import time
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
    def diagnostics_fixture(self, directory):
        project = pathlib.Path(directory) / "project"
        scripts = project / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts/diagnostics.sh", scripts / "diagnostics.sh")
        shutil.copy2(ROOT / "scripts/lib.sh", scripts / "lib.sh")

        mock_bin = pathlib.Path(directory) / "bin"
        mock_bin.mkdir()
        mock = """#!/usr/bin/env bash
set -Eeuo pipefail
if [[ -n "${MOCK_DIAGNOSTICS_DELAY:-}" ]]; then
  sleep "$MOCK_DIAGNOSTICS_DELAY"
fi
if [[ -n "${MOCK_DIAGNOSTICS_LATEST_ROOT:-}" \
  && -n "${MOCK_DIAGNOSTICS_RECOVERY_VIOLATION:-}" \
  && ! -L "$MOCK_DIAGNOSTICS_LATEST_ROOT/latest" ]]; then
  printf 'capture started before recovery\\n' >"$MOCK_DIAGNOSTICS_RECOVERY_VIOLATION"
fi
printf 'mock diagnostic output\\n'
"""
        for command in ("kubectl", "helm"):
            executable = mock_bin / command
            executable.write_text(mock)
            executable.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{mock_bin}{os.pathsep}{env['PATH']}"
        env["CODERUSHOJ_DIAGNOSTICS_LOCK_TIMEOUT_SECONDS"] = "10"
        env["CODERUSHOJ_DIAGNOSTICS_STALE_LOCK_SECONDS"] = "1"
        env["CODERUSHOJ_DIAGNOSTICS_RETAIN"] = "2"
        return project, scripts / "diagnostics.sh", env

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
        self.assertIn("-name pods-logs.txt -exec rm -f", contents)
        self.assertNotIn("redacted diagnostics", contents)
        self.assertIn("sensitive diagnostics", contents)

    def test_diagnostics_atomically_replace_unsafe_latest_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)

            diagnostics_root = project / ".workspace/diagnostics"
            latest = diagnostics_root / "latest"
            latest.mkdir(parents=True)
            latest.chmod(0o755)
            stale_log = latest / "pods-logs.txt"
            stale_log.write_text("historical application secret\n")
            stale_log.chmod(0o644)

            result = subprocess.run(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse(stale_log.exists())
            self.assertTrue(latest.is_symlink())
            self.assertEqual(
                0o700,
                stat.S_IMODE(latest.stat().st_mode),
            )
            files = [path for path in latest.iterdir() if path.is_file()]
            self.assertTrue(files, "diagnostics bundle has no files")
            for path in files:
                with self.subTest(path=path.name):
                    self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(
                [],
                list(diagnostics_root.rglob("pods-logs.txt")),
            )
            self.assertFalse((diagnostics_root / ".publish-journal").exists())
            self.assertFalse((diagnostics_root / ".publish.lock").exists())

    def test_diagnostics_recovers_sigkill_journal_and_stale_lock_before_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)

            diagnostics_root = project / ".workspace/diagnostics"
            bundles = diagnostics_root / "bundles"
            bundles.mkdir(parents=True)
            previous = diagnostics_root / ".legacy.previous.crash"
            previous.mkdir()
            sentinel = previous / "sentinel.txt"
            sentinel.write_text("previous diagnostics\n")
            (previous / "pods-logs.txt").write_text("stale secret log\n")

            journal = diagnostics_root / ".publish-journal"
            journal.mkdir()
            (journal / "operation").write_text("legacy-migration\n")
            (journal / "previous").write_text(".legacy.previous.crash\n")
            (journal / "target").write_text("legacy-crash\n")

            stale_lock = diagnostics_root / ".publish.lock"
            stale_lock.mkdir()
            (stale_lock / "pid").write_text("999999\n")
            (stale_lock / "process-start").write_text("dead process\n")
            (stale_lock / "token").write_text("dead-token\n")
            (stale_lock / "created").write_text("1\n")

            violation = pathlib.Path(directory) / "recovery-violation"
            env["MOCK_DIAGNOSTICS_LATEST_ROOT"] = str(diagnostics_root)
            env["MOCK_DIAGNOSTICS_RECOVERY_VIOLATION"] = str(violation)

            result = subprocess.run(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse(violation.exists())
            self.assertTrue((bundles / "legacy-crash/sentinel.txt").exists())
            self.assertFalse(previous.exists())
            self.assertFalse(journal.exists())
            self.assertFalse(stale_lock.exists())
            self.assertTrue((diagnostics_root / "latest").is_symlink())
            self.assertEqual([], list(diagnostics_root.rglob("pods-logs.txt")))

    def test_diagnostics_lock_serializes_concurrent_publishers(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            env["MOCK_DIAGNOSTICS_DELAY"] = "0.03"

            processes = [
                subprocess.Popen(
                    ["bash", str(diagnostics_script)],
                    cwd=project,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(0, process.returncode, stdout + stderr)

            diagnostics_root = project / ".workspace/diagnostics"
            latest = diagnostics_root / "latest"
            self.assertTrue(latest.is_symlink())
            self.assertTrue(latest.resolve().is_dir())
            bundles = [
                path
                for path in (diagnostics_root / "bundles").iterdir()
                if path.is_dir() and not path.name.startswith(".staging.")
            ]
            self.assertEqual(2, len(bundles))
            self.assertFalse((diagnostics_root / ".publish.lock").exists())
            self.assertEqual(
                [],
                [
                    path
                    for path in diagnostics_root.rglob("latest")
                    if path != latest
                ],
            )

    def test_diagnostics_reclaims_incomplete_owner_after_grace(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            env["CODERUSHOJ_DIAGNOSTICS_LOCK_TIMEOUT_SECONDS"] = "3"

            diagnostics_root = project / ".workspace/diagnostics"
            stale_lock = diagnostics_root / ".publish.lock"
            stale_lock.mkdir(parents=True)
            (stale_lock / "pid").write_text(f"{os.getpid()}\n")
            (stale_lock / "created").write_text("1\n")

            result = subprocess.run(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue((diagnostics_root / "latest").is_symlink())
            self.assertFalse(stale_lock.exists())

    def test_diagnostics_steady_state_pointer_is_continuous_and_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            first = subprocess.run(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)

            diagnostics_root = project / ".workspace/diagnostics"
            latest = diagnostics_root / "latest"
            first_bundle = latest.resolve()
            env["MOCK_DIAGNOSTICS_DELAY"] = "0.03"
            second = subprocess.Popen(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            pointer_was_broken = False
            while second.poll() is None:
                if not latest.is_symlink() or not latest.exists():
                    pointer_was_broken = True
                    break
                time.sleep(0.002)
            stdout, stderr = second.communicate(timeout=20)
            self.assertEqual(0, second.returncode, stdout + stderr)
            self.assertFalse(pointer_was_broken)
            second_bundle = latest.resolve()
            self.assertNotEqual(first_bundle, second_bundle)
            self.assertTrue(first_bundle.exists())

            env.pop("MOCK_DIAGNOSTICS_DELAY")
            third = subprocess.run(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, third.returncode, third.stdout + third.stderr)
            third_bundle = latest.resolve()
            self.assertNotEqual(second_bundle, third_bundle)
            self.assertFalse(first_bundle.exists())
            self.assertTrue(second_bundle.exists())
            bundles = [
                path
                for path in (diagnostics_root / "bundles").iterdir()
                if path.is_dir() and not path.name.startswith(".staging.")
            ]
            self.assertEqual(2, len(bundles))

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
