import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def service_setting(service_name: str, setting: str) -> str:
    prefix = f"{setting}="
    for line in (ROOT / service_name).read_text().splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    raise AssertionError(f"{setting} is missing from {service_name}")


class ServiceSupervisionTests(unittest.TestCase):
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

    def test_deployment_only_restarts_preinstalled_services(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()

        self.assertNotIn("sudo tee", workflow)
        self.assertNotIn("systemctl daemon-reload", workflow)
        self.assertNotIn("systemctl enable", workflow)
        self.assertIn(
            "sudo -n /usr/bin/systemctl restart jobtracker\n",
            workflow,
        )
        self.assertIn(
            "sudo -n /usr/bin/systemctl restart jobtracker-frontend",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
