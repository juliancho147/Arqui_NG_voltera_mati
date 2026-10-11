############################ General ############################
variable "aws_region" {
  description = "Región AWS (el perfil default no tiene región configurada)."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefijo de nombre de todos los recursos."
  type        = string
  default     = "voltera-exp2"
}

variable "tags" {
  description = "Tags adicionales (se mezclan con los comunes proyecto/experimento/stack)."
  type        = map(string)
  default     = {}
}

variable "services_dir" {
  description = "Carpeta con el código de las Lambdas (services/<nombre>/handler.py). null = ../../../services relativo a este stack."
  type        = string
  default     = null
}

############################ Parámetros del experimento ############################
variable "n_solicitudes" {
  description = "N_SOLICITUDES: cantidad de solicitudes de liquidación por corrida (el orchestrator la recibe como env)."
  type        = number
  default     = 10
}

variable "simulated_delay_seconds" {
  description = "Retardo simulado por mensaje en ms-process-billing (Exp. 1). Solo se publica en outputs para el stack efímero."
  type        = number
  default     = 5
}

variable "keda_lag_threshold" {
  description = "KEDA lagThreshold (solo se expone en outputs para el stack efímero)."
  type        = number
  default     = 2
}

variable "process_billing_min_replicas" {
  type    = number
  default = 1
}

variable "process_billing_max_replicas" {
  type    = number
  default = 5
}

variable "batch_sla_seconds" {
  description = "SLA del lote (Exp. 1): 10 facturas en <= 120 s. Solo informativo/outputs."
  type        = number
  default     = 120
}

############################ SQS ############################
variable "max_receive_count" {
  description = "SQS maxReceiveCount antes de mover el mensaje a la DLQ."
  type        = number
  default     = 3
}

variable "sqs_message_retention_seconds" {
  type    = number
  default = 345600 # 4 días
}

variable "sqs_dlq_retention_seconds" {
  type    = number
  default = 1209600 # 14 días
}

variable "transactions_queue_visibility_timeout" {
  description = "Visibility timeout de la cola de transacciones. null = 6 x lambda_timeout_seconds (recomendación AWS)."
  type        = number
  default     = null
}

variable "comprobantes_queue_visibility_timeout" {
  description = "Visibility timeout de la cola de comprobantes. null = 6 x lambda_timeout_seconds (debe ser >= timeout de la Lambda consumidora)."
  type        = number
  default     = null
}

variable "comprobantes_batch_size" {
  type    = number
  default = 1
}

############################ Lambdas ############################
variable "lambda_timeout_seconds" {
  type    = number
  default = 30
}

variable "lambda_memory_mb" {
  type    = number
  default = 256
}

variable "lambda_log_retention_days" {
  description = "Retención corta de logs (costo)."
  type        = number
  default     = 3
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "powertools_layer_arn" {
  description = "ARN del layer de AWS Lambda Powertools (Python 3.12). Vacío = sin layer. Ver README para el formato del ARN público."
  type        = string
  default     = ""
}

variable "fault_injection" {
  description = <<-EOT
    Inyección de fallos por servicio (Exp. 2). Clave = nombre del servicio
    (ms-tarifas, ms-calculo-consumo-neto, ms-facturacion, ms-comprobante-factura, ms-orchestrator-billing, outbox-relay).
    fail_rate: probabilidad 0..1 de fallo; force_fail: fallo siempre.
  EOT
  type = map(object({
    fail_rate  = optional(number, 0)
    force_fail = optional(bool, false)
  }))
  default = {}
}

variable "reserved_concurrency" {
  description = <<-EOT
    Concurrencia reservada por servicio (Bulkhead / Exp. 2). Clave = nombre del servicio; ausente = sin reserva (-1); 0 = bloqueada (simula caída).
    OJO: cuentas nuevas suelen tener límite 10 de concurrencia total y AWS exige dejar >=10 sin reservar; la reserva puede fallar hasta subir la cuota.
  EOT
  type        = map(number)
  default     = {}
}

variable "kafka_bootstrap_servers" {
  description = "Bootstrap servers de Kafka (salida de `make relay-bootstrap`: <hostname NLB>:9094). Vacío mientras no exista."
  type        = string
  default     = ""
}

variable "relay_vpc_config" {
  description = "VPC del outbox-relay (output relay_vpc_config de ephemeral/cluster). null = sin VPC. Volver a null ANTES de destruir el efímero."
  type = object({
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
  default = null
}

variable "relay_extra_layer_arns" {
  description = "Layers adicionales del relay (p. ej. con confluent-kafka). Alternativa: empaquetarlo en el zip."
  type        = list(string)
  default     = []
}

variable "kafka_topic_eventos" {
  description = "Tópico del Event Mesh donde cada paso publica su evento de dominio."
  type        = string
  default     = "voltera.eventos"
}

variable "lambda_subnet_ids" {
  description = "Subnets VPC para relay, tarifas, calculo, facturacion y comprobante (stack efímero). [] = sin VPC."
  type        = list(string)
  default     = []
}

variable "lambda_security_group_ids" {
  type    = list(string)
  default = []
}

variable "kafka_topic" {
  type    = string
  default = "voltera.consumo-facturable-preparado"
}

variable "outbox_batch_size" {
  type    = number
  default = 10
}

variable "outbox_max_retry_attempts" {
  description = "Reintentos del mapping Streams -> relay. -1 = infinito (sin descartar eventos del outbox: cero pérdida, Exp. 3)."
  type        = number
  default     = -1
}

############################ DynamoDB ############################
variable "idempotency_ttl_attribute" {
  type    = string
  default = "expiresAt"
}

############################ Step Functions ############################
variable "sfn_type" {
  description = "STANDARD (default, trazabilidad visual) o EXPRESS (más barato a escala real)."
  type        = string
  default     = "STANDARD"
  validation {
    condition     = contains(["STANDARD", "EXPRESS"], var.sfn_type)
    error_message = "sfn_type debe ser STANDARD o EXPRESS."
  }
}

variable "sfn_retry_max_attempts" {
  type    = number
  default = 3
}

variable "sfn_retry_interval_seconds" {
  type    = number
  default = 2
}

variable "sfn_retry_backoff_rate" {
  type    = number
  default = 2.0
}

variable "sfn_log_level" {
  type    = string
  default = "ALL"
}

############################ EventBridge ############################
variable "cierre_mes_schedule_expression" {
  description = "Expresión del Scheduler: último día de cada mes 23:00."
  type        = string
  default     = "cron(0 23 L * ? *)"
}

variable "cierre_mes_schedule_timezone" {
  type    = string
  default = "America/Bogota"
}

variable "cierre_mes_schedule_enabled" {
  description = "Deshabilitado por defecto: el runner dispara el cierre con PutEvents al bus."
  type        = bool
  default     = false
}

############################ Observabilidad / ECR ############################
variable "alarm_actions" {
  description = "ARNs de acciones (p. ej. SNS) para las alarmas de DLQ."
  type        = list(string)
  default     = []
}

variable "ecr_keep_images" {
  type    = number
  default = 5
}

variable "orchestrator_timeout_seconds" {
  description = "Timeout de ms-orchestrator-billing: escribe N filas en el outbox (con N grande, 30 s no alcanzan)."
  type        = number
  default     = 300
}

variable "comprobante_timeout_seconds" {
  description = "Timeout de ms-comprobante-factura (simula al tercero, ~1 s). Debe ser <= visibility timeout de su cola."
  type        = number
  default     = 30
}
