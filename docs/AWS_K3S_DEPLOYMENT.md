# AWS + k3s deployment guide

This runbook moves JobTracker from the home Linux server to a small, always-on
AWS environment while keeping the application architecture horizontally
scalable.

## Architecture

```text
GitHub Actions --OIDC--> ECR Public + private S3 deployment bundle
                                   |
                                   v (SSM deploy command)
Browser --SSM tunnel--> EC2 t4g.small / single-node k3s
                              |              |
                              |              +--> FastAPI + React Deployment
                              |              +--> scheduled scan CronJob
                              |                         |
                              +-- instance IAM role ----+--> DynamoDB
                                                            jobs table
                                                            state/locks table
```

Terraform creates:

- A custom VPC, public subnet, internet gateway, and tightly scoped security
  group. SSH and the Kubernetes API are not exposed.
- One Ubuntu 24.04 Arm instance running k3s on `t4g.small` (2 vCPU, 2 GiB).
- A 20 GiB encrypted gp3 root volume and a 2 GiB swap file on that encrypted
  volume for short Chromium memory peaks.
- Two encrypted DynamoDB on-demand tables with point-in-time recovery and
  deletion protection: one for jobs and one for scan state, locks, and keyword
  settings. Scan history expires after 90 days by default.
- A stateless web Deployment and a separate CronJob. The CronJob scans every 15
  minutes on weekdays from 7 AM to 8 PM Eastern and hourly otherwise.
- A private, versioned S3 bucket for short-lived deployment bundles and a
  public ECR repository for the image.
- GitHub OIDC deployment credentials and Systems Manager access. No persistent
  AWS access key is stored in GitHub or on the instance.

The site stays private by default because it has write endpoints and no login.
Access it through an authenticated Systems Manager tunnel.

## Cost target

Using September 2026 us-east-1 list prices, the steady fixed cost is about
**$17.51/month before tax**:

| Resource | Approximate monthly cost |
|---|---:|
| `t4g.small`, 730 hours at $0.0168/hour | $12.26 |
| Public IPv4, 730 hours at $0.005/hour | $3.65 |
| 20 GiB gp3 at $0.08/GiB-month | $1.60 |
| DynamoDB, S3, and ECR at this personal traffic level | usually pennies |

AWS currently advertises up to 750 free `t4g.small` hours per month through
December 31, 2026, subject to its offer terms. Do not rely on a promotion for
the long-term budget. Create a budget alert before applying and confirm prices
for the selected region in the AWS Pricing Calculator.

This design avoids the recurring cost of RDS, NAT Gateway, an Application Load
Balancer, Elastic IP, and a managed Kubernetes control plane. DynamoDB is billed
on demand, so moving persistence out of the pod does not require an always-on
database server.

## 1. Select the correct AWS identity

The old `Figurado_Local_Dev` name comes from the access key selected by the AWS
CLI's default profile; it is not read from Terraform. Configure a new IAM
Identity Center profile (recommended), select it, and verify the account before
running Terraform:

```bash
aws configure sso --profile role-discovery-admin
aws sso login --profile role-discovery-admin
export AWS_PROFILE=role-discovery-admin
aws sts get-caller-identity
```

The returned account and ARN must be the account where this project should
live. The bootstrap identity needs permission to create IAM, EC2/VPC, S3,
DynamoDB, ECR Public, and SSM-related resources. Do not use the root user or
create root access keys.

After the new profile works, the obsolete `[default]`/`Figurado_Local_Dev`
credentials can be removed from `~/.aws/credentials`; keeping the project on a
named profile prevents accidental cross-account changes. The included
Terraform wrapper forwards `AWS_PROFILE` and mounts the AWS configuration
read-only.

## 2. Create the infrastructure

From the repository root:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
./tf init
./tf fmt -check
./tf validate
./tf plan -out=jobtracker.tfplan
./tf apply jobtracker.tfplan
```

Use a locally installed `terraform` command instead of `./tf` if preferred.
The wrapper uses Docker and pins Terraform 1.16.3.

Review `terraform.tfvars` before the plan:

- `allowed_http_cidrs = []` keeps the app private. Never use `0.0.0.0/0`
  before adding authentication and TLS.
- `auto_stop_after_minutes = 0` keeps it online continuously. A value of at
  least 60 converts it to an on-demand demo environment.
- Set `github_oidc_provider_arn` if the account already has the singleton
  GitHub OIDC provider.
- Update `github_oidc_subject` if the repository owner or repository changes.

Wait for bootstrap:

```bash
INSTANCE_ID=$(./tf output -raw instance_id)
REGION=$(./tf output -raw aws_region)
aws ssm start-session --region "$REGION" --target "$INSTANCE_ID"
```

Then, in the remote shell:

```bash
sudo cloud-init status --wait
sudo k3s kubectl get nodes
sudo swapon --show
exit
```

The node is deliberately single-node and not highly available. Durable state is
outside the cluster, so a later production evolution can add nodes and app
replicas without migrating data again. The current resource limits and
single-node capacity are optimized for this personal workload, not high
traffic.

## 3. Migrate the existing SQLite data

Migrate after Terraform creates the tables and before the first application
deployment. On the old server, stop the services so the source does not change,
then make a consistent SQLite copy:

```bash
sudo systemctl stop jobtracker jobtracker-frontend
sqlite3 /path/to/jobs.db ".backup '/tmp/jobtracker-jobs.db'"
```

Copy `/tmp/jobtracker-jobs.db` and, if present, `keywords.json` to the computer
running Terraform. From the repository root, install the Python dependencies
and obtain the Terraform outputs:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

JOBS_TABLE=$(infra/terraform/tf output -raw dynamodb_jobs_table)
STATE_TABLE=$(infra/terraform/tf output -raw dynamodb_state_table)
REGION=$(infra/terraform/tf output -raw aws_region)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

Validate the source, identity, region, and destination tables without writing:

```bash
python scripts/migrate_sqlite_to_dynamodb.py \
  --sqlite /path/to/jobtracker-jobs.db \
  --keywords /path/to/keywords.json \
  --jobs-table "$JOBS_TABLE" \
  --state-table "$STATE_TABLE" \
  --region "$REGION" \
  --profile "$AWS_PROFILE" \
  --confirm-account "$ACCOUNT_ID" \
  --dry-run
```

Remove `--keywords` if that file does not exist. When the counts and destination
account are correct, repeat the command without `--dry-run`. The migration uses
deterministic job keys and legacy scan IDs, so rerunning it is idempotent for
the copied data.

Do not delete the old files until the DynamoDB data and UI have been verified.
DynamoDB point-in-time recovery provides continuous recovery for the AWS data;
it is not a substitute for retaining the source during the cutover.

## 4. Configure and run GitHub Actions

With `gh` authenticated to this repository, run from `infra/terraform`:

```bash
gh variable set AWS_REGION --body "$(./tf output -raw aws_region)"
gh variable set AWS_DEPLOY_ROLE_ARN --body "$(./tf output -raw github_deploy_role_arn)"
gh variable set DEPLOYMENT_BUCKET --body "$(./tf output -raw deployment_bucket)"
gh variable set EC2_INSTANCE_ID --body "$(./tf output -raw instance_id)"
gh variable set ECR_REPOSITORY_URI --body "$(./tf output -raw ecr_repository_uri)"
```

These are resource identifiers, not secrets. If `gh` is unavailable, create the
same five repository variables under **Settings → Secrets and variables →
Actions → Variables**.

Pushes and pull requests run tests only. Start **Test and deploy to AWS k3s**
manually on the `main` branch for the first and subsequent deployments. The
workflow:

1. exchanges GitHub's OIDC token for short-lived AWS credentials;
2. builds and pushes an Arm64 container image;
3. uploads the Kubernetes bundle to S3;
4. uses SSM to apply it to k3s; and
5. waits for the web Deployment rollout.

The web pod receives AWS access through the EC2 instance role. Do not create a
Kubernetes secret containing AWS access keys.

## 5. Open the private site

```bash
cd infra/terraform
./instance tunnel
```

Keep that command running and open <http://localhost:8080>. If the instance was
manually stopped, run `./instance start` first. AWS does not automatically boot
an EC2 instance when a browser visits it, which is why the default for this
frequently used app is always on.

Optional notification settings remain in a Kubernetes secret:

```bash
sudo k3s kubectl -n jobtracker create secret generic jobtracker-secrets \
  --from-literal=NTFY_TOPIC='YOUR_TOPIC' \
  --dry-run=client -o yaml | sudo k3s kubectl apply -f -
sudo k3s kubectl -n jobtracker rollout restart deployment/jobtracker
```

## Operations

Useful commands in an SSM shell:

```bash
sudo k3s kubectl -n jobtracker get deployment,cronjob,jobs,pods,service,ingress
sudo k3s kubectl -n jobtracker logs deployment/jobtracker --tail=200
sudo k3s kubectl -n jobtracker logs job/NAME-OF-SCAN-JOB --tail=200
sudo k3s kubectl -n jobtracker create job --from=cronjob/jobtracker-scan manual-scan
sudo k3s kubectl -n jobtracker rollout status deployment/jobtracker
sudo journalctl -u k3s -n 200
```

Local instance helpers:

```bash
infra/terraform/instance status
infra/terraform/instance tunnel
infra/terraform/instance stop
infra/terraform/instance start
```

`CronJob.concurrencyPolicy: Forbid` prevents duplicate Kubernetes jobs, and a
conditional DynamoDB lock also prevents a manual web scan and CronJob scan from
overlapping. The lock expires if a worker dies.

Both DynamoDB tables have deletion protection. To intentionally destroy the
whole environment, first set `deletion_protection_enabled = false` on both table
resources, apply that change, confirm any required export, and only then run
`terraform destroy`.

## Important limits

- One k3s node means node maintenance or failure causes downtime. DynamoDB
  remains available and is not tied to that node.
- A `t4g.small` is sized for one user and sequential scans. To demonstrate real
  traffic scaling, add worker nodes (or migrate to EKS), deploy metrics-server
  plus an HPA, and revisit pod requests/limits. The persistence layer already
  supports multiple replicas.
- Swap is a deliberate cost optimization for this combined control-plane and
  workload node. Kubernetes generally recommends avoiding swap on production
  control-plane nodes.
- Public HTTPS and login are not included. Keep using SSM or one trusted `/32`
  CIDR until those are designed.
- ECR Public makes the application image readable by anyone; no credentials or
  runtime data are embedded in it.

## Primary references

- [K3s requirements](https://docs.k3s.io/installation/requirements)
- [K3s configuration](https://docs.k3s.io/installation/configuration)
- [Kubernetes swap management](https://kubernetes.io/docs/concepts/cluster-administration/swap-memory-management/)
- [DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/)
- [AWS T4g instances](https://aws.amazon.com/ec2/instance-types/t4/)
- [Amazon EBS gp3 pricing](https://aws.amazon.com/ebs/volume-types/)
- [Amazon VPC public IPv4 pricing](https://aws.amazon.com/vpc/pricing/)
- [AWS Systems Manager Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html)
- [GitHub Actions OIDC for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
