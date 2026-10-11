variable "name_prefix" { type = string }
variable "bus_name" { type = string }
variable "target_lambda_arn" { type = string }
variable "target_lambda_name" { type = string }
variable "schedule_expression" { type = string }
variable "schedule_timezone" { type = string }
variable "schedule_enabled" { type = bool }

# Bus custom SOLO para el disparo del cierre de mes (NO es el Event Mesh del proyecto).
resource "aws_cloudwatch_event_bus" "this" {
  name = var.bus_name
}

# El runner de experimentos dispara con PutEvents (source=voltera.runner, detail-type=CierreDeMes).
resource "aws_cloudwatch_event_rule" "cierre_mes" {
  name           = "${var.name_prefix}-cierre-mes"
  event_bus_name = aws_cloudwatch_event_bus.this.name
  event_pattern = jsonencode({
    source        = ["voltera.runner", "voltera.scheduler"]
    "detail-type" = ["CierreDeMes"]
  })
}

resource "aws_cloudwatch_event_target" "orchestrator" {
  rule           = aws_cloudwatch_event_rule.cierre_mes.name
  event_bus_name = aws_cloudwatch_event_bus.this.name
  target_id      = "ms-orchestrator-billing"
  arn            = var.target_lambda_arn
}

resource "aws_lambda_permission" "from_rule" {
  statement_id  = "AllowEventBridgeRule"
  action        = "lambda:InvokeFunction"
  function_name = var.target_lambda_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cierre_mes.arn
}

# Cierre de mes programado (EventBridge Scheduler). DESHABILITADO por defecto.
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [var.target_lambda_arn]
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invocar-orchestrator"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}

resource "aws_scheduler_schedule" "cierre_mes" {
  name                         = "${var.name_prefix}-cierre-mes"
  state                        = var.schedule_enabled ? "ENABLED" : "DISABLED"
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = var.target_lambda_arn
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      source        = "voltera.scheduler"
      "detail-type" = "CierreDeMes"
      detail        = {}
    })
  }
}

output "bus_name" { value = aws_cloudwatch_event_bus.this.name }
output "bus_arn" { value = aws_cloudwatch_event_bus.this.arn }
output "rule_arn" { value = aws_cloudwatch_event_rule.cierre_mes.arn }
output "schedule_name" { value = aws_scheduler_schedule.cierre_mes.name }
