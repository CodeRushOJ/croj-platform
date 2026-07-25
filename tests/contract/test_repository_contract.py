import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class RepositoryContractTest(unittest.TestCase):
    def read_required(self, relative_path):
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"required file is missing: {relative_path}")
        return path.read_text()

    def test_version_is_semver(self):
        self.assertRegex(self.read_required("VERSION").strip(), r"^\d+\.\d+\.\d+$")

    def test_changelog_has_current_version(self):
        version = self.read_required("VERSION").strip()
        self.assertIn(f"## [{version}]", self.read_required("CHANGELOG.md"))

    def test_makefile_discovers_contract_tests(self):
        makefile = self.read_required("Makefile")
        self.assertIn("unittest discover -s tests/contract", makefile)

    def test_brewfile_includes_optional_host_go_without_blocking_docker_paths(self):
        brewfile = self.read_required("Brewfile")
        quickstart = self.read_required("docs/guide/quickstart.md")
        self.assertIn('brew "go"\n', brewfile)
        self.assertIn("宿主 Go 是可选工具", quickstart)
        self.assertIn("Docker Compose 路径仍可用", quickstart)

    def test_brewfile_includes_optional_openjdk_17_for_host_maven_tests(self):
        brewfile = self.read_required("Brewfile")
        quickstart = self.read_required("docs/guide/quickstart.md")
        self.assertIn('brew "openjdk@17"\n', brewfile)
        self.assertIn("OpenJDK 17 是可选工具", quickstart)
        self.assertIn("本机 Maven 测试", quickstart)
        self.assertIn(
            'export PATH="$(brew --prefix openjdk@17)/bin:$PATH"',
            quickstart,
        )
        self.assertIn(
            'export JAVA_HOME="$(brew --prefix openjdk@17)/libexec/'
            'openjdk.jdk/Contents/Home"',
            quickstart,
        )

    def test_versions_are_pinned(self):
        values = {}
        for line in self.read_required("config/versions.env").splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value

        required = {
            "KUBERNETES_VERSION",
            "KIND_NODE_IMAGE",
            "ENVOY_GATEWAY_VERSION",
            "MYSQL_VERSION",
            "REDIS_VERSION",
            "ROCKETMQ_VERSION",
            "SEAWEEDFS_VERSION",
        }
        self.assertEqual(required, required & values.keys())
        for key in required:
            self.assertNotIn(values[key], {"latest", "main", "master"})


if __name__ == "__main__":
    unittest.main()
