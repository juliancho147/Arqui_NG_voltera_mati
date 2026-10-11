data "terraform_remote_state" "cluster" {
  backend = "local"
  config = {
    path = var.cluster_state_path
  }
}

data "terraform_remote_state" "base" {
  count   = var.base_state_path == null ? 0 : 1
  backend = "local"
  config = {
    path = var.base_state_path
  }
}

locals {
  base = try(data.terraform_remote_state.base[0].outputs, {})
  bo   = var.base_overrides

  ecr_repository_url     = try(coalesce(local.bo.ecr_repository_url, try(local.base.ecr_process_billing.repository_url, null)), null)
  transactions_queue_url = try(coalesce(local.bo.transactions_queue_url, try(local.base.sqs.transacciones.url, null)), null)
  idem_comprobante_table = try(coalesce(local.bo.idem_comprobante_table, try(local.base.dynamodb_tables.names["idem-comprobante"], null)), null)
  process_billing_table  = try(coalesce(local.bo.process_billing_table, try(local.base.dynamodb_tables.names["process-billing"], null)), null)

  # Parámetros del experimento (salen del stack base para que haya una sola fuente de verdad).
  params = try(local.base.experiment_parameters, {})

  keda_lag_threshold      = try(coalesce(local.bo.keda_lag_threshold, try(local.params.keda_lag_threshold, null)), 2)
  min_replicas            = try(coalesce(local.bo.process_billing_min, try(local.params.process_billing_min, null)), 1)
  max_replicas            = try(coalesce(local.bo.process_billing_max, try(local.params.process_billing_max, null)), 5)
  simulated_delay_seconds = try(coalesce(local.bo.simulated_delay_seconds, try(local.params.simulated_delay_seconds, null)), 5)
  ingreso_topic           = try(coalesce(local.bo.ingreso_topic, try(local.params.kafka_topic, null)), "voltera.consumo-facturable-preparado")

  tags = local.cluster.tags

  kafka_bootstrap_billing = "billing-kafka-bootstrap.${var.kafka_namespace}.svc:9092"
}

resource "terraform_data" "inputs_check" {
  lifecycle {
    precondition {
      condition     = local.ecr_repository_url != null && local.transactions_queue_url != null && local.process_billing_table != null
      error_message = "Faltan outputs del stack base (ECR/SQS/DynamoDB). Aplica base primero (revisa base_state_path) o completa base_overrides."
    }
    precondition {
      condition     = var.ingreso_partitions >= local.max_replicas
      error_message = "ingreso_partitions debe ser >= réplicas máximas de KEDA (${local.max_replicas})."
    }
  }
}
