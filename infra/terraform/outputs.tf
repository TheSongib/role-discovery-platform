output "instance_id" {
  description = "EC2 instance managed by Systems Manager."
  value       = aws_instance.node.id
}

output "public_ip" {
  description = "Current auto-assigned public IPv4 address. It changes after stop/start; port 80 is closed unless allowed_http_cidrs is set."
  value       = aws_instance.node.public_ip
}

output "deployment_bucket" {
  description = "S3 bucket used for short-lived deployment bundles."
  value       = aws_s3_bucket.deployments.id
}

output "dynamodb_jobs_table" {
  description = "DynamoDB table containing job listings."
  value       = aws_dynamodb_table.jobs.name
}

output "dynamodb_state_table" {
  description = "DynamoDB table containing scan status, locks, and keyword settings."
  value       = aws_dynamodb_table.state.name
}

output "ecr_repository_uri" {
  description = "Public ECR repository used by the deployment workflow."
  value       = aws_ecrpublic_repository.app.repository_uri
}

output "github_deploy_role_arn" {
  description = "Short-lived OIDC role assumed by GitHub Actions."
  value       = aws_iam_role.github_deploy.arn
}

output "aws_region" {
  description = "AWS region used by the deployment workflow."
  value       = var.aws_region
}

output "ssm_port_forward_command" {
  description = "Run this locally, then open http://localhost:8080. Requires AWS CLI and the Session Manager plugin."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.node.id} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"80\"],\"localPortNumber\":[\"8080\"]}'"
}

output "start_command" {
  description = "Start the stopped portfolio instance."
  value       = "aws ec2 start-instances --region ${var.aws_region} --instance-ids ${aws_instance.node.id}"
}

output "stop_command" {
  description = "Stop the portfolio instance immediately when the demo is finished."
  value       = "aws ec2 stop-instances --region ${var.aws_region} --instance-ids ${aws_instance.node.id}"
}
