# Manifiestos en codigo_fuente_voltera/k8s/*.tftpl. Se aplican con kubectl_manifest (valida sin CRDs en el plan).
# Orden: operador Strimzi -> Kafka x2 -> tópicos -> MirrorMaker2; KEDA + Apicurio -> ms-process-billing.

locals {
  k8s_dir = "${path.module}/../../../../k8s"
  lb_tags = join(",", [for k, v in local.tags : "${k}=${v}"])

  kafka_common = {
    namespace      = var.kafka_namespace
    kafka_version  = var.kafka_version
    storage_size   = var.kafka_storage_size
    storage_class  = var.kafka_storage_class
    heap           = var.kafka_heap
    memory_request = var.kafka_memory_request
    memory_limit   = var.kafka_memory_limit
  }
}

############################ Kafka (Strimzi) ############################
data "kubectl_file_documents" "kafka_billing" {
  content = templatefile("${local.k8s_dir}/kafka/billing.yaml.tftpl", merge(local.kafka_common, {
    vpc_cidr = local.cluster.vpc_cidr
    lb_tags  = local.lb_tags
  }))
}

resource "kubectl_manifest" "kafka_billing" {
  for_each  = data.kubectl_file_documents.kafka_billing.manifests
  yaml_body = each.value

  wait_for_rollout = false
  depends_on       = [helm_release.strimzi, kubectl_manifest.storageclass, terraform_data.inputs_check]
}

data "kubectl_file_documents" "kafka_dominios" {
  content = templatefile("${local.k8s_dir}/kafka/dominios.yaml.tftpl", local.kafka_common)
}

resource "kubectl_manifest" "kafka_dominios" {
  for_each  = data.kubectl_file_documents.kafka_dominios.manifests
  yaml_body = each.value

  wait_for_rollout = false
  depends_on       = [helm_release.strimzi, kubectl_manifest.storageclass]
}

data "kubectl_file_documents" "topics" {
  content = templatefile("${local.k8s_dir}/kafka/topics.yaml.tftpl", {
    namespace          = var.kafka_namespace
    ingreso_partitions = var.ingreso_partitions
    eventos_partitions = var.eventos_partitions
    retention_ms       = var.topic_retention_ms
  })
}

resource "kubectl_manifest" "topics" {
  for_each  = data.kubectl_file_documents.topics.manifests
  yaml_body = each.value

  depends_on = [kubectl_manifest.kafka_billing]
}

data "kubectl_file_documents" "mirrormaker2" {
  content = templatefile("${local.k8s_dir}/kafka/mirrormaker2.yaml.tftpl", {
    namespace             = var.kafka_namespace
    kafka_version         = var.kafka_version
    mirror_topics_pattern = replace(var.eventos_topic, ".", "[.]")
  })
}

resource "kubectl_manifest" "mirrormaker2" {
  for_each  = var.mirror_enabled ? data.kubectl_file_documents.mirrormaker2.manifests : {}
  yaml_body = each.value

  depends_on = [kubectl_manifest.kafka_billing, kubectl_manifest.kafka_dominios, kubectl_manifest.topics]
}

############################ Schema Registry (Apicurio) ############################
data "kubectl_file_documents" "apicurio" {
  content = templatefile("${local.k8s_dir}/apicurio/apicurio.yaml.tftpl", {
    namespace = var.kafka_namespace
    image     = var.apicurio_image
  })
}

resource "kubectl_manifest" "apicurio" {
  for_each  = data.kubectl_file_documents.apicurio.manifests
  yaml_body = each.value

  depends_on = [kubectl_manifest.namespaces]
}

############################ ms-process-billing + ScaledObject ############################
data "kubectl_file_documents" "process_billing" {
  content = templatefile("${local.k8s_dir}/apps/ms-process-billing.yaml.tftpl", {
    namespace               = local.cluster.app_namespace
    service_account         = "ms-process-billing"
    region                  = local.cluster.region
    image                   = "${local.ecr_repository_url}:${var.process_billing_image_tag}"
    kafka_bootstrap         = local.kafka_bootstrap_billing
    topic_ingreso           = local.ingreso_topic
    topic_eventos           = var.eventos_topic
    consumer_group          = var.process_billing_consumer_group
    schema_registry_url     = "http://apicurio-registry.${var.kafka_namespace}.svc:8080/apis/registry/v3"
    sqs_queue_url           = local.transactions_queue_url
    table_process_billing   = local.process_billing_table
    simulated_delay_seconds = local.simulated_delay_seconds
    health_path             = var.process_billing_health_path
    min_replicas            = local.min_replicas
    max_replicas            = local.max_replicas
    lag_threshold           = local.keda_lag_threshold
    polling_interval        = var.keda_polling_interval
    cooldown_period         = var.keda_cooldown_period
    metrics_backend         = var.metrics_backend
    cloudwatch_namespace    = var.cloudwatch_namespace
    metrics_flush_seconds   = var.metrics_flush_seconds
    table_reconciliacion    = coalesce(local.idem_comprobante_table, "")
    reconcile_after_seconds = var.reconcile_after_seconds
    consumer_concurrency    = var.consumer_concurrency
  })
}

resource "kubectl_manifest" "process_billing" {
  for_each  = data.kubectl_file_documents.process_billing.manifests
  yaml_body = each.value

  # No esperar el rollout: si la imagen aún no está en ECR el pod queda en ImagePullBackOff y no debe bloquear el apply.
  wait_for_rollout = false
  depends_on       = [helm_release.keda, kubectl_manifest.topics, kubectl_manifest.apicurio, terraform_data.inputs_check]
}

############################ Lag de Kafka -> CloudWatch (OBS-7) ############################
data "kubectl_file_documents" "prometheus_cwagent" {
  content = templatefile("${local.k8s_dir}/observability/prometheus-cwagent.yaml.tftpl", {
    namespace       = "amazon-cloudwatch"
    kafka_namespace = var.kafka_namespace
    cluster_name    = local.cluster.cluster_name
    image           = var.cwagent_image
  })
}

resource "kubectl_manifest" "prometheus_cwagent" {
  for_each  = var.enable_prometheus_lag_agent && try(local.cluster.container_insights_enabled, false) ? data.kubectl_file_documents.prometheus_cwagent.manifests : {}
  yaml_body = each.value

  depends_on = [kubectl_manifest.kafka_billing]
}

############################ Consumidor de reportes (Exp. 4, opcional) ############################
data "kubectl_file_documents" "reportes_consumer" {
  content = templatefile("${local.k8s_dir}/consumers/reportes-consumer.yaml.tftpl", {
    namespace = var.kafka_namespace
    image     = var.reportes_consumer_image
    bootstrap = "dominios-kafka-bootstrap.${var.kafka_namespace}.svc:9092"
    topic     = "billing.${var.eventos_topic}"
    group     = var.reportes_consumer_group
  })
}

resource "kubectl_manifest" "reportes_consumer" {
  for_each  = var.reportes_consumer_enabled ? data.kubectl_file_documents.reportes_consumer.manifests : {}
  yaml_body = each.value

  depends_on = [kubectl_manifest.kafka_dominios]
}
