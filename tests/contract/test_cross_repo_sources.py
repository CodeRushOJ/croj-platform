import importlib.util
import json
import os
import pathlib
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCK = ROOT / "config/source-lock.json"
VALIDATOR = ROOT / "scripts/verify-source-lock.py"
CHECKOUT = ROOT / "scripts/checkout-sources.sh"
BUILD = ROOT / "scripts/build-dev-images.sh"
LOAD = ROOT / "scripts/load-dev-images.sh"
LOCK_HELPER = ROOT / "scripts/checkout-lock.py"


def load_lock_helper():
    spec = importlib.util.spec_from_file_location("checkout_lock", LOCK_HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

COMPONENTS = ("frontend", "backend", "judging-server", "sandbox")
REPOSITORIES = {
    "frontend": "croj-frontend",
    "backend": "croj-backend",
    "judging-server": "croj-judging-server",
    "sandbox": "croj-sandbox",
}
IMAGES = {
    "frontend": "ghcr.io/coderushoj/croj-frontend:dev",
    "backend": "ghcr.io/coderushoj/croj-backend:dev",
    "judging-server": "ghcr.io/coderushoj/croj-judging-server:dev",
    "sandbox": "ghcr.io/coderushoj/croj-sandbox:dev",
}
DOCS_IMAGE = "ghcr.io/coderushoj/coderushoj-docs:dev"
PLATFORM_REPOSITORY = "https://github.com/CodeRushOJ/croj-platform.git"
RELEASE_CANDIDATES = {
    "frontend": "3d969de520c00d67d986a9fb2835515f505633ee",
    "backend": "b15482be4107c3100f82b43e6c30eac6eb9955e4",
    "judging-server": "50b2ee3fbf7f0b22a1170518a1705e4bbabe8f85",
    "sandbox": "f927ba0baaaf4d4100f6ba20ec0d6b68d2cd96af",
}


def run(command, **kwargs):
    return subprocess.run(
        [str(part) for part in command],
        text=True,
        capture_output=True,
        check=False,
        **kwargs,
    )


def make_lock(commits, path):
    sources = {}
    for component in COMPONENTS:
        sources[component] = {
            "repository": f"https://github.com/CodeRushOJ/{REPOSITORIES[component]}.git",
            "commit": commits[component],
            "context": ".",
            "dockerfile": "Dockerfile",
            "image": IMAGES[component],
        }
    path.write_text(json.dumps({"schemaVersion": 1, "sources": sources}, indent=2) + "\n")


class SourceLockContractTest(unittest.TestCase):
    def valid_lock(self, directory):
        lock = pathlib.Path(directory) / "source-lock.json"
        make_lock({component: str(index) * 40 for index, component in enumerate(COMPONENTS, 1)}, lock)
        return lock

    def test_canonical_lock_is_valid_and_normalizes_exactly_four_external_sources(self):
        self.assertTrue(LOCK.is_file(), "config/source-lock.json is missing")
        self.assertTrue(VALIDATOR.is_file(), "scripts/verify-source-lock.py is missing")

        validated = run(["python3", VALIDATOR, "validate", "--lock", LOCK])
        self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)

        rows = run(["python3", VALIDATOR, "rows", "--lock", LOCK])
        self.assertEqual(0, rows.returncode, rows.stdout + rows.stderr)
        parsed = [line.split("\t") for line in rows.stdout.splitlines()]
        self.assertEqual(4, len(parsed))
        self.assertEqual(list(COMPONENTS), [row[0] for row in parsed])
        for component, repository, commit, context, dockerfile, image in parsed:
            self.assertEqual(
                f"https://github.com/CodeRushOJ/{REPOSITORIES[component]}.git",
                repository,
            )
            self.assertRegex(commit, r"^[0-9a-f]{40}$")
            self.assertFalse(pathlib.PurePosixPath(context).is_absolute())
            self.assertFalse(pathlib.PurePosixPath(dockerfile).is_absolute())
            self.assertNotIn("..", pathlib.PurePosixPath(context).parts)
            self.assertNotIn("..", pathlib.PurePosixPath(dockerfile).parts)
            self.assertEqual(IMAGES[component], image)

    def test_canonical_lock_selects_the_reviewed_v1_release_candidates(self):
        payload = json.loads(LOCK.read_text())
        self.assertEqual(
            RELEASE_CANDIDATES,
            {
                component: payload["sources"][component]["commit"]
                for component in COMPONENTS
            },
        )

    def test_validator_rejects_mutable_ref_unknown_fields_and_duplicate_images(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock = self.valid_lock(temporary_directory)
            payload = json.loads(lock.read_text())
            payload["sources"]["frontend"]["commit"] = "main"
            payload["sources"]["backend"]["branch"] = "codex/backend-product-integration"
            payload["sources"]["sandbox"]["image"] = IMAGES["frontend"]
            lock.write_text(json.dumps(payload))

            result = run(["python3", VALIDATOR, "validate", "--lock", lock])

        self.assertNotEqual(0, result.returncode)
        self.assertIn("commit", result.stderr)
        self.assertIn("unknown field", result.stderr)
        self.assertIn("duplicate image", result.stderr)

    def test_validator_rejects_missing_component_unsafe_path_and_foreign_remote(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock = self.valid_lock(temporary_directory)
            payload = json.loads(lock.read_text())
            del payload["sources"]["sandbox"]
            payload["sources"]["frontend"]["context"] = "../outside"
            payload["sources"]["backend"]["repository"] = "https://example.com/backend.git"
            lock.write_text(json.dumps(payload))

            result = run(["python3", VALIDATOR, "validate", "--lock", lock])

        self.assertNotEqual(0, result.returncode)
        self.assertIn("component set", result.stderr)
        self.assertIn("safe relative path", result.stderr)
        self.assertIn("CodeRushOJ GitHub repository", result.stderr)

    def test_validator_rejects_ascii_control_characters_before_record_serialization(self):
        for code_point in (*range(32), 127):
            control_character = chr(code_point)
            with self.subTest(code_point=ord(control_character)):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    lock = self.valid_lock(temporary_directory)
                    payload = json.loads(lock.read_text())
                    payload["sources"]["frontend"]["dockerfile"] = (
                        "Dockerfile" + control_character + "injected"
                    )
                    lock.write_text(json.dumps(payload))

                    result = run(["python3", VALIDATOR, "validate", "--lock", lock])

                self.assertNotEqual(0, result.returncode)
                self.assertIn("ASCII control", result.stderr)

    def test_validator_rejects_control_characters_in_every_source_text_field(self):
        for field in ("repository", "commit", "context", "dockerfile", "image"):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    lock = self.valid_lock(temporary_directory)
                    payload = json.loads(lock.read_text())
                    payload["sources"]["frontend"][field] += "\nlog-injection"
                    lock.write_text(json.dumps(payload))

                    result = run(["python3", VALIDATOR, "validate", "--lock", lock])

                self.assertNotEqual(0, result.returncode)
                self.assertIn("ASCII control", result.stderr)

    def test_validator_emits_nul_delimited_records_for_shell_consumers(self):
        records = run(["python3", VALIDATOR, "records", "--lock", LOCK])

        self.assertEqual(0, records.returncode, records.stdout + records.stderr)
        fields = records.stdout.split("\x00")
        self.assertEqual("", fields.pop())
        self.assertEqual(4 * 6, len(fields))
        self.assertEqual(list(COMPONENTS), fields[0::6])
        for script in (CHECKOUT, BUILD, LOAD):
            contents = script.read_text()
            self.assertIn('"records"', contents)
            self.assertNotIn('"rows"', contents)


class GitFixtureMixin:
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.temporary_directory.name)
        self.remotes = self.base / "remotes"
        self.remotes.mkdir()
        self.commits = {}
        for component in COMPONENTS:
            repository_name = REPOSITORIES[component]
            working = self.base / f"working-{repository_name}"
            working.mkdir()
            run(["git", "init", "--initial-branch=main", working])
            run(["git", "-C", working, "config", "user.name", "Contract Test"])
            run(["git", "-C", working, "config", "user.email", "contract@example.test"])
            context = working
            (context / "Dockerfile").write_text("FROM scratch\n")
            run(["git", "-C", working, "add", "."])
            commit = run(["git", "-C", working, "commit", "-m", "fixture"])
            self.assertEqual(0, commit.returncode, commit.stdout + commit.stderr)
            self.commits[component] = run(
                ["git", "-C", working, "rev-parse", "HEAD"]
            ).stdout.strip()
            bare = self.remotes / f"{repository_name}.git"
            clone = run(["git", "clone", "--bare", working, bare])
            self.assertEqual(0, clone.returncode, clone.stdout + clone.stderr)

        self.lock = self.base / "source-lock.json"
        make_lock(self.commits, self.lock)
        self.sources = self.base / "sources"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.environment = os.environ.copy()
        self.platform_revision = run(
            ["git", "-C", ROOT, "rev-parse", "HEAD"]
        ).stdout.strip()
        self.environment.update(
            {
                "GITHUB_SHA": self.platform_revision,
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "url.file://"
                + self.remotes.as_posix()
                + "/.insteadOf",
                "GIT_CONFIG_VALUE_0": "https://github.com/CodeRushOJ/",
            }
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_executable(self, name, contents):
        executable = self.bin / name
        executable.write_text("#!/usr/bin/env bash\nset -Eeuo pipefail\n" + contents)
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        return executable


class CrossRepositoryCheckoutTest(GitFixtureMixin, unittest.TestCase):
    def checkout(self, environment=None):
        return run(
            [CHECKOUT, "--lock", self.lock, "--root", self.sources],
            env=environment or self.environment,
        )

    def assert_checkout_ignores_incomplete_legacy_owner(self, owner_contents):
        component_root = self.sources / "frontend"
        lock_directory = component_root / f".{self.commits['frontend']}.lock"
        lock_directory.mkdir(parents=True)
        if owner_contents is not None:
            (lock_directory / "owner").write_text(owner_contents)
        environment = self.environment.copy()
        environment.update(
            {
                "CODERUSHOJ_CHECKOUT_LOCK_TIMEOUT_MS": "500",
                "CODERUSHOJ_CHECKOUT_LOCK_POLL_MS": "10",
                "CODERUSHOJ_CHECKOUT_LOCK_LEGACY_GRACE_MS": "20",
            }
        )
        process = subprocess.Popen(
            [str(CHECKOUT), "--lock", str(self.lock), "--root", str(self.sources)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            self.fail("checkout remained blocked by incomplete owner metadata\n" + stdout + stderr)
        self.assertEqual(0, process.returncode, stdout + stderr)

    def test_ownerless_legacy_lock_does_not_block_checkout(self):
        self.assert_checkout_ignores_incomplete_legacy_owner(None)

    def test_partially_written_legacy_owner_does_not_block_checkout(self):
        self.assert_checkout_ignores_incomplete_legacy_owner("wri")

    def test_owner_completed_within_grace_is_not_reclaimed(self):
        component_root = self.sources / "frontend"
        lock_directory = component_root / f".{self.commits['frontend']}.lock"
        lock_directory.mkdir(parents=True)
        environment = self.environment.copy()
        environment.update(
            {
                "CODERUSHOJ_CHECKOUT_LOCK_TIMEOUT_MS": "250",
                "CODERUSHOJ_CHECKOUT_LOCK_POLL_MS": "10",
                "CODERUSHOJ_CHECKOUT_LOCK_LEGACY_GRACE_MS": "100",
            }
        )
        process = subprocess.Popen(
            [str(CHECKOUT), "--lock", str(self.lock), "--root", str(self.sources)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        owner = lock_directory / "owner"
        time.sleep(0.02)
        owner.write_text(f"{os.getpid()}\n")

        stdout, stderr = process.communicate(timeout=2)

        self.assertNotEqual(0, process.returncode, stdout + stderr)
        self.assertTrue(lock_directory.is_dir())
        self.assertEqual(str(os.getpid()), owner.read_text().strip())

    def test_sigkill_of_helper_keeps_lock_in_inherited_critical_child(self):
        lock_file = self.base / "crash-safe.lock"
        waiter_ready = self.base / "waiter.ready"
        child_started = self.base / "child.started"
        child_release = self.base / "child.release"
        critical_child = self.write_executable(
            "critical-child",
            'touch "$CHILD_STARTED"\n'
            'while [[ ! -f "$CHILD_RELEASE" ]]; do sleep 0.01; done\n',
        )

        def helper_command(ready=None, command=None):
            arguments = [
                "python3",
                str(LOCK_HELPER),
                "--lock",
                str(lock_file),
                "--parent-pid",
                str(os.getpid()),
                "--timeout-ms",
                "1000",
                "--poll-ms",
                "10",
                "--legacy-grace-ms",
                "20",
            ]
            if ready is not None:
                arguments.extend(("--ready", str(ready)))
            if command is not None:
                arguments.extend(("--", str(command)))
            return arguments

        environment = self.environment.copy()
        environment.update(
            {"CHILD_STARTED": str(child_started), "CHILD_RELEASE": str(child_release)}
        )
        holder = subprocess.Popen(
            helper_command(command=critical_child),
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        waiter = None
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not child_started.exists():
                if holder.poll() is not None:
                    self.fail(holder.stderr.read())
                time.sleep(0.01)
            self.assertTrue(child_started.exists())
            waiter = subprocess.Popen(
                helper_command(ready=waiter_ready), stderr=subprocess.PIPE, text=True
            )
            time.sleep(0.05)
            self.assertFalse(waiter_ready.exists(), "waiter acquired a lock held by child")

            holder.kill()
            holder.wait(timeout=2)
            time.sleep(0.05)
            self.assertFalse(
                waiter_ready.exists(),
                "helper death released the lock while its critical child was still running",
            )
            child_release.touch()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not waiter_ready.exists():
                if waiter.poll() is not None:
                    self.fail(waiter.stderr.read())
                time.sleep(0.01)
            self.assertTrue(waiter_ready.exists())
        finally:
            child_release.touch(exist_ok=True)
            if holder.poll() is None:
                holder.kill()
                holder.wait(timeout=2)
            if waiter is not None and waiter.poll() is None:
                waiter.terminate()
                waiter.wait(timeout=2)
            if holder.stderr:
                holder.stderr.close()
            if waiter is not None and waiter.stderr:
                waiter.stderr.close()

    def test_sigkill_of_parent_cancels_helper_waiting_for_lock(self):
        lock_file = self.base / "parent-crash.lock"
        blocker_ready = self.base / "blocker.ready"
        orphan_ready = self.base / "orphan.ready"
        orphan_pid_file = self.base / "orphan.pid"
        helper_arguments = [
            "--lock",
            str(lock_file),
            "--timeout-ms",
            "1000",
            "--poll-ms",
            "10",
            "--legacy-grace-ms",
            "20",
        ]
        blocker = subprocess.Popen(
            [
                "python3",
                str(LOCK_HELPER),
                *helper_arguments,
                "--ready",
                str(blocker_ready),
                "--parent-pid",
                str(os.getpid()),
            ]
        )
        parent = None
        orphan_pid = None
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not blocker_ready.exists():
                time.sleep(0.01)
            self.assertTrue(blocker_ready.exists())
            wrapper = self.write_executable(
                "waiting-parent",
                'python3 "$LOCK_HELPER" "$@" --ready "$ORPHAN_READY" --parent-pid "$$" &\n'
                'child="$!"\n'
                'printf \'%s\\n\' "$child" > "$ORPHAN_PID_FILE"\n'
                'wait "$child"\n',
            )
            environment = self.environment.copy()
            environment.update(
                {
                    "LOCK_HELPER": str(LOCK_HELPER),
                    "ORPHAN_READY": str(orphan_ready),
                    "ORPHAN_PID_FILE": str(orphan_pid_file),
                }
            )
            parent = subprocess.Popen(
                [str(wrapper), *helper_arguments],
                env=environment,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not orphan_pid_file.exists():
                time.sleep(0.01)
            self.assertTrue(orphan_pid_file.exists())
            orphan_pid = int(orphan_pid_file.read_text().strip())
            self.assertFalse(orphan_ready.exists())

            parent.kill()
            parent.wait(timeout=2)
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                try:
                    os.kill(orphan_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.01)
            else:
                self.fail("orphaned helper kept waiting after its parent was killed")
        finally:
            if parent is not None and parent.poll() is None:
                parent.kill()
                parent.wait(timeout=2)
            if orphan_pid is not None:
                try:
                    os.kill(orphan_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if blocker.poll() is None:
                blocker.terminate()
                blocker.wait(timeout=2)

    def test_legacy_owner_write_during_quarantine_fails_closed_without_overwriting_later_path(self):
        lock_helper = load_lock_helper()
        lock_directory = self.base / "legacy.lock"
        lock_directory.mkdir()
        owner = lock_directory / "owner"
        owner.write_text("wri")
        expected = lock_helper.legacy_snapshot(lock_directory)
        real_rename = lock_helper.os.rename
        rename_calls = 0

        def racing_rename(source, destination):
            nonlocal rename_calls
            if rename_calls == 0:
                owner.write_text(f"{os.getpid()}\n")
            rename_calls += 1
            result = real_rename(source, destination)
            if rename_calls == 1:
                lock_directory.mkdir()
            return result

        with mock.patch.object(lock_helper.os, "rename", side_effect=racing_rename):
            with self.assertRaisesRegex(RuntimeError, "retained for inspection"):
                lock_helper.quarantine_legacy_lock(lock_directory, expected)

        self.assertTrue(lock_directory.is_dir())
        self.assertEqual([], list(lock_directory.iterdir()))
        quarantines = list(self.base.glob("legacy.lock.stale.*"))
        self.assertEqual(1, len(quarantines))
        self.assertEqual(
            str(os.getpid()), (quarantines[0] / "owner").read_text().strip()
        )
        with self.assertRaisesRegex(RuntimeError, "retained legacy quarantine"):
            lock_helper.open_lock_file(
                lock_directory,
                deadline=time.monotonic() + 0.1,
                poll_seconds=0.01,
                legacy_grace_ms=20,
                parent_pid=os.getppid(),
            )

    def test_recent_partial_owner_update_receives_the_full_legacy_grace(self):
        lock_helper = load_lock_helper()
        lock_directory = self.base / "legacy.lock"
        lock_directory.mkdir()
        owner = lock_directory / "owner"
        owner.write_text("w")
        old = time.time() - 60
        os.utime(lock_directory, (old, old))
        owner.write_text("wri")

        snapshot = lock_helper.legacy_snapshot(lock_directory)

        self.assertFalse(lock_helper.legacy_is_stale(snapshot, grace_ms=1000))

    def test_lock_timing_environment_requires_safe_positive_milliseconds(self):
        cases = (
            ({"CODERUSHOJ_CHECKOUT_LOCK_TIMEOUT_MS": "0"}, "timeout"),
            ({"CODERUSHOJ_CHECKOUT_LOCK_POLL_MS": "fast"}, "poll"),
            (
                {
                    "CODERUSHOJ_CHECKOUT_LOCK_POLL_MS": "20",
                    "CODERUSHOJ_CHECKOUT_LOCK_LEGACY_GRACE_MS": "10",
                },
                "grace",
            ),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                environment = self.environment.copy()
                environment.update(overrides)
                result = self.checkout(environment)
                self.assertNotEqual(0, result.returncode)
                self.assertIn(message, result.stderr)

    def test_checkout_uses_detached_commit_addressed_directories_and_is_idempotent(self):
        first = self.checkout()
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)

        for component in COMPONENTS:
            checkout = self.sources / component / self.commits[component]
            self.assertTrue(checkout.is_dir())
            head = run(["git", "-C", checkout, "rev-parse", "HEAD"])
            self.assertEqual(self.commits[component], head.stdout.strip())
            branch = run(["git", "-C", checkout, "symbolic-ref", "-q", "HEAD"])
            self.assertNotEqual(0, branch.returncode)

        second = self.checkout()
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertIn("reusing frontend", second.stdout)

    def test_checkout_refuses_to_reuse_a_dirty_source(self):
        first = self.checkout()
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        frontend = self.sources / "frontend" / self.commits["frontend"]
        (frontend / "dirty.txt").write_text("must not be silently deleted\n")

        second = self.checkout()

        self.assertNotEqual(0, second.returncode)
        self.assertIn("not clean", second.stderr)
        self.assertTrue((frontend / "dirty.txt").is_file())

    def test_checkout_refuses_an_attached_branch_even_at_the_locked_commit(self):
        first = self.checkout()
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        frontend = self.sources / "frontend" / self.commits["frontend"]
        attached = run(["git", "-C", frontend, "switch", "-c", "mutable-ref"])
        self.assertEqual(0, attached.returncode, attached.stdout + attached.stderr)

        second = self.checkout()

        self.assertNotEqual(0, second.returncode)
        self.assertIn("not detached", second.stderr)

    def test_concurrent_checkouts_publish_one_clean_exact_cache_entry(self):
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)
        fetch_log = self.base / "fetch.log"
        self.write_executable(
            "git",
            'if [[ "${1:-}" == "-C" && "${3:-}" == "fetch" ]]; then\n'
            '  printf \'fetch\\n\' >> "$FETCH_LOG"\n'
            "  sleep 0.2\n"
            "fi\n"
            'exec "$REAL_GIT" "$@"\n',
        )
        environment = self.environment.copy()
        environment.update(
            {
                "PATH": self.bin.as_posix() + os.pathsep + environment["PATH"],
                "REAL_GIT": real_git,
                "FETCH_LOG": fetch_log.as_posix(),
            }
        )

        commands = [
            str(CHECKOUT),
            "--lock",
            str(self.lock),
            "--root",
            str(self.sources),
        ]
        workers = [
            subprocess.Popen(
                commands,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            for _ in range(2)
        ]
        results = [
            worker.communicate(timeout=30) + (worker.returncode,) for worker in workers
        ]

        for stdout, stderr, returncode in results:
            self.assertEqual(0, returncode, stdout + stderr)
        self.assertEqual(4, len(fetch_log.read_text().splitlines()))
        for component in COMPONENTS:
            checkout = self.sources / component / self.commits[component]
            head = run([real_git, "-C", checkout, "rev-parse", "HEAD"])
            branch = run([real_git, "-C", checkout, "symbolic-ref", "-q", "HEAD"])
            status = run(
                [
                    real_git,
                    "-C",
                    checkout,
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ]
            )
            self.assertEqual(self.commits[component], head.stdout.strip())
            self.assertNotEqual(0, branch.returncode)
            self.assertEqual("", status.stdout, status.stdout)


class CrossRepositoryImageWorkflowTest(GitFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.platform_root = self.base / "platform"
        (self.platform_root / "scripts").mkdir(parents=True)
        (self.platform_root / "docs").mkdir()
        for name in (
            "build-dev-images.sh",
            "checkout-lock.py",
            "checkout-one-source.sh",
            "checkout-sources.sh",
            "lib.sh",
            "load-dev-images.sh",
            "verify-source-lock.py",
        ):
            shutil.copy2(ROOT / "scripts" / name, self.platform_root / "scripts" / name)
        (self.platform_root / "docs" / "Dockerfile").write_text("FROM scratch\n")
        run(["git", "init", "--initial-branch=main", self.platform_root])
        run(["git", "-C", self.platform_root, "config", "user.name", "Contract Test"])
        run(
            [
                "git",
                "-C",
                self.platform_root,
                "config",
                "user.email",
                "contract@example.test",
            ]
        )
        run(["git", "-C", self.platform_root, "add", "."])
        commit = run(["git", "-C", self.platform_root, "commit", "-m", "platform fixture"])
        self.assertEqual(0, commit.returncode, commit.stdout + commit.stderr)
        self.platform_revision = run(
            ["git", "-C", self.platform_root, "rev-parse", "HEAD"]
        ).stdout.strip()
        self.environment["GITHUB_SHA"] = self.platform_revision
        self.build = self.platform_root / "scripts" / "build-dev-images.sh"
        self.load = self.platform_root / "scripts" / "load-dev-images.sh"
        self.command_log = self.base / "commands.log"
        self.environment["PATH"] = self.bin.as_posix() + os.pathsep + self.environment["PATH"]
        self.environment["COMMAND_LOG"] = self.command_log.as_posix()

    def write_docker_inspector(self):
        cases = []
        for component in COMPONENTS:
            cases.append(
                f"  {IMAGES[component]!r}) printf '%s\\n%s\\n' "
                f"{self.commits[component]!r} "
                f"{'https://github.com/CodeRushOJ/' + REPOSITORIES[component] + '.git'!r} ;;"
            )
        cases.append(
            f"  {DOCS_IMAGE!r}) printf '%s\\n%s\\n' "
            f"{self.platform_revision!r} {PLATFORM_REPOSITORY!r} ;;"
        )
        self.write_executable(
            "docker",
            'printf \'docker\' >> "$COMMAND_LOG"\n'
            'printf \' %q\' "$@" >> "$COMMAND_LOG"\n'
            'printf \'\\n\' >> "$COMMAND_LOG"\n'
            '[[ "${1:-}" == image && "${2:-}" == inspect ]]\n'
            'image="${@: -1}"\n'
            'if [[ "${PROVENANCE_MODE:-valid}" == missing ]]; then\n'
            "  printf '<no value>\\n<no value>\\n'\n"
            "  exit 0\n"
            "fi\n"
            'if [[ "${PROVENANCE_MODE:-valid}" == wrong && "$image" == '
            + repr(IMAGES["frontend"])
            + " ]]; then\n"
            "  printf '0000000000000000000000000000000000000000\\nhttps://github.com/CodeRushOJ/croj-frontend.git\\n'\n"
            "  exit 0\n"
            "fi\n"
            "case \"$image\" in\n"
            + "\n".join(cases)
            + "\n  *) exit 2 ;;\nesac\n",
        )

    def test_build_uses_four_locked_inputs_and_current_platform_docs_provenance(self):
        self.write_executable("docker", 'printf \'%q \' "$@" >> "$COMMAND_LOG"\nprintf \'\\n\' >> "$COMMAND_LOG"\n')

        result = run(
            [self.build, "--lock", self.lock, "--root", self.sources],
            env=self.environment,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        commands = self.command_log.read_text().splitlines()
        self.assertEqual(5, len(commands))
        for component, command in zip(COMPONENTS, commands[:4]):
            checkout = self.sources / component / self.commits[component]
            context = checkout
            self.assertIn("buildx build --load", command)
            self.assertIn(f"--tag {IMAGES[component]}", command)
            self.assertIn(f"org.opencontainers.image.revision={self.commits[component]}", command)
            self.assertIn(
                f"org.opencontainers.image.source=https://github.com/CodeRushOJ/{REPOSITORIES[component]}.git",
                command,
            )
            self.assertIn(f"--file {context / 'Dockerfile'}", command)
            self.assertTrue(command.endswith(context.as_posix() + " "))
        docs_command = commands[4]
        docs_context = self.platform_root / "docs"
        self.assertIn("buildx build --load", docs_command)
        self.assertIn(f"--tag {DOCS_IMAGE}", docs_command)
        self.assertIn(
            f"org.opencontainers.image.revision={self.platform_revision}",
            docs_command,
        )
        self.assertIn(
            f"org.opencontainers.image.source={PLATFORM_REPOSITORY}",
            docs_command,
        )
        self.assertIn(f"--file {docs_context / 'Dockerfile'}", docs_command)
        self.assertTrue(docs_command.endswith(docs_context.as_posix() + " "))

    def test_current_platform_revision_rejects_tracked_staged_and_untracked_changes(self):
        cases = {
            "tracked": lambda: (self.platform_root / "docs" / "Dockerfile").write_text(
                "FROM scratch\n# dirty\n"
            ),
            "staged": lambda: (
                (self.platform_root / "docs" / "staged.txt").write_text("dirty\n"),
                run(["git", "-C", self.platform_root, "add", "docs/staged.txt"]),
            ),
            "untracked": lambda: (
                self.platform_root / "docs" / "untracked.txt"
            ).write_text("dirty\n"),
        }
        for state, make_dirty in cases.items():
            with self.subTest(state=state):
                run(["git", "-C", self.platform_root, "reset", "--hard", "HEAD"])
                run(["git", "-C", self.platform_root, "clean", "-fd"])
                make_dirty()

                result = run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; current_platform_revision',
                        "contract",
                        self.platform_root / "scripts" / "lib.sh",
                    ],
                    env=self.environment,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("not clean", result.stderr)

    def test_load_checks_images_then_calls_kind_once_without_creating_a_cluster(self):
        self.write_docker_inspector()
        self.write_executable(
            "kind",
            'printf \'kind\' >> "$COMMAND_LOG"\nprintf \' %q\' "$@" >> "$COMMAND_LOG"\nprintf \'\\n\' >> "$COMMAND_LOG"\n',
        )

        result = run(
            [self.load, "--lock", self.lock, "--cluster", "contract-cluster"],
            env=self.environment,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        commands = self.command_log.read_text().splitlines()
        self.assertEqual(6, len(commands))
        self.assertEqual(5, sum(command.startswith("docker image inspect") for command in commands))
        kind_commands = [command for command in commands if command.startswith("kind ")]
        self.assertEqual(1, len(kind_commands))
        kind_command = kind_commands[0]
        self.assertIn("kind load docker-image", kind_command)
        for image in IMAGES.values():
            self.assertIn(image, kind_command)
        self.assertIn(DOCS_IMAGE, kind_command)
        self.assertTrue(kind_command.endswith("--name contract-cluster"))
        self.assertNotIn("create", kind_command)

    def test_load_rejects_missing_or_wrong_oci_provenance_before_kind(self):
        for mode in ("missing", "wrong"):
            with self.subTest(mode=mode):
                self.command_log.write_text("")
                self.write_docker_inspector()
                self.write_executable(
                    "kind",
                    'printf \'kind should-not-run\\n\' >> "$COMMAND_LOG"\n',
                )
                environment = self.environment.copy()
                environment["PROVENANCE_MODE"] = mode

                result = run(
                    [self.load, "--lock", self.lock, "--cluster", "contract-cluster"],
                    env=environment,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("provenance", result.stderr)
                self.assertNotIn("kind should-not-run", self.command_log.read_text())


if __name__ == "__main__":
    unittest.main()
