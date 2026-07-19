import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCK = ROOT / "config/source-lock.json"
VALIDATOR = ROOT / "scripts/verify-source-lock.py"
CHECKOUT = ROOT / "scripts/checkout-sources.sh"
BUILD = ROOT / "scripts/build-dev-images.sh"
LOAD = ROOT / "scripts/load-dev-images.sh"

COMPONENTS = ("frontend", "backend", "judging-server", "sandbox", "docs")
REPOSITORIES = {
    "frontend": "croj-frontend",
    "backend": "croj-backend",
    "judging-server": "croj-judging-server",
    "sandbox": "croj-sandbox",
    "docs": "croj-platform",
}
IMAGES = {
    "frontend": "ghcr.io/coderushoj/croj-frontend:dev",
    "backend": "ghcr.io/coderushoj/croj-backend:dev",
    "judging-server": "ghcr.io/coderushoj/croj-judging-server:dev",
    "sandbox": "ghcr.io/coderushoj/croj-sandbox:dev",
    "docs": "ghcr.io/coderushoj/coderushoj-docs:dev",
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
            "context": "docs" if component == "docs" else ".",
            "dockerfile": "Dockerfile",
            "image": IMAGES[component],
        }
    path.write_text(json.dumps({"schemaVersion": 1, "sources": sources}, indent=2) + "\n")


class SourceLockContractTest(unittest.TestCase):
    def valid_lock(self, directory):
        lock = pathlib.Path(directory) / "source-lock.json"
        make_lock({component: str(index) * 40 for index, component in enumerate(COMPONENTS, 1)}, lock)
        return lock

    def test_canonical_lock_is_valid_and_normalizes_exactly_five_sources(self):
        self.assertTrue(LOCK.is_file(), "config/source-lock.json is missing")
        self.assertTrue(VALIDATOR.is_file(), "scripts/verify-source-lock.py is missing")

        validated = run(["python3", VALIDATOR, "validate", "--lock", LOCK])
        self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)

        rows = run(["python3", VALIDATOR, "rows", "--lock", LOCK])
        self.assertEqual(0, rows.returncode, rows.stdout + rows.stderr)
        parsed = [line.split("\t") for line in rows.stdout.splitlines()]
        self.assertEqual(5, len(parsed))
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
            del payload["sources"]["docs"]
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
        self.assertEqual(5 * 6, len(fields))
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
            context = working / "docs" if component == "docs" else working
            context.mkdir(exist_ok=True)
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
        self.environment.update(
            {
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
    def checkout(self):
        return run(
            [CHECKOUT, "--lock", self.lock, "--root", self.sources],
            env=self.environment,
        )

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
        self.assertEqual(5, len(fetch_log.read_text().splitlines()))
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

    def test_build_uses_all_locked_inputs_and_oci_provenance(self):
        self.write_executable("docker", 'printf \'%q \' "$@" >> "$COMMAND_LOG"\nprintf \'\\n\' >> "$COMMAND_LOG"\n')

        result = run(
            [BUILD, "--lock", self.lock, "--root", self.sources],
            env=self.environment,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        commands = self.command_log.read_text().splitlines()
        self.assertEqual(5, len(commands))
        for component, command in zip(COMPONENTS, commands):
            checkout = self.sources / component / self.commits[component]
            context = checkout / ("docs" if component == "docs" else ".")
            self.assertIn("buildx build --load", command)
            self.assertIn(f"--tag {IMAGES[component]}", command)
            self.assertIn(f"org.opencontainers.image.revision={self.commits[component]}", command)
            self.assertIn(
                f"org.opencontainers.image.source=https://github.com/CodeRushOJ/{REPOSITORIES[component]}.git",
                command,
            )
            self.assertIn(f"--file {context / 'Dockerfile'}", command)
            self.assertTrue(command.endswith(context.as_posix() + " "))

    def test_load_checks_images_then_calls_kind_once_without_creating_a_cluster(self):
        self.write_docker_inspector()
        self.write_executable(
            "kind",
            'printf \'kind\' >> "$COMMAND_LOG"\nprintf \' %q\' "$@" >> "$COMMAND_LOG"\nprintf \'\\n\' >> "$COMMAND_LOG"\n',
        )

        result = run(
            [LOAD, "--lock", self.lock, "--cluster", "contract-cluster"],
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
                    [LOAD, "--lock", self.lock, "--cluster", "contract-cluster"],
                    env=environment,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("provenance", result.stderr)
                self.assertNotIn("kind should-not-run", self.command_log.read_text())


if __name__ == "__main__":
    unittest.main()
