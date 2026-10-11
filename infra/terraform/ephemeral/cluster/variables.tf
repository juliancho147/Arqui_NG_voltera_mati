############################ General ############################
variable "aws_region" {
  description = "Región AWS."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefijo de nombre de los recursos (se usa también como nombre del clúster EKS)."
  type        = string
  default     = "voltera-exp2-eph"
}

variable "tags" {
  description = "Tags adicionales (se mezclan con proyecto/experimento/stack)."
  type        = map(string)
  default     = {}
}

############################ Stack base (entradas) ############################
variable "base_state_path" {
  description = "Ruta local al terraform.tfstate del stack base (terraform_remote_state). null = no leer el estado y usar solo base_overrides."
  type        = string
  default     = "../../base/terraform.tfstate"
}

variable "base_overrides" {
  description = "Valores del stack base si no se lee su estado (o para sobreescribirlos)."
  type = object({
    process_billing_table_arn = optional(string)
    transactions_queue_arn    = optional(string)
  })
  default = {}
}

############################ Red ############################
variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "az_count" {
  description = "Cantidad de zonas de disponibilidad (EKS exige >= 2)."
  type        = number
  default     = 2
  validation {
    condition     = var.az_count >= 2
    error_message = "EKS requiere al menos 2 AZ."
  }
}

############################ EKS ############################
variable "kubernetes_version" {
  description = "Versión de EKS. OJO: una versión fuera de soporte estándar cobra soporte extendido (~0,60 USD/h en vez de 0,10). 1.36 está en soporte estándar hasta 2027-08."
  type        = string
  default     = "1.36"
}

variable "public_access_cidrs" {
  description = "CIDRs con acceso al endpoint público del API de Kubernetes. Restringe a tu IP/32 si puedes."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "admin_principal_arns" {
  description = "ARNs IAM adicionales con rol cluster-admin (el creador ya lo es)."
  type        = list(string)
  default     = []
}

variable "enabled_cluster_log_types" {
  description = "Logs del control plane hacia CloudWatch (cuestan; vacío por defecto)."
  type        = list(string)
  default     = []
}

variable "node_instance_types" {
  type    = list(string)
  default = ["t3.large"]
}

variable "node_capacity_type" {
  description = "ON_DEMAND o SPOT. Kafka con 1 broker no tolera bien interrupciones: ON_DEMAND por defecto."
  type        = string
  default     = "ON_DEMAND"
}

variable "node_desired_size" {
  type    = number
  default = 2
}

variable "node_min_size" {
  type    = number
  default = 2
}

variable "node_max_size" {
  type    = number
  default = 2
}

variable "node_disk_size_gb" {
  type    = number
  default = 30
}

############################ Add-ons / observabilidad ############################
variable "enable_container_insights" {
  description = "Instala el add-on amazon-cloudwatch-observability (Container Insights; lo usará Grafana)."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "Retención de los log groups de Container Insights (corta por costo)."
  type        = number
  default     = 3
}

variable "app_namespace" {
  description = "Namespace de las aplicaciones (debe coincidir con el stack platform)."
  type        = string
  default     = "voltera"
}

variable "process_billing_service_account" {
  type    = string
  default = "ms-process-billing"
}

variable "lambda_interface_endpoints" {
  description = "Endpoints de interfaz para Lambdas en la VPC (sufijo del servicio: xray, sqs...). Una sola AZ. [] = ninguno."
  type        = list(string)
  default     = ["xray", "sqs"]
}

variable "metrics_namespace" {
  description = "Namespace de CloudWatch en el que ms-process-billing puede publicar (cloudwatch:PutMetricData)."
  type        = string
  default     = "Voltera/Exp2"
}
