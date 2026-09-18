variable "aws_region" {
  description = "AWS region for the EC2 instance, DynamoDB tables, and deployment bucket."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix used for AWS resource names. Keep this DNS-safe."
  type        = string
  default     = "role-discovery"
}

variable "instance_type" {
  description = "EC2 size. The Arm-based t4g.small keeps the always-on portfolio stack under $20/month; scans are sequential to fit its 2 GiB RAM."
  type        = string
  default     = "t4g.small"

  validation {
    condition     = startswith(var.instance_type, "t4g.")
    error_message = "The Ubuntu AMI and deployment image are Arm64; choose a t4g instance type."
  }
}

variable "root_volume_size_gib" {
  description = "Size of the encrypted EC2 root volume."
  type        = number
  default     = 20
}

variable "auto_stop_after_minutes" {
  description = "Automatically stop the portfolio instance this many minutes after boot to cap demo cost. Set to 0 to disable."
  type        = number
  default     = 0

  validation {
    condition     = var.auto_stop_after_minutes == 0 || var.auto_stop_after_minutes >= 60
    error_message = "auto_stop_after_minutes must be 0 (disabled) or at least 60 minutes."
  }
}

variable "k3s_channel" {
  description = "K3s release channel used by the official installer."
  type        = string
  default     = "stable"
}

variable "allowed_http_cidrs" {
  description = "CIDRs allowed to reach HTTP port 80. Leave empty and use SSM port forwarding. Never use 0.0.0.0/0 until authentication and TLS are configured."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.allowed_http_cidrs, "0.0.0.0/0") && !contains(var.allowed_http_cidrs, "::/0")
    error_message = "This application has write endpoints and no login yet; unrestricted public HTTP is intentionally blocked."
  }
}

variable "github_oidc_subject" {
  description = "Exact GitHub OIDC sub claim allowed to deploy. The default uses this repository's immutable owner and repository IDs."
  type        = string
  default     = "repo:TheSongib@61258600/role-discovery-platform@1366373286:ref:refs/heads/main"
}

variable "github_oidc_provider_arn" {
  description = "Existing GitHub Actions OIDC provider ARN. Leave blank to create it; set this when the AWS account already has one."
  type        = string
  default     = ""
}

variable "scan_history_retention_days" {
  description = "Days DynamoDB retains scan-run history; jobs and keyword settings do not expire."
  type        = number
  default     = 90

  validation {
    condition     = var.scan_history_retention_days >= 7
    error_message = "scan_history_retention_days must be at least 7 days."
  }
}
