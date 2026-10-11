variable "function_name" { type = string }
variable "source_dir" { type = string }
variable "handler" {
  type    = string
  default = "handler.handler"
}
variable "timeout" { type = number }
variable "memory_size" { type = number }
variable "log_retention_days" { type = number }
variable "layers" {
  type    = list(string)
  default = []
}
variable "environment" { type = map(string) }
variable "reserved_concurrency" {
  description = "-1 = sin reserva; 0 = bloqueada."
  type        = number
  default     = -1
}
variable "vpc_config" {
  description = "null = Lambda sin VPC. Si se define, se adjunta AWSLambdaVPCAccessExecutionRole."
  type = object({
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
  default = null
}

variable "subnet_ids" {
  type    = list(string)
  default = []
}

variable "security_group_ids" {
  type    = list(string)
  default = []
}

locals {
  # vpc_config explícito tiene prioridad; si no, subnet_ids/security_group_ids (solo si hay subnets).
  effective_vpc = var.vpc_config != null ? var.vpc_config : (length(var.subnet_ids) > 0 ? {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  } : null)
}

variable "policy_statements" {
  description = "Permisos adicionales de mínimo privilegio (además de logs y X-Ray)."
  type = list(object({
    sid       = string
    actions   = list(string)
    resources = list(string)
  }))
  default = []
}

data "archive_file" "zip" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.root}/.build/${var.function_name}.zip"
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "inline" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }

  statement {
    sid       = "XRay"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  dynamic "statement" {
    for_each = local.effective_vpc == null ? [] : [1]
    content {
      sid       = "ENIVpc"
      actions   = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"]
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = var.policy_statements
    content {
      sid       = statement.value.sid
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy" "this" {
  name   = "minimo-privilegio"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.inline.json
}

resource "aws_iam_role_policy_attachment" "vpc_access" {
  count      = local.effective_vpc == null ? 0 : 1
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_lambda_function" "this" {
  function_name = var.function_name
  role          = aws_iam_role.this.arn
  runtime       = "python3.12"
  handler       = var.handler
  architectures = ["arm64"]

  filename         = data.archive_file.zip.output_path
  source_code_hash = data.archive_file.zip.output_base64sha256

  timeout                        = var.timeout
  memory_size                    = var.memory_size
  reserved_concurrent_executions = var.reserved_concurrency
  layers                         = var.layers

  environment {
    variables = var.environment
  }

  dynamic "vpc_config" {
    for_each = local.effective_vpc == null ? [] : [local.effective_vpc]
    content {
      subnet_ids         = vpc_config.value.subnet_ids
      security_group_ids = vpc_config.value.security_group_ids
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.this.name
  }

  depends_on = [aws_iam_role_policy.this, aws_iam_role_policy_attachment.vpc_access]
}

output "function_arn" { value = aws_lambda_function.this.arn }
output "function_name" { value = aws_lambda_function.this.function_name }
output "role_arn" { value = aws_iam_role.this.arn }
output "log_group_name" { value = aws_cloudwatch_log_group.this.name }
