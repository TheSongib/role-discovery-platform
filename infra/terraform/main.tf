data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ssm_parameter" "ubuntu_ami" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
}

locals {
  node_name           = "role-discovery"
  deployment_bucket   = "${var.project_name}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  jobs_table_name     = "${var.project_name}-jobs"
  state_table_name    = "${var.project_name}-state"
  oidc_provider_arn   = var.github_oidc_provider_arn != "" ? var.github_oidc_provider_arn : one(aws_iam_openid_connect_provider.github[*].arn)
  github_oidc_subject = var.github_oidc_subject
  application_url     = var.enable_custom_domain ? "https://${var.custom_domain_name}" : aws_apigatewayv2_api.app.api_endpoint
}

resource "aws_vpc" "main" {
  # Keep this distinct from k3s's default 10.42.0.0/16 pod network.
  cidr_block           = "10.80.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = var.project_name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = var.project_name }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.80.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = { Name = "${var.project_name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project_name}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "node" {
  name_prefix = "${var.project_name}-"
  description = "k3s node; management uses SSM, so SSH and Kubernetes APIs stay closed"
  vpc_id      = aws_vpc.main.id

  dynamic "ingress" {
    for_each = toset(var.enable_public_gateway_origin ? ["0.0.0.0/0"] : var.allowed_http_cidrs)
    content {
      description = var.enable_public_gateway_origin ? "API Gateway origin; application verifies a secret header" : "JobTracker HTTP from an explicitly approved CIDR"
      protocol    = "tcp"
      from_port   = 80
      to_port     = 80
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    description = "Updates, scraper targets, AWS APIs, and container registries"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-node" }
}

resource "aws_s3_bucket" "deployments" {
  bucket        = local.deployment_bucket
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "deployments" {
  bucket = aws_s3_bucket.deployments.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "deployments" {
  bucket = aws_s3_bucket.deployments.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "deployments" {
  bucket = aws_s3_bucket.deployments.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "deployments" {
  bucket = aws_s3_bucket.deployments.id

  rule {
    id     = "expire-deployment-bundles"
    status = "Enabled"

    filter {
      prefix = "deployments/"
    }

    expiration {
      days = 7
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.deployments]
}

resource "aws_dynamodb_table" "jobs" {
  name         = local.jobs_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_key"

  attribute {
    name = "job_key"
    type = "S"
  }

  attribute {
    name = "company"
    type = "S"
  }

  attribute {
    name = "feed_bucket"
    type = "S"
  }

  attribute {
    name = "feed_sort"
    type = "S"
  }

  global_secondary_index {
    name            = "company-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "company"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "job_key"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "feed-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "feed_bucket"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "feed_sort"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = true
}

resource "aws_dynamodb_table" "state" {
  name         = local.state_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = true
}

resource "aws_iam_role" "node" {
  name = "${var.project_name}-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "node_ssm" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "node_storage" {
  name = "storage"
  role = aws_iam_role.node.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.deployments.arn}/deployments/*"
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = aws_ssm_parameter.origin_secret.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:BatchWriteItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeTable",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:UpdateItem",
        ]
        Resource = [
          aws_dynamodb_table.jobs.arn,
          "${aws_dynamodb_table.jobs.arn}/index/*",
          aws_dynamodb_table.state.arn,
          "${aws_dynamodb_table.state.arn}/index/*",
        ]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "node" {
  name = "${var.project_name}-node"
  role = aws_iam_role.node.name
}

resource "aws_instance" "node" {
  ami                         = data.aws_ssm_parameter.ubuntu_ami.value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.node.id]
  iam_instance_profile        = aws_iam_instance_profile.node.name
  associate_public_ip_address = true
  user_data_replace_on_change = false

  metadata_options {
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 2
    http_tokens                 = "required"
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = var.root_volume_size_gib
  }

  dynamic "credit_specification" {
    for_each = startswith(var.instance_type, "t") ? [1] : []
    content {
      cpu_credits = "standard"
    }
  }

  user_data = templatefile("${path.module}/templates/user-data.sh.tftpl", {
    auto_stop_after_minutes = var.auto_stop_after_minutes
    aws_region              = var.aws_region
    deployment_script = templatefile("${path.module}/templates/jobtracker-deploy.sh.tftpl", {
      aws_region                  = var.aws_region
      cognito_admin_group         = aws_cognito_user_group.admins.name
      cognito_client_id           = aws_cognito_user_pool_client.web.id
      cognito_domain              = "https://${aws_cognito_user_pool_domain.login.domain}.auth.${var.aws_region}.amazoncognito.com"
      cognito_region              = var.aws_region
      cognito_user_pool_id        = aws_cognito_user_pool.admin.id
      jobs_table_name             = aws_dynamodb_table.jobs.name
      origin_secret_parameter     = aws_ssm_parameter.origin_secret.name
      public_base_url             = local.application_url
      scan_history_retention_days = var.scan_history_retention_days
      state_table_name            = aws_dynamodb_table.state.name
    })
    k3s_channel = var.k3s_channel
    node_name   = local.node_name
  })

  # The guest's automatic poweroff must stop, rather than terminate, EC2.
  instance_initiated_shutdown_behavior = "stop"

  tags = { Name = var.project_name }

  # Releasing a newer Ubuntu AMI must not unexpectedly replace the node during
  # an unrelated Terraform change. Rebuild explicitly with `-replace` instead.
  lifecycle {
    # User data runs only at first boot. Updating it in-place restarts EC2 but
    # does not rerun the script, so handle bootstrap changes explicitly and
    # avoid needlessly restarting the stable Elastic IP-backed node.
    ignore_changes = [ami, user_data]
  }

  depends_on = [
    aws_iam_role_policy_attachment.node_ssm,
    aws_iam_role_policy.node_storage,
  ]
}

resource "aws_ecrpublic_repository" "app" {
  provider        = aws.us_east_1
  repository_name = var.project_name

  catalog_data {
    description = "Role Discovery Platform container image"
  }
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.github_oidc_provider_arn == "" ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_deploy" {
  name = "${var.project_name}-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = local.github_oidc_subject
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "deploy"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr-public:BatchCheckLayerAvailability",
          "ecr-public:CompleteLayerUpload",
          "ecr-public:InitiateLayerUpload",
          "ecr-public:PutImage",
          "ecr-public:UploadLayerPart",
        ]
        Resource = aws_ecrpublic_repository.app.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.deployments.arn}/deployments/*"
      },
      {
        Effect = "Allow"
        Action = ["ssm:SendCommand"]
        Resource = [
          aws_instance.node.arn,
          "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetCommandInvocation"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:StartInstances"]
        Resource = aws_instance.node.arn
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstanceStatus",
          "ssm:DescribeInstanceInformation",
        ]
        Resource = "*"
      }
    ]
  })
}
