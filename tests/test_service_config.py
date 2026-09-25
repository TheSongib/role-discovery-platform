import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def service_setting(service_name: str, setting: str) -> str:
    prefix = f"{setting}="
    for line in (ROOT / service_name).read_text().splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    raise AssertionError(f"{setting} is missing from {service_name}")


class LegacyServiceSupervisionTests(unittest.TestCase):
    def test_systemd_directly_supervises_uvicorn(self):
        command = service_setting("jobtracker.service", "ExecStart")

        self.assertIn("python3 -m uvicorn api:app", command)
        self.assertNotIn("bash", command)
        self.assertNotIn("&", command)
        self.assertEqual(
            service_setting("jobtracker.service", "Restart"),
            "always",
        )

    def test_frontend_runs_in_a_separate_service(self):
        api_command = service_setting("jobtracker.service", "ExecStart")
        frontend_command = service_setting(
            "jobtracker-frontend.service",
            "ExecStart",
        )

        self.assertNotIn("serve -s frontend", api_command)
        self.assertIn("npx serve -s frontend/dist", frontend_command)


class KubernetesDeploymentTests(unittest.TestCase):
    def test_workflow_uses_oidc_ecr_and_ssm(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()

        self.assertIn("id-token: write", workflow)
        self.assertIn("amazon-ecr-login@", workflow)
        self.assertIn("aws ssm send-command", workflow)
        self.assertIn("aws ec2 start-instances", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("platforms: linux/arm64", workflow)
        self.assertNotIn("/home/bcg600", workflow)

    def test_manifest_uses_stateless_app_and_scheduled_worker(self):
        manifest = (ROOT / "k8s" / "aws.yaml").read_text()

        self.assertIn("replicas: 1", manifest)
        self.assertIn("DATABASE_BACKEND: dynamodb", manifest)
        self.assertIn("kind: CronJob", manifest)
        self.assertIn("concurrencyPolicy: Forbid", manifest)
        self.assertIn("- scheduled_scan.py", manifest)
        self.assertIn("path: /api/health", manifest)
        self.assertIn("image: IMAGE_PLACEHOLDER", manifest)
        self.assertIn('AUTH_ENABLED: "true"', manifest)
        self.assertIn("name: jobtracker-origin-secret", manifest)
        self.assertNotIn("PersistentVolume", manifest)
        self.assertNotIn("mountPath: /data", manifest)

    def test_terraform_caps_demo_cost(self):
        main = (ROOT / "infra" / "terraform" / "main.tf").read_text()
        variables = (ROOT / "infra" / "terraform" / "variables.tf").read_text()
        user_data = (
            ROOT / "infra" / "terraform" / "templates" / "user-data.sh.tftpl"
        ).read_text()
        deploy_helper = (
            ROOT
            / "infra"
            / "terraform"
            / "templates"
            / "jobtracker-deploy.sh.tftpl"
        ).read_text()

        auth = (ROOT / "infra" / "terraform" / "auth.tf").read_text()

        self.assertIn('resource "aws_eip" "node"', auth)
        self.assertIn('resource "aws_apigatewayv2_api" "app"', auth)
        self.assertIn('resource "aws_cognito_user_pool" "admin"', auth)
        self.assertIn('mfa_configuration        = "ON"', auth)
        self.assertIn('deletion_protection      = "ACTIVE"', auth)
        self.assertIn('allow_admin_create_user_only = true', auth)
        self.assertIn('"overwrite:header.x-origin-verify"', auth)
        self.assertNotIn('resource "aws_ebs_volume"', main)
        self.assertIn('resource "aws_dynamodb_table" "jobs"', main)
        self.assertIn('resource "aws_dynamodb_table" "state"', main)
        self.assertIn('billing_mode = "PAY_PER_REQUEST"', main)
        self.assertIn('default     = "t4g.small"', variables)
        self.assertIn("http_put_response_hop_limit = 2", main)
        self.assertIn("portfolio-auto-stop.timer", user_data)
        self.assertIn("swapBehavior: LimitedSwap", user_data)
        self.assertIn("crictl rmi --prune", deploy_helper)
        self.assertIn("aws ssm get-parameter", deploy_helper)
        self.assertIn("jobtracker-origin-secret", deploy_helper)
        self.assertNotIn("jobtracker-backup", user_data)

        terraform_wrapper = (ROOT / "infra" / "terraform" / "tf").read_text()
        self.assertIn("AWS_PROFILE", terraform_wrapper)

    def test_container_builds_frontend_and_installs_chromium(self):
        dockerfile = (ROOT / "Dockerfile").read_text()

        self.assertIn("npm run build", dockerfile)
        self.assertIn("playwright install --with-deps chromium", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)


if __name__ == "__main__":
    unittest.main()
