############################ Entradas de otros stacks ############################
variable "cluster_state_path" {
  description = "Ruta local al terraform.tfstate del stack ephemeral/cluster."
  type        = string
  default     = "../cluster/terraform.tfstate"
}

variable "base_state_path" {
  description = "Ruta local al terraform.tfstate del stack base. null = usar solo base_overrides."
  type        = string
  default     = "../../base/terraform.tfstate"
}

variable "base_overrides" {
  description = "Valores del stack base si no se lee su estado (o para sobreescribirlos)."
  type = object({
    ecr_repository_url      = optional(string)
    transactions_queue_url  = optional(string)
    process_billing_table   = optional(string)
    keda_lag_threshold      = optional(number)
    process_billing_min     = optional(number)
    process_billing_max     = optional(number)
    simulated_delay_seconds = optional(number)
    ingreso_topic           = optional(string)
  })
  default = {}
}

############################ Namespaces ############################
variable "kafka_namespace" {
  type    = string
  default = "kafka"
}

variable "keda_namespace" {
  type    = string
  default = "keda"
}

############################ Charts / versiones (fijadas) ############################
variable "strimzi_chart_version" {
  description = "Versión del chart strimzi-kafka-operator (OCI quay.io/strimzi-helm)."
  type        = string
  default     = "1.2.0"
}

variable "keda_chart_version" {
  type    = string
  default = "2.21.0"
}

variable "kafka_version" {
  description = "Versión de Apache Kafka (debe estar soportada por la versión de Strimzi; 1.2.0 soporta 4.2.x y 4.3.x)."
  type        = string
  default     = "4.3.1"
}

variable "apicurio_image" {
  type    = string
  default = "quay.io/apicurio/apicurio-registry:3.3.3"
}

############################ Kafka ############################
variable "kafka_storage_size" {
  description = "Tamaño del PVC (EBS gp3) por broker."
  type        = string
  default     = "5Gi"
}

variable "kafka_storage_class" {
  type    = string
  default = "gp3-delete"
}

variable "kafka_heap" {
  description = "Heap JVM de cada broker."
  type        = string
  default     = "512m"
}

variable "kafka_memory_request" {
  type    = string
  default = "1Gi"
}

variable "kafka_memory_limit" {
  type    = string
  default = "1536Mi"
}

variable "topic_retention_ms" {
  type    = number
  default = 86400000 # 1 día
}

variable "ingreso_partitions" {
  description = "Particiones del tópico de ingreso. Debe ser >= réplicas máximas de KEDA."
  type        = number
  default     = 5
}

variable "eventos_partitions" {
  type    = number
  default = 3
}

variable "eventos_topic" {
  type    = string
  default = "voltera.eventos"
}

variable "mirror_enabled" {
  description = "Despliega KafkaMirrorMaker2 billing -> dominios."
  type        = bool
  default     = true
}

############################ ms-process-billing ############################
variable "process_billing_image_tag" {
  description = "Tag de la imagen en ECR (la URL del repositorio sale de los outputs de base)."
  type        = string
  default     = "latest"
}

variable "process_billing_consumer_group" {
  type    = string
  default = "ms-process-billing"
}

variable "process_billing_health_path" {
  description = "Ruta HTTP de salud (liveness/readiness) del contenedor, puerto 8080."
  type        = string
  default     = "/healthz"
}

variable "keda_polling_interval" {
  type    = number
  default = 5
}

variable "keda_cooldown_period" {
  type    = number
  default = 60
}

variable "helm_timeout_seconds" {
  type    = number
  default = 600
}

variable "cwagent_image" {
  description = "Imagen del agente CloudWatch que scrapea Prometheus (kafka-exporter). Fija un tag si lo prefieres."
  type        = string
  default     = "public.ecr.aws/cloudwatch-agent/cloudwatch-agent:latest"
}

variable "reportes_consumer_enabled" {
  description = "Despliega el consumidor de reportes en el clúster dominios (Exp. 4, prueba de extensibilidad). Se puede activar después sin tocar nada de lo existente."
  type        = bool
  default     = false
}

variable "reportes_consumer_image" {
  description = "Imagen con kafka-console-consumer.sh (mismo patrón que las imágenes de Strimzi: <versión operador>-kafka-<versión kafka>)."
  type        = string
  default     = "quay.io/strimzi/kafka:1.2.0-kafka-4.3.1"
}

variable "reportes_consumer_group" {
  type    = string
  default = "reportes"
}

variable "enable_prometheus_lag_agent" {
  description = "Despliega cwagent-prometheus (lag vía kafka-exporter). APAGADO: su config no funciona; el lag lo publica la app (KafkaConsumerLag)."
  type        = bool
  default     = false
}

variable "metrics_backend" {
  type    = string
  default = "cloudwatch"
}

variable "cloudwatch_namespace" {
  type    = string
  default = "Voltera/Exp2"
}

variable "metrics_flush_seconds" {
  type    = number
  default = 10
}
