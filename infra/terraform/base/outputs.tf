output "region" {
  value = var.aws_region
}

output "dynamodb_tables" {
  description = "Nombres y ARNs de las tablas."
  value = {
    names      = module.dynamodb.table_names
    arns       = module.dynamodb.table_arns
    stream_arn = module.dynamodb.stream_arns
  }
}

output "outbox_stream_arn" {
  value = module.dynamodb.stream_arns["outbox"]
}

output "sqs" {
  description = "Colas y DLQs (URL/ARN) para ms-process-billing, runner y redrive."
  value = {
    transacciones = {
      url     = module.sqs_transactions.queue_url
      arn     = module.sqs_transactions.queue_arn
      dlq_url = module.sqs_transactions.dlq_url
      dlq_arn = module.sqs_transactions.dlq_arn
    }
    comprobantes = {
      url     = module.sqs_comprobantes.queue_url
      arn     = module.sqs_comprobantes.queue_arn
      dlq_url = module.sqs_comprobantes.dlq_url
      dlq_arn = module.sqs_comprobantes.dlq_arn
    }
  }
}

output "eventbridge" {
  value = {
    bus_name      = module.eventbridge.bus_name
    bus_arn       = module.eventbridge.bus_arn
    rule_arn      = module.eventbridge.rule_arn
    schedule_name = module.eventbridge.schedule_name
    # Para el runner: PutEvents con Source=voltera.runner, DetailType=CierreDeMes
    putevents_hint = "Source=voltera.runner DetailType=CierreDeMes EventBusName=${module.eventbridge.bus_name}"
  }
}

output "lambdas" {
  description = "Nombre, ARN y log group por Lambda."
  value = {
    ms-orchestrator-billing = { name = module.lambda_orchestrator.function_name, arn = module.lambda_orchestrator.function_arn, log_group = module.lambda_orchestrator.log_group_name }
    outbox-relay            = { name = module.lambda_outbox_relay.function_name, arn = module.lambda_outbox_relay.function_arn, log_group = module.lambda_outbox_relay.log_group_name }
    ms-tarifas              = { name = module.lambda_tarifas.function_name, arn = module.lambda_tarifas.function_arn, log_group = module.lambda_tarifas.log_group_name }
    ms-calculo-consumo-neto = { name = module.lambda_calculo.function_name, arn = module.lambda_calculo.function_arn, log_group = module.lambda_calculo.log_group_name }
    ms-facturacion          = { name = module.lambda_facturacion.function_name, arn = module.lambda_facturacion.function_arn, log_group = module.lambda_facturacion.log_group_name }
    ms-comprobante-factura  = { name = module.lambda_comprobante.function_name, arn = module.lambda_comprobante.function_arn, log_group = module.lambda_comprobante.log_group_name }
  }
}

output "outbox_relay_role_arn" {
  description = "Rol del relay: el stack efímero debe agregarle permisos kafka-cluster:* sobre MSK."
  value       = module.lambda_outbox_relay.role_arn
}

output "step_functions" {
  value = {
    arn       = module.stepfunctions.state_machine_arn
    name      = module.stepfunctions.state_machine_name
    type      = var.sfn_type
    log_group = module.stepfunctions.log_group_name
  }
}

output "ecr_process_billing" {
  value = {
    repository_url = module.ecr_process_billing.repository_url
    repository_arn = module.ecr_process_billing.repository_arn
  }
}

output "dlq_alarm_arns" {
  value = module.observability.alarm_arns
}

output "experiment_parameters" {
  description = "Parámetros del plan, para que el stack efímero y el runner los lean."
  value = {
    n_solicitudes           = var.n_solicitudes
    simulated_delay_seconds = var.simulated_delay_seconds
    keda_lag_threshold      = var.keda_lag_threshold
    process_billing_min     = var.process_billing_min_replicas
    process_billing_max     = var.process_billing_max_replicas
    batch_sla_seconds       = var.batch_sla_seconds
    max_receive_count       = var.max_receive_count
    sfn_retry = {
      max_attempts     = var.sfn_retry_max_attempts
      interval_seconds = var.sfn_retry_interval_seconds
      backoff_rate     = var.sfn_retry_backoff_rate
    }
    kafka_topic = var.kafka_topic
  }
}
