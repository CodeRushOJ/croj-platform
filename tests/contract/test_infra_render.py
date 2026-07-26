import pathlib
import re
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/coderushoj-infra"


class InfrastructureRenderTest(unittest.TestCase):
    def render(self, *extra_args):
        self.assertTrue((CHART / "Chart.yaml").is_file(), "infrastructure chart is missing")
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj-infra",
                str(CHART),
                "--namespace",
                "coderushoj",
                *extra_args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def network_policy(self, rendered, name):
        marker = f"kind: NetworkPolicy\nmetadata:\n  name: {name}\n"
        self.assertIn(marker, rendered, f"missing NetworkPolicy {name}")
        return marker + rendered.split(marker, 1)[1].split("\n---", 1)[0]

    def test_renders_pinned_stateful_dependencies(self):
        rendered = self.render()
        for image in (
            "mysql:8.4.10",
            "redis:8.6.2-alpine",
            "apache/rocketmq:5.5.0",
            "chrislusf/seaweedfs:4.39",
            "axllent/mailpit:v1.30.0",
        ):
            self.assertIn(f"image: {image}", rendered)
        self.assertNotRegex(rendered, r"image:\s+\S+:latest(?:\s|$)")

        self.assertGreaterEqual(rendered.count("kind: StatefulSet"), 4)
        self.assertIn("kind: Deployment", rendered)
        self.assertGreaterEqual(rendered.count("volumeClaimTemplates:"), 4)
        self.assertGreaterEqual(rendered.count("readinessProbe:"), 5)
        self.assertGreaterEqual(rendered.count("resources:"), 5)
        self.assertIn("-Xms512m -Xmx512m", rendered)
        self.assertIn("-XX:MaxDirectMemorySize=256m", rendered)
        self.assertIn("app.kubernetes.io/component: mailpit", rendered)
        self.assertIn("port: 1025", rendered)

    def test_security_and_secret_contracts(self):
        rendered = self.render()
        self.assertGreaterEqual(rendered.count("allowPrivilegeEscalation: false"), 5)
        self.assertGreaterEqual(rendered.count("readOnlyRootFilesystem: true"), 5)
        self.assertGreaterEqual(rendered.count("runAsNonRoot: true"), 5)
        self.assertGreaterEqual(rendered.count("seccompProfile:"), 5)
        self.assertIn("kind: NetworkPolicy", rendered)
        self.assertIn("policyTypes:\n    - Ingress\n    - Egress", rendered)
        self.assertNotIn("podSelector: {}", rendered)
        self.assertGreaterEqual(rendered.count("automountServiceAccountToken: false"), 7)

        # Keep the known historical default out of both rendered manifests and
        # source-level secret detectors by assembling the sentinel at runtime.
        forbidden_default = "password: " + "coderush" + "oj"
        self.assertNotIn(forbidden_default, rendered.lower())
        for key in ("mysql-root-password", "redis-password", "s3-access-key", "s3-secret-key"):
            self.assertIn(f"key: {key}", rendered)

    def test_s3_smoke_probe_has_least_privilege_network_access(self):
        rendered = self.render()
        self.assertIn("name: coderushoj-infra-allow-s3-smoke-egress", rendered)
        self.assertIn("name: coderushoj-infra-allow-s3-smoke-ingress", rendered)

        egress_policy = rendered.split(
            "name: coderushoj-infra-allow-s3-smoke-egress", 1
        )[1].split("---", 1)[0]
        self.assertIn("app.kubernetes.io/component: s3-smoke", egress_policy)
        self.assertIn("app.kubernetes.io/component: seaweedfs", egress_policy)
        self.assertIn("port: 8333", egress_policy)
        self.assertIn("kubernetes.io/metadata.name: kube-system", egress_policy)

        ingress_policy = rendered.split(
            "name: coderushoj-infra-allow-s3-smoke-ingress", 1
        )[1].split("---", 1)[0]
        self.assertIn("app.kubernetes.io/component: seaweedfs", ingress_policy)
        self.assertIn("app.kubernetes.io/component: s3-smoke", ingress_policy)
        self.assertIn("port: 8333", ingress_policy)

        smoke_job = (ROOT / "tests/smoke/s3-job.yaml").read_text()
        self.assertIn("automountServiceAccountToken: false", smoke_job)

    def test_application_ingress_is_split_by_dependency_and_release(self):
        rendered = self.render()
        policies = {
            "mysql": (3306, ("backend", "judging-server", "admin-bootstrap")),
            "seaweedfs": (8333, ("backend", "judging-server")),
            "rocketmq-namesrv": (9876, ("backend", "judging-server")),
            "rocketmq-broker": (10911, ("backend", "judging-server")),
            "mailpit": (1025, ("backend",)),
        }
        for component, (port, sources) in policies.items():
            with self.subTest(component=component):
                policy = self.network_policy(
                    rendered,
                    f"coderushoj-infra-allow-applications-{component}",
                )
                selected_pods = policy.split("policyTypes:", 1)[0]
                self.assertIn(
                    "app.kubernetes.io/instance: coderushoj-infra",
                    selected_pods,
                )
                self.assertIn(
                    f"app.kubernetes.io/component: {component}",
                    selected_pods,
                )
                self.assertIn("app.kubernetes.io/instance: coderushoj", policy)
                for source in sources:
                    self.assertIn(source, policy)
                self.assertIn(f"port: {port}", policy)

        redis_backend = self.network_policy(
            rendered,
            "coderushoj-infra-allow-applications-redis-backend",
        )
        self.assertIn("app.kubernetes.io/component: redis", redis_backend)
        self.assertIn("app.kubernetes.io/component: backend", redis_backend)
        self.assertNotIn("judging-server", redis_backend)
        self.assertIn("port: 6379", redis_backend)

        redis_judging = self.network_policy(
            rendered,
            "coderushoj-infra-allow-applications-redis-judging",
        )
        self.assertIn("app.kubernetes.io/component: redis", redis_judging)
        self.assertIn("app.kubernetes.io/component: judging-server", redis_judging)
        self.assertIn("port: 6379", redis_judging)

        external_api_disabled = self.render(
            "--set",
            "applications.judgingExternalAPIEnabled=false",
        )
        self.assertNotIn(
            "name: coderushoj-infra-allow-applications-redis-judging",
            external_api_disabled,
        )
        self.assertIn(
            "name: coderushoj-infra-allow-applications-redis-backend",
            external_api_disabled,
        )

        self.assertNotIn("name: coderushoj-infra-allow-applications\n", rendered)

    def test_mailpit_can_reply_only_within_configured_cluster_networks(self):
        rendered = self.render()
        policy = self.network_policy(
            rendered,
            "coderushoj-infra-allow-mailpit-replies",
        )
        self.assertIn("app.kubernetes.io/component: mailpit", policy)
        self.assertIn("policyTypes:\n    - Egress", policy)
        for cidr in ("172.18.0.0/16", "192.168.0.0/16"):
            self.assertIn(f'cidr: "{cidr}"', policy)
        self.assertNotIn('cidr: "10.0.0.0/8"', policy)
        self.assertNotIn('cidr: "172.16.0.0/12"', policy)
        self.assertNotIn('cidr: "0.0.0.0/0"', policy)
        self.assertNotIn('cidr: "::/0"', policy)

        custom = self.render(
            "--set",
            "mailpit.replyCIDRs[0]=192.168.0.0/16",
        )
        custom_policy = self.network_policy(
            custom,
            "coderushoj-infra-allow-mailpit-replies",
        )
        self.assertIn('cidr: "192.168.0.0/16"', custom_policy)
        self.assertNotIn('cidr: "10.0.0.0/8"', custom_policy)

    def test_infrastructure_internal_network_is_limited_to_real_rocketmq_dependencies(self):
        rendered = self.render()
        self.assertNotIn("name: coderushoj-infra-allow-infra-internal\n", rendered)
        self.assertNotIn("namespaceSelector: {}", rendered)

        dns = self.network_policy(
            rendered,
            "coderushoj-infra-allow-rocketmq-dns-egress",
        )
        self.assertIn("kubernetes.io/metadata.name: kube-system", dns)
        self.assertIn("k8s-app: kube-dns", dns)
        self.assertIn("values: [rocketmq-broker, rocketmq-topic-bootstrap]", dns)

        broker_egress = self.network_policy(
            rendered,
            "coderushoj-infra-allow-rocketmq-broker-egress",
        )
        self.assertIn("app.kubernetes.io/component: rocketmq-broker", broker_egress)
        self.assertIn("app.kubernetes.io/component: rocketmq-namesrv", broker_egress)
        self.assertIn("port: 9876", broker_egress)

        topic_egress = self.network_policy(
            rendered,
            "coderushoj-infra-allow-rocketmq-topic-bootstrap-egress",
        )
        for component, port in (
            ("rocketmq-namesrv", 9876),
            ("rocketmq-broker", 10911),
        ):
            self.assertIn(f"app.kubernetes.io/component: {component}", topic_egress)
            self.assertIn(f"port: {port}", topic_egress)

        namesrv_ingress = self.network_policy(
            rendered,
            "coderushoj-infra-allow-rocketmq-namesrv-ingress",
        )
        self.assertIn("values: [rocketmq-broker, rocketmq-topic-bootstrap]", namesrv_ingress)
        self.assertIn("port: 9876", namesrv_ingress)

        broker_ingress = self.network_policy(
            rendered,
            "coderushoj-infra-allow-rocketmq-broker-ingress",
        )
        self.assertIn("app.kubernetes.io/component: rocketmq-topic-bootstrap", broker_ingress)
        self.assertIn("port: 10911", broker_ingress)

    def test_rocketmq_bootstrap_waits_for_and_verifies_a_routable_broker(self):
        rendered = self.render()
        topic_job = rendered.split(
            "name: coderushoj-infra-rocketmq-topics", 1
        )[1].split("\n---", 1)[0]
        self.assertIn(
            'until sh mqadmin clusterList -n "$namesrv" 2>/dev/null '
            "| grep -Fq CodeRushCluster",
            topic_job,
        )
        self.assertIn(
            'until sh mqadmin topicRoute -n "$namesrv" -t submission-topic '
            "2>/dev/null | grep -Fq broker-a",
            topic_job,
        )

    def test_local_mysql_supports_bulk_imports_within_workstation_budget(self):
        rendered = self.render()

        mysql = rendered.split(
            "kind: StatefulSet\nmetadata:\n  name: coderushoj-infra-mysql\n",
            1,
        )[1].split("\n---", 1)[0]
        mysql_memory = re.search(
            r"resources:\n"
            r"\s+limits:\n"
            r"\s+cpu: [^\n]+\n"
            r"\s+memory: (\d+)(Mi|Gi)\n"
            r"\s+requests:\n"
            r"\s+cpu: [^\n]+\n"
            r"\s+memory: (\d+)(Mi|Gi)",
            mysql,
        )
        self.assertIsNotNone(mysql_memory, "MySQL memory resources were not rendered")
        limit_value, limit_unit, request_value, request_unit = mysql_memory.groups()
        limit_mib = int(limit_value) * (1024 if limit_unit == "Gi" else 1)
        request_mib = int(request_value) * (1024 if request_unit == "Gi" else 1)
        self.assertGreaterEqual(
            limit_mib,
            2048,
            "local MySQL needs 2 GiB of cgroup headroom for transactional problem imports",
        )
        self.assertEqual(
            request_mib,
            512,
            "local MySQL request must remain scheduler-visible without consuming import headroom",
        )

        requests = re.findall(r"requests:\n\s+cpu: [^\n]+\n\s+memory: (\d+)(Mi|Gi)", rendered)
        self.assertTrue(requests, "no workload memory requests were rendered")
        total_mib = sum(int(value) * (1024 if unit == "Gi" else 1) for value, unit in requests)
        # Leave at least 2.5 GiB of an 8 GiB Colima VM for application Pods,
        # Kubernetes system Pods, the container runtime, and transient imports.
        self.assertLessEqual(total_mib, 5632)

    def test_production_profile_keeps_secrets_external(self):
        rendered = self.render("--values", str(CHART / "values-production.yaml"))
        self.assertIn("coderushoj-production-secrets", rendered)
        self.assertNotIn("kind: Secret", rendered)
        self.assertNotIn("axllent/mailpit", rendered)
        self.assertGreaterEqual(rendered.count("automountServiceAccountToken: false"), 6)
        self.assertNotIn(
            "name: coderushoj-infra-allow-applications-mailpit",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
