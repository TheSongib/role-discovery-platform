resource "random_password" "origin" {
  length  = 48
  special = false
}

resource "aws_ssm_parameter" "origin_secret" {
  name        = "/${var.project_name}/origin-verify-secret"
  description = "Shared secret used to verify API Gateway origin requests"
  type        = "SecureString"
  value       = random_password.origin.result
}

# A stable origin avoids coupling Cognito and API Gateway to an address that
# changes whenever the low-cost EC2 node is stopped and started.
resource "aws_eip" "node" {
  domain = "vpc"

  tags = { Name = "${var.project_name}-origin" }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_eip_association" "node" {
  allocation_id = aws_eip.node.id
  instance_id   = aws_instance.node.id
}

resource "aws_cognito_user_pool" "admin" {
  name                     = "${var.project_name}-admins"
  deletion_protection      = "ACTIVE"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "ON"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  software_token_mfa_configuration {
    enabled = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  user_attribute_update_settings {
    attributes_require_verification_before_update = ["email"]
  }
}

resource "aws_cognito_user_group" "admins" {
  name         = "admins"
  description  = "Users allowed to run scans and change JobTracker state"
  user_pool_id = aws_cognito_user_pool.admin.id
}

resource "aws_cognito_user_pool_domain" "login" {
  domain       = "${var.project_name}-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.admin.id
}

resource "aws_apigatewayv2_api" "app" {
  name          = var.project_name
  protocol_type = "HTTP"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${var.project_name}"
  retention_in_days = 14
}

resource "aws_apigatewayv2_integration" "app" {
  api_id                 = aws_apigatewayv2_api.app.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = "http://${aws_eip.node.public_ip}"
  payload_format_version = "1.0"
  timeout_milliseconds   = 30000

  request_parameters = {
    "overwrite:header.x-origin-verify" = random_password.origin.result
  }
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.app.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.app.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.app.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 20
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      sourceIp       = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
    })
  }

  depends_on = [aws_apigatewayv2_route.default]
}

# DNS stays with the domain provider. Terraform requests the certificate and
# exposes the records that must be added there before enable_custom_domain is
# turned on.
resource "aws_acm_certificate" "app" {
  count = var.custom_domain_name == "" ? 0 : 1

  domain_name       = var.custom_domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "app" {
  count = var.enable_custom_domain ? 1 : 0

  certificate_arn = aws_acm_certificate.app[0].arn
  validation_record_fqdns = [
    for option in aws_acm_certificate.app[0].domain_validation_options :
    option.resource_record_name
  ]
}

resource "aws_apigatewayv2_domain_name" "app" {
  count = var.enable_custom_domain ? 1 : 0

  domain_name = var.custom_domain_name

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.app[0].certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "app" {
  count = var.enable_custom_domain ? 1 : 0

  api_id      = aws_apigatewayv2_api.app.id
  domain_name = aws_apigatewayv2_domain_name.app[0].id
  stage       = aws_apigatewayv2_stage.default.id
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.project_name}-web"
  user_pool_id = aws_cognito_user_pool.admin.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["email", "openid"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls = concat(
    ["${aws_apigatewayv2_api.app.api_endpoint}/api/auth/callback"],
    var.enable_custom_domain ? ["https://${var.custom_domain_name}/api/auth/callback"] : [],
  )
  logout_urls = concat(
    ["${aws_apigatewayv2_api.app.api_endpoint}/"],
    var.enable_custom_domain ? ["https://${var.custom_domain_name}/"] : [],
  )
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
  access_token_validity         = 60
  id_token_validity             = 60
  refresh_token_validity        = 1

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
