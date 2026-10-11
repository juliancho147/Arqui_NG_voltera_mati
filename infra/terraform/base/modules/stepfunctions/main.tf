variable "name" { type = string }
variable "type" { type = string }
variable "definition_template" { type = string }
variable "log_retention_days" { type = number }
variable "log_level" { type = string }
variable "lambda_tarifas_arn" { type = string }
variable "lambda_calculo_arn" { type = string }
variable "lambda_facturacion_arn" { type = string }
variable "dlq_transactions_url" { type = string }
variable "dlq_transactions_arn" { type = string }
variable "comprobantes_queue_url" { type = string }
variable "comprobantes_queue_arn" { type = string }
variable "retry_max_attempts" { type = number }
variable "retry_interval_seconds" { type = number }
variable "retry_backoff_rate" { type = number }

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/vendedlogs/states/${var.name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "inline" {
  statement {
    sid     = "InvocarLambdas"
    actions = ["lambda:InvokeFunction"]
    resources = [
      var.lambda_tarifas_arn,
      var.lambda_calculo_arn,
      var.lambda_facturacion_arn,
    ]
  }

  statement {
    sid       = "PublicarColas"
    actions   = ["sqs:SendMessage"]
    resources = [var.dlq_transactions_arn, var.comprobantes_queue_arn]
  }

  # Requeridos por AWS para entregar logs de Step Functions (no admiten restricción de recurso).
  statement {
    sid = "LogDelivery"
    actions = [
      "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "XRay"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy" "this" {
  name   = "minimo-privilegio"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.inline.json
}

resource "aws_sfn_state_machine" "this" {
  name     = var.name
  type     = var.type
  role_arn = aws_iam_role.this.arn

  definition = templatefile(var.definition_template, {
    lambda_tarifas_arn     = var.lambda_tarifas_arn
    lambda_calculo_arn     = var.lambda_calculo_arn
    lambda_facturacion_arn = var.lambda_facturacion_arn
    dlq_transactions_url   = var.dlq_transactions_url
    comprobantes_queue_url = var.comprobantes_queue_url
    retry_max_attempts     = var.retry_max_attempts
    retry_interval_seconds = var.retry_interval_seconds
    retry_backoff_rate     = var.retry_backoff_rate
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.this.arn}:*"
    include_execution_data = true
    level                  = var.log_level
  }

  tracing_configuration {
    enabled = true
  }

  depends_on = [aws_iam_role_policy.this]
}

output "state_machine_arn" { value = aws_sfn_state_machine.this.arn }
output "state_machine_name" { value = aws_sfn_state_machine.this.name }
output "role_arn" { value = aws_iam_role.this.arn }
output "log_group_name" { value = aws_cloudwatch_log_group.this.name }
