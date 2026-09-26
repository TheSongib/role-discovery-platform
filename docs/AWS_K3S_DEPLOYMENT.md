# AWS + k3s deployment guide

This runbook moves JobTracker from the home Linux server to a small, always-on
AWS environment while keeping the application architecture horizontally
scalable.

## Architecture

```text
GitHub Actions --OIDC--> ECR Public + private S3 deployment bundle
                                   |
                                   v (SSM deploy command)
Browser --HTTPS--> API Gateway --secret header--> Elastic IP
    |                                                |
    +-- admin login --> Cognito                 EC2 t4g.small / k3s
                                                    |          |
                                                    |          +--> web Deployment
                                                    |          +--> scan CronJob
                                                    +-- IAM ------> DynamoDB
```

Terraform creates:

- A custom VPC, public subnet, internet gateway, and tightly scoped security
  group. SSH and the Kubernetes API are not exposed.
- One Ubuntu 24.04 Arm instance running k3s on `t4g.small` (2 vCPU, 2 GiB).
- A stable Elastic IP origin and an API Gateway HTTP API for public HTTPS.
- A Cognito user pool with self-registration disabled, TOTP MFA required, and
  an `admins` group for state-changing operations.
- A generated origin-verification secret in SSM Parameter Store. API Gateway
  injects it, and FastAPI rejects direct-origin requests that do not have it.
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

Anonymous users can view active jobs and scan history. Running a manual scan,
hiding jobs, viewing hidden jobs, and editing keywords require Cognito login
and membership in the `admins` group. OAuth uses the authorization-code flow
with PKCE; the verified ID token is held in a Secure, HttpOnly cookie rather
than browser storage.

## Cost target

Using September 2026 us-east-1 list prices, the steady fixed cost is about
**$17.51/month before tax**:

| Resource | Approximate monthly cost |
|---|---:|
| `t4g.small`, 730 hours at $0.0168/hour | $12.26 |
| Public IPv4, 730 hours at $0.005/hour | $3.65 |
| 20 GiB gp3 at $0.08/GiB-month | $1.60 |
| API Gateway, Cognito, CloudWatch, DynamoDB, S3, and ECR at this traffic level | usually pennies |

AWS currently advertises up to 750 free `t4g.small` hours per month through
December 31, 2026, subject to its offer terms. Do not rely on a promotion for
the long-term budget. Create a budget alert before applying and confirm prices
for the selected region in the AWS Pricing Calculator.

The Elastic IP replaces the instance's auto-assigned public address, so it does
not add a second steady public-IPv4 charge. This design avoids the recurring
cost of RDS, NAT Gateway, an Application Load Balancer, and a managed Kubernetes
control plane. DynamoDB and API Gateway are billed on demand, so persistence
and HTTPS do not require another always-on server.

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

- `allowed_http_cidrs` optionally allows a trusted `/32` to test the origin
  during bootstrap.
- Keep `enable_public_gateway_origin = false` until the guarded application
  has been deployed. Set it to `true` only after direct-origin requests return
  `403`; this allows API Gateway's changing source addresses to reach port 80.
- `auto_stop_after_minutes = 0` keeps it online continuously. A value of at
  least 60 converts it to an on-demand demo environment.
- Set `github_oidc_provider_arn` if the account already has the singleton
  GitHub OIDC provider.
- Update `github_oidc_subject` if the repository owner or repository changes.
  Its default wildcard trusts branch refs only from this repository, allowing
  manually selected branches to use the deployment role without trusting tags
  or pull-request refs.

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
gh variable set PUBLIC_BASE_URL --body "$(./tf output -raw application_url)"
```

These are resource identifiers, not secrets. If `gh` is unavailable, create the
same six repository variables under **Settings → Secrets and variables →
Actions → Variables**.

Pull requests run tests only. Pushes to `main` run the tests and deploy
automatically. To validate another branch in AWS before merging, start **Test
and deploy to AWS k3s** manually, select that branch, and run the workflow. A
manual branch deployment replaces the application in the same environment; it
does not create an isolated preview environment. Re-run the workflow for
`main` to restore the main-branch version if the branch is not merged. The
workflow:

1. exchanges GitHub's OIDC token for short-lived AWS credentials;
2. builds and pushes an Arm64 container image;
3. uploads the Kubernetes bundle to S3;
4. uses SSM to apply it to k3s; and
5. waits for the web Deployment rollout.

The web pod receives AWS access through the EC2 instance role. Do not create a
Kubernetes secret containing AWS access keys.

## 5. Create the administrator

Self-registration is intentionally disabled. Create only the administrator
you need and add it to the group Terraform created:

```bash
POOL_ID=$(infra/terraform/tf output -raw cognito_user_pool_id)
REGION=$(infra/terraform/tf output -raw aws_region)
ADMIN_EMAIL='you@example.com'

aws cognito-idp admin-create-user \
  --region "$REGION" \
  --user-pool-id "$POOL_ID" \
  --username "$ADMIN_EMAIL" \
  --user-attributes Name=email,Value="$ADMIN_EMAIL" Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL

aws cognito-idp admin-add-user-to-group \
  --region "$REGION" \
  --user-pool-id "$POOL_ID" \
  --username "$ADMIN_EMAIL" \
  --group-name admins
```

The invitation contains a temporary password. On first login, Cognito requires
a replacement password and TOTP authenticator enrollment.

## 6. Open the public site

After the protected pod is healthy, set
`enable_public_gateway_origin = true`, review the one-rule security-group plan,
and apply it:

```bash
cd infra/terraform
./tf plan -out=gateway-origin.tfplan
./tf apply gateway-origin.tfplan
./tf output -raw application_url
```

Open that HTTPS URL. Visitors can browse without an account; use **Admin
login** for management controls. The Elastic IP is an origin address, not the
normal application URL, and direct requests to it receive `403` except for the
minimal health endpoint.

### Use `songib.net` with Squarespace DNS

The custom domain is deliberately rolled out in two phases because Squarespace,
not Terraform, controls the authoritative DNS zone. This avoids switching the
application or Cognito to a hostname before its certificate and routing are
ready.

The local `terraform.tfvars` should initially contain:

```hcl
custom_domain_name   = "songib.net"
enable_custom_domain = false
```

Apply once to request the free, non-exportable ACM certificate:

```bash
cd infra/terraform
./tf plan -out=custom-domain-certificate.tfplan
./tf apply custom-domain-certificate.tfplan
./tf output -json custom_domain_validation_records
```

In Squarespace, open **Domains → songib.net → DNS → DNS Settings → Custom
Records** and add each record from that output. Use its `squarespace_name` as
the Name, `CNAME` as the Type, and `value` as the Data. Keep the existing apex
record in place during certificate validation.

Wait until ACM reports `ISSUED`:

```bash
CERTIFICATE_ARN=$(./tf output -raw custom_domain_certificate_arn)
aws acm wait certificate-validated \
  --region "$(./tf output -raw aws_region)" \
  --certificate-arn "$CERTIFICATE_ARN"
```

Then set `enable_custom_domain = true`, plan, and apply again. This creates the
API Gateway domain and mapping and permits both the AWS URL and `songib.net` as
Cognito callback/logout URLs:

```bash
./tf plan -out=custom-domain-enable.tfplan
./tf apply custom-domain-enable.tfplan
./tf output -json custom_domain_dns_record
```

In Squarespace, disable DNSSEC if it is enabled, remove only the existing apex
web-hosting A/AAAA/ALIAS records for `@`, and create the record shown by that
last output: Type `ALIAS`, Name `@`, and Data equal to `value`. Do not remove
MX or TXT records used for email or verification.

After `https://songib.net` responds, update the GitHub Actions repository
variable and deploy the application once so its OAuth and origin configuration
uses the new URL:

```bash
gh variable set PUBLIC_BASE_URL --body "$(./tf output -raw application_url)"
```

The AWS-provided URL remains available as `default_application_url` for
recovery and testing.

An SSM tunnel remains available for maintenance:

```bash
cd infra/terraform
./instance tunnel
```

Keep that command running and use it for origin troubleshooting. If the
instance was manually stopped, run `./instance start` first. AWS does not
automatically boot an EC2 instance when a browser visits it, which is why the
default for this frequently used app is always on.

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

Both DynamoDB tables and the Cognito user pool have deletion protection. To
intentionally destroy the whole environment, first disable protection on those
three resources, apply that change, confirm any required export, and only then
run `terraform destroy`.

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
- The `songib.net` DNS zone remains outside Terraform in Squarespace, so its
  ACM validation CNAME and API Gateway ALIAS must be maintained there.
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
- [API Gateway HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api.html)
- [Cognito managed login](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-managed-login.html)
- [Cognito authorization code grant with PKCE](https://docs.aws.amazon.com/cognito/latest/developerguide/using-pkce-in-authorization-code.html)
- [AWS Systems Manager Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html)
- [GitHub Actions OIDC for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
