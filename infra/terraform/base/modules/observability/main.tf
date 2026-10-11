variable "name_prefix" { type = string }
variable "alarm_actions" { type = list(string) }
variable "dlq_names" {
  description = "Mapa etiqueta -> nombre de DLQ."
  type        = map(string)
}

# Alarma básica: DLQ no vacía (evidencia directa de Exp. 2 / Exp. 3).
resource "aws_cloudwatch_metric_alarm" "dlq_no_vacia" {
  for_each = var.dlq_names

  alarm_name          = "${var.name_prefix}-dlq-${each.key}-no-vacia"
  alarm_description   = "La DLQ ${each.value} tiene mensajes."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
}

output "alarm_arns" {
  value = { for k, a in aws_cloudwatch_metric_alarm.dlq_no_vacia : k => a.arn }
}
