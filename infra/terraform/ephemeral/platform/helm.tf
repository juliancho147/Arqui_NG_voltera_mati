############################ Namespaces y StorageClass ############################
data "kubectl_file_documents" "namespaces" {
  content = file("${path.module}/../../../../k8s/00-namespaces.yaml")
}

resource "kubectl_manifest" "namespaces" {
  for_each  = data.kubectl_file_documents.namespaces.manifests
  yaml_body = each.value
}

data "kubectl_file_documents" "storageclass" {
  content = file("${path.module}/../../../../k8s/01-storageclass.yaml")
}

resource "kubectl_manifest" "storageclass" {
  for_each  = data.kubectl_file_documents.storageclass.manifests
  yaml_body = each.value
}

############################ Operadores (Helm) ############################
# Strimzi: gestiona Kafka/KafkaNodePool/KafkaTopic/KafkaMirrorMaker2 (control plane del mesh). Vigila su propio namespace.
resource "helm_release" "strimzi" {
  name       = "strimzi"
  namespace  = var.kafka_namespace
  repository = "oci://quay.io/strimzi-helm"
  chart      = "strimzi-kafka-operator"
  version    = var.strimzi_chart_version
  timeout    = var.helm_timeout_seconds
  wait       = true

  set {
    name  = "resources.requests.cpu"
    value = "100m"
  }
  set {
    name  = "resources.requests.memory"
    value = "256Mi"
  }
  set {
    name  = "resources.limits.memory"
    value = "512Mi"
  }

  depends_on = [kubectl_manifest.namespaces]
}

# KEDA: autoscaling por lag de Kafka.
resource "helm_release" "keda" {
  name             = "keda"
  namespace        = var.keda_namespace
  create_namespace = true
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = var.keda_chart_version
  timeout          = var.helm_timeout_seconds
  wait             = true

  set {
    name  = "resources.operator.requests.cpu"
    value = "50m"
  }
  set {
    name  = "resources.operator.requests.memory"
    value = "128Mi"
  }
  set {
    name  = "resources.operator.limits.memory"
    value = "256Mi"
  }
  set {
    name  = "resources.metricServer.requests.cpu"
    value = "50m"
  }
  set {
    name  = "resources.metricServer.requests.memory"
    value = "128Mi"
  }
  set {
    name  = "resources.metricServer.limits.memory"
    value = "256Mi"
  }
  set {
    name  = "resources.webhooks.requests.cpu"
    value = "20m"
  }
  set {
    name  = "resources.webhooks.requests.memory"
    value = "64Mi"
  }
  set {
    name  = "resources.webhooks.limits.memory"
    value = "128Mi"
  }
}
