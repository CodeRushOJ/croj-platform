import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
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
if [[ -n "${MOCK_DIAGNOSTICS_CAPTURE_MARKER:-}" ]]; then
  : >"$MOCK_DIAGNOSTICS_CAPTURE_MARKER"
fi
if [[ -n "${MOCK_DIAGNOSTICS_HOLD_FILE:-}" ]]; then
  while [[ -e "$MOCK_DIAGNOSTICS_HOLD_FILE" ]]; do
    sleep 0.02
  done
fi
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
        env["CODERUSHOJ_DIAGNOSTICS_RETAIN"] = "2"
        return project, scripts / "diagnostics.sh", env

    def wait_for_path(self, path, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {path}")

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
        self.assertIn("fcntl.flock", contents)
        self.assertNotIn("ps -p", contents)
        self.assertNotIn("lock_is_stale", contents)
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
            lock_file = diagnostics_root / ".publish.flock"
            self.assertTrue(lock_file.is_file())
            self.assertEqual(0o600, stat.S_IMODE(lock_file.stat().st_mode))

    def test_diagnostics_recovers_sigkill_journal_before_capture(self):
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
            (stale_lock / "process-start").write_text("legacy\n")
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
            flock_file = diagnostics_root / ".publish.flock"
            self.assertTrue(flock_file.is_file())
            self.assertIn('"mechanism": "fcntl.flock"', flock_file.read_text())
            self.assertTrue((diagnostics_root / "latest").is_symlink())
            self.assertEqual([], list(diagnostics_root.rglob("pods-logs.txt")))

    def test_diagnostics_refuses_to_migrate_a_live_legacy_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            env["CODERUSHOJ_DIAGNOSTICS_LOCK_TIMEOUT_SECONDS"] = "1"
            capture_marker = pathlib.Path(directory) / "capture-started"
            env["MOCK_DIAGNOSTICS_CAPTURE_MARKER"] = str(capture_marker)

            legacy_lock = project / ".workspace/diagnostics/.publish.lock"
            legacy_lock.mkdir(parents=True)
            (legacy_lock / "pid").write_text(f"{os.getpid()}\n")
            (legacy_lock / "process-start").write_text("timezone-independent\n")
            (legacy_lock / "token").write_text("live-token\n")
            (legacy_lock / "created").write_text("1\n")

            result = subprocess.run(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("live legacy diagnostics publisher", result.stderr)
            self.assertFalse(capture_marker.exists())
            self.assertTrue(legacy_lock.is_dir())

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
            lock_file = diagnostics_root / ".publish.flock"
            self.assertTrue(lock_file.is_file())
            self.assertIn('"mechanism": "fcntl.flock"', lock_file.read_text())
            self.assertEqual(
                [],
                [
                    path
                    for path in diagnostics_root.rglob("latest")
                    if path != latest
                ],
            )

    def test_diagnostics_live_owner_is_not_reclaimed_across_timezones(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            mock_ps = pathlib.Path(directory) / "bin/ps"
            mock_ps.write_text(
                "#!/usr/bin/env bash\n"
                "set -Eeuo pipefail\n"
                'if [[ "${TZ:-}" == "UTC" ]]; then\n'
                "  printf 'Mon Jan 01 00:00:00 2024\\n'\n"
                "else\n"
                "  printf 'Mon Jan 01 08:00:00 2024\\n'\n"
                "fi\n"
            )
            mock_ps.chmod(0o755)

            hold = pathlib.Path(directory) / "hold-first-capture"
            first_marker = pathlib.Path(directory) / "first-capture"
            second_marker = pathlib.Path(directory) / "second-capture"
            hold.touch()

            first_env = env.copy()
            first_env["TZ"] = "UTC"
            first_env["MOCK_DIAGNOSTICS_CAPTURE_MARKER"] = str(first_marker)
            first_env["MOCK_DIAGNOSTICS_HOLD_FILE"] = str(hold)
            first = subprocess.Popen(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=first_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.wait_for_path(first_marker)

            second_env = env.copy()
            second_env["TZ"] = "Asia/Shanghai"
            second_env["MOCK_DIAGNOSTICS_CAPTURE_MARKER"] = str(second_marker)
            second = subprocess.Popen(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=second_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            entered_while_live = second_marker.exists()
            hold.unlink()

            results = []
            for process in (first, second):
                stdout, stderr = process.communicate(timeout=20)
                results.append((process.returncode, stdout, stderr))
            for returncode, stdout, stderr in results:
                self.assertEqual(0, returncode, stdout + stderr)
            self.assertFalse(
                entered_while_live,
                "a live owner was reclaimed after ps output changed with TZ",
            )

    def test_diagnostics_two_reclaimers_cannot_replace_a_new_live_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            diagnostics_root = project / ".workspace/diagnostics"
            diagnostics_root.mkdir(parents=True)
            (diagnostics_root / ".publish.lock").touch()

            coordination = pathlib.Path(directory) / "mv-coordination"
            coordination.mkdir()
            real_mv = shutil.which("mv")
            self.assertIsNotNone(real_mv)
            fake_mv = pathlib.Path(directory) / "bin/mv"
            fake_mv.write_text(
                "#!/usr/bin/env bash\n"
                "set -Eeuo pipefail\n"
                f"real_mv={real_mv!r}\n"
                'if [[ "${1:-}" == */.publish.lock '
                '&& "${2:-}" == */.publish.lock.stale.* ]]; then\n'
                '  if mkdir "$MOCK_DIAGNOSTICS_MV_COORDINATION/claim" '
                "2>/dev/null; then\n"
                '    "$real_mv" "$@"\n'
                '    : >"$MOCK_DIAGNOSTICS_MV_COORDINATION/first-moved"\n'
                "    exit 0\n"
                "  fi\n"
                '  while [[ ! -f "$MOCK_DIAGNOSTICS_MV_COORDINATION/first-moved" ]]; do\n'
                "    sleep 0.01\n"
                "  done\n"
                '  while [[ ! -f "${1}/token" ]]; do\n'
                "    sleep 0.01\n"
                "  done\n"
                '  exec "$real_mv" "$@"\n'
                "fi\n"
                'exec "$real_mv" "$@"\n'
            )
            fake_mv.chmod(0o755)

            hold = pathlib.Path(directory) / "hold-captures"
            hold.touch()
            markers = [
                pathlib.Path(directory) / "capture-one",
                pathlib.Path(directory) / "capture-two",
            ]
            processes = []
            for marker in markers:
                process_env = env.copy()
                process_env["MOCK_DIAGNOSTICS_MV_COORDINATION"] = str(coordination)
                process_env["MOCK_DIAGNOSTICS_CAPTURE_MARKER"] = str(marker)
                process_env["MOCK_DIAGNOSTICS_HOLD_FILE"] = str(hold)
                processes.append(
                    subprocess.Popen(
                        ["bash", str(diagnostics_script)],
                        cwd=project,
                        env=process_env,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                )

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not any(
                marker.exists() for marker in markers
            ):
                time.sleep(0.01)
            self.assertTrue(any(marker.exists() for marker in markers))
            time.sleep(0.5)
            concurrent_captures = sum(marker.exists() for marker in markers)
            hold.unlink()

            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                results.append((process.returncode, stdout, stderr))
            for returncode, stdout, stderr in results:
                self.assertEqual(0, returncode, stdout + stderr)
            self.assertEqual(
                1,
                concurrent_captures,
                "a delayed stale observer replaced a newly acquired live lock",
            )

    def test_diagnostics_shared_inherited_ofd_cannot_authorize_two_publishers(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            diagnostics_root = project / ".workspace/diagnostics"
            diagnostics_root.mkdir(parents=True)
            shared_lock = diagnostics_root / ".publish.lock"
            hold = pathlib.Path(directory) / "hold-captures"
            hold.touch()
            markers = [
                pathlib.Path(directory) / "shared-capture-one",
                pathlib.Path(directory) / "shared-capture-two",
            ]

            launcher = r"""
import fcntl
import json
import os
import pathlib
import subprocess
import sys
import time

script, project, lock_path, hold_path, marker_one, marker_two = sys.argv[1:]
lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(lock_fd, fcntl.LOCK_EX)
if lock_fd != 9:
    os.dup2(lock_fd, 9, inheritable=True)
    os.close(lock_fd)
else:
    os.set_inheritable(lock_fd, True)

processes = []
for marker in (marker_one, marker_two):
    child_env = os.environ.copy()
    child_env["CODERUSHOJ_DIAGNOSTICS_FCNTL_LOCK_FD"] = "9"
    child_env["MOCK_DIAGNOSTICS_CAPTURE_MARKER"] = marker
    child_env["MOCK_DIAGNOSTICS_HOLD_FILE"] = hold_path
    processes.append(
        subprocess.Popen(
            ["bash", script],
            cwd=project,
            env=child_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(9,),
        )
    )
os.close(9)

deadline = time.monotonic() + 5
marker_paths = [pathlib.Path(marker_one), pathlib.Path(marker_two)]
while time.monotonic() < deadline and not any(path.exists() for path in marker_paths):
    time.sleep(0.01)
time.sleep(0.5)
concurrent = sum(path.exists() for path in marker_paths)
pathlib.Path(hold_path).unlink()

results = []
for process in processes:
    stdout, stderr = process.communicate(timeout=20)
    results.append(
        {"returncode": process.returncode, "stdout": stdout, "stderr": stderr}
    )
print(json.dumps({"concurrent": concurrent, "results": results}))
"""
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    launcher,
                    str(diagnostics_script),
                    str(project),
                    str(shared_lock),
                    str(hold),
                    str(markers[0]),
                    str(markers[1]),
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            for process_result in payload["results"]:
                self.assertEqual(
                    0,
                    process_result["returncode"],
                    process_result["stdout"] + process_result["stderr"],
                )
            self.assertEqual(
                1,
                payload["concurrent"],
                "two children sharing one locked OFD both entered capture",
            )

    def test_diagnostics_reuses_the_invoking_bash_without_hardcoded_path(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            alternate_bash = pathlib.Path(directory) / "alternate-bash"
            alternate_bash.symlink_to(shutil.which("bash"))

            result = subprocess.run(
                [str(alternate_bash), str(diagnostics_script)],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            contents = diagnostics_script.read_text()
            self.assertNotIn('"/bin/bash"', contents)
            metadata = json.loads(
                (project / ".workspace/diagnostics/.publish.flock").read_text()
            )
            self.assertEqual(str(alternate_bash), metadata["bash"])

    def test_diagnostics_stale_metadata_cannot_block_kernel_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            env["CODERUSHOJ_DIAGNOSTICS_LOCK_TIMEOUT_SECONDS"] = "3"

            diagnostics_root = project / ".workspace/diagnostics"
            stale_lock = diagnostics_root / ".publish.flock"
            stale_lock.parent.mkdir(parents=True)
            stale_lock.write_text(
                f'{{"pid": {os.getpid()}, "incomplete_owner": true}}\n'
            )

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
            self.assertIn('"mechanism": "fcntl.flock"', stale_lock.read_text())

    def test_diagnostics_ignores_spoofed_inherited_fd_state(self):
        with tempfile.TemporaryDirectory() as directory:
            project, diagnostics_script, env = self.diagnostics_fixture(directory)
            env["CODERUSHOJ_DIAGNOSTICS_FCNTL_LOCK_FD"] = "9"

            result = subprocess.run(
                ["bash", str(diagnostics_script)],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            lock_file = project / ".workspace/diagnostics/.publish.flock"
            self.assertTrue(lock_file.is_file())
            self.assertIn('"mechanism": "fcntl.flock"', lock_file.read_text())

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
