output "instance_id" {
  description = "EC2 instance managed by Systems Manager."
  value       = aws_instance.node.id
}

output "public_ip" {
  description = "Stable Elastic IP for the guarded HTTP origin. Use application_url for normal access."
  value       = aws_eip.node.public_ip
}

output "application_url" {
  description = "Public HTTPS URL served by API Gateway. Anonymous visitors have read-only access."
  value       = aws_apigatewayv2_api.app.api_endpoint
}

output "cognito_user_pool_id" {
  description = "Cognito user pool used for administrator login."
  value       = aws_cognito_user_pool.admin.id
}

output "cognito_admin_group" {
  description = "Cognito group whose members can run scans and change application state."
  value       = aws_cognito_user_group.admins.name
}

output "cognito_login_domain" {
  description = "Cognito managed-login domain."
  value       = "https://${aws_cognito_user_pool_domain.login.domain}.auth.${var.aws_region}.amazoncognito.com"
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
