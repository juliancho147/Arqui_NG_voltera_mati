output "kafka_bootstrap_billing_internal" {
  value = local.kafka_bootstrap_billing
}

output "kafka_bootstrap_dominios_internal" {
  value = "dominios-kafka-bootstrap.${var.kafka_namespace}.svc:9092"
}

output "schema_registry_url_internal" {
  value = "http://apicurio-registry.${var.kafka_namespace}.svc:8080/apis/registry/v3"
}

output "relay_bootstrap_hint" {
  description = "El hostname del NLB interno aparece unos minutos después; léelo con scripts/kafka-relay-bootstrap.sh (make relay-bootstrap)."
  value       = "../../../scripts/kafka-relay-bootstrap.sh"
}

output "process_billing_image" {
  value = "${local.ecr_repository_url}:${var.process_billing_image_tag}"
}

output "keda" {
  value = {
    min           = local.min_replicas
    max           = local.max_replicas
    lag_threshold = local.keda_lag_threshold
  }
}
