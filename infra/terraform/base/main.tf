locals {
  tags = merge({
    proyecto    = "voltera"
    experimento = "exp2-eda"
    stack       = "base"
  }, var.tags)

  prefix       = var.name_prefix
  services_dir = coalesce(var.services_dir, "${path.root}/../../../services")

  # Nombre del bus calculado aquí para evitar dependencias circulares con el orchestrator.
  bus_name = "${local.prefix}-bus"

  tx_visibility           = coalesce(var.transactions_queue_visibility_timeout, 6 * var.lambda_timeout_seconds)
  comprobantes_visibility = coalesce(var.comprobantes_queue_visibility_timeout, 6 * var.lambda_timeout_seconds)

  common_env = {
    LOG_LEVEL                    = var.log_level
    POWERTOOLS_LOG_LEVEL         = var.log_level
    POWERTOOLS_METRICS_NAMESPACE = "Voltera/Exp2"
    EXPERIMENTO                  = "exp2-eda"
  }

  # FAIL_RATE / FORCE_FAIL por servicio (Exp. 2).
  fault_env = {
    for s in ["ms-orchestrator-billing", "outbox-relay", "ms-tarifas", "ms-calculo-consumo-neto", "ms-facturacion", "ms-comprobante-factura"] : s => {
      FAIL_RATE  = tostring(try(var.fault_injection[s].fail_rate, 0))
      FORCE_FAIL = tostring(try(var.fault_injection[s].force_fail, false))
    }
  }

  reserved = { for s, _ in local.fault_env : s => lookup(var.reserved_concurrency, s, -1) }
}

############################ DynamoDB ############################
# Claves:
#  transacciones   PK cicloId, SK facturaId      -> transacciones preprocesadas (insumo del orchestrator)
#  outbox          PK eventId                    -> Transactional Outbox; Streams NEW_IMAGE; TTL limpia publicados
#  process_billing PK cicloId, SK sk             -> sk = "META" (estado/contador del ciclo) | "DEDUP#<facturaId>" (dedup de ingreso)
#  idem_facturacion      PK facturaId            -> idempotencia de ms-facturacion (PutItem condicional + TTL)
#  idem_comprobante      PK facturaId            -> idempotencia de ms-comprobante-factura (+ TTL)
module "dynamodb" {
  source = "./modules/dynamodb"

  name_prefix = local.prefix
  tables = {
    transacciones = {
      hash_key  = "cicloId"
      range_key = "facturaId"
    }
    outbox = {
      hash_key         = "eventId"
      ttl_attribute    = var.idempotency_ttl_attribute
      stream_view_type = "NEW_IMAGE"
    }
    process-billing = {
      hash_key      = "cicloId"
      range_key     = "sk"
      ttl_attribute = var.idempotency_ttl_attribute
    }
    idem-facturacion = {
      hash_key      = "facturaId"
      ttl_attribute = var.idempotency_ttl_attribute
    }
    idem-comprobante = {
      hash_key      = "facturaId"
      ttl_attribute = var.idempotency_ttl_attribute
    }
  }
}

############################ SQS ############################
module "sqs_transactions" {
  source = "./modules/sqs"

  name                       = "${local.prefix}-transacciones"
  visibility_timeout_seconds = local.tx_visibility
  max_receive_count          = var.max_receive_count
  retention_seconds          = var.sqs_message_retention_seconds
  dlq_retention_seconds      = var.sqs_dlq_retention_seconds
}

module "sqs_comprobantes" {
  source = "./modules/sqs"

  name                       = "${local.prefix}-comprobantes"
  visibility_timeout_seconds = local.comprobantes_visibility
  max_receive_count          = var.max_receive_count
  retention_seconds          = var.sqs_message_retention_seconds
  dlq_retention_seconds      = var.sqs_dlq_retention_seconds
}

############################ Lambdas ############################
locals {
  lambda_common = {
    runtime_timeout = var.lambda_timeout_seconds
    memory_mb       = var.lambda_memory_mb
    retention_days  = var.lambda_log_retention_days
    layers          = var.powertools_layer_arn == "" ? [] : [var.powertools_layer_arn]
  }
}

module "lambda_orchestrator" {
  source = "./modules/lambda"

  function_name        = "${local.prefix}-ms-orchestrator-billing"
  source_dir           = "${local.services_dir}/ms-orchestrator-billing"
  timeout              = local.lambda_common.runtime_timeout
  memory_size          = local.lambda_common.memory_mb
  log_retention_days   = local.lambda_common.retention_days
  layers               = local.lambda_common.layers
  reserved_concurrency = local.reserved["ms-orchestrator-billing"]

  environment = merge(local.common_env, local.fault_env["ms-orchestrator-billing"], {
    POWERTOOLS_SERVICE_NAME = "ms-orchestrator-billing"
    TABLE_TRANSACCIONES     = module.dynamodb.table_names["transacciones"]
    TABLE_OUTBOX            = module.dynamodb.table_names["outbox"]
    TABLE_PROCESS_BILLING   = module.dynamodb.table_names["process-billing"]
    N_SOLICITUDES           = tostring(var.n_solicitudes)
    EVENT_BUS_NAME          = local.bus_name
  })

  policy_statements = [
    {
      sid       = "LeerTransacciones"
      actions   = ["dynamodb:Query", "dynamodb:GetItem", "dynamodb:Scan"]
      resources = [module.dynamodb.table_arns["transacciones"]]
    },
    {
      sid       = "EscribirOutbox"
      actions   = ["dynamodb:PutItem", "dynamodb:BatchWriteItem"]
      resources = [module.dynamodb.table_arns["outbox"]]
    },
  ]
}

# Publica a Kafka más adelante (stack efímero). Los permisos kafka-cluster:* se agregarán
# cuando exista el cluster MSK; por ahora solo lee el stream del outbox.
module "lambda_outbox_relay" {
  source = "./modules/lambda"

  subnet_ids         = var.lambda_subnet_ids
  security_group_ids = var.lambda_security_group_ids

  function_name        = "${local.prefix}-outbox-relay"
  source_dir           = "${local.services_dir}/outbox-relay"
  timeout              = local.lambda_common.runtime_timeout
  memory_size          = local.lambda_common.memory_mb
  log_retention_days   = local.lambda_common.retention_days
  layers               = concat(local.lambda_common.layers, var.relay_extra_layer_arns)
  vpc_config           = var.relay_vpc_config
  reserved_concurrency = local.reserved["outbox-relay"]

  environment = merge(local.common_env, local.fault_env["outbox-relay"], {
    POWERTOOLS_SERVICE_NAME = "outbox-relay"
    KAFKA_BOOTSTRAP_SERVERS = var.kafka_bootstrap_servers
    KAFKA_TOPIC             = var.kafka_topic
    KAFKA_TOPIC_EVENTOS     = var.kafka_topic_eventos
    KAFKA_KEY_FIELD         = "facturaId"
    KAFKA_HEADER_FIELDS     = "cicloId,facturaId"
    TABLE_OUTBOX            = module.dynamodb.table_names["outbox"]
  })

  policy_statements = [
    {
      sid       = "LeerStreamOutbox"
      actions   = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"]
      resources = [module.dynamodb.stream_arns["outbox"]]
    },
    {
      sid       = "MarcarPublicado"
      actions   = ["dynamodb:UpdateItem"]
      resources = [module.dynamodb.table_arns["outbox"]]
    },
  ]
}

module "lambda_tarifas" {
  source = "./modules/lambda"

  subnet_ids         = var.lambda_subnet_ids
  security_group_ids = var.lambda_security_group_ids

  function_name        = "${local.prefix}-ms-tarifas"
  source_dir           = "${local.services_dir}/ms-tarifas"
  timeout              = local.lambda_common.runtime_timeout
  memory_size          = local.lambda_common.memory_mb
  log_retention_days   = local.lambda_common.retention_days
  layers               = local.lambda_common.layers
  reserved_concurrency = local.reserved["ms-tarifas"]

  environment = merge(local.common_env, local.fault_env["ms-tarifas"], {
    POWERTOOLS_SERVICE_NAME = "ms-tarifas"
    KAFKA_BOOTSTRAP_SERVERS = var.kafka_bootstrap_servers
    KAFKA_TOPIC_EVENTOS     = var.kafka_topic_eventos
  })

  policy_statements = []
}

module "lambda_calculo" {
  source = "./modules/lambda"

  subnet_ids         = var.lambda_subnet_ids
  security_group_ids = var.lambda_security_group_ids

  function_name        = "${local.prefix}-ms-calculo-consumo-neto"
  source_dir           = "${local.services_dir}/ms-calculo-consumo-neto"
  timeout              = local.lambda_common.runtime_timeout
  memory_size          = local.lambda_common.memory_mb
  log_retention_days   = local.lambda_common.retention_days
  layers               = local.lambda_common.layers
  reserved_concurrency = local.reserved["ms-calculo-consumo-neto"]

  environment = merge(local.common_env, local.fault_env["ms-calculo-consumo-neto"], {
    POWERTOOLS_SERVICE_NAME = "ms-calculo-consumo-neto"
    KAFKA_BOOTSTRAP_SERVERS = var.kafka_bootstrap_servers
    KAFKA_TOPIC_EVENTOS     = var.kafka_topic_eventos
    TABLE_TRANSACCIONES     = module.dynamodb.table_names["transacciones"]
  })

  policy_statements = [
    {
      sid       = "LeerTransacciones"
      actions   = ["dynamodb:GetItem", "dynamodb:Query"]
      resources = [module.dynamodb.table_arns["transacciones"]]
    },
  ]
}

module "lambda_facturacion" {
  source = "./modules/lambda"

  subnet_ids         = var.lambda_subnet_ids
  security_group_ids = var.lambda_security_group_ids

  function_name        = "${local.prefix}-ms-facturacion"
  source_dir           = "${local.services_dir}/ms-facturacion"
  timeout              = local.lambda_common.runtime_timeout
  memory_size          = local.lambda_common.memory_mb
  log_retention_days   = local.lambda_common.retention_days
  layers               = local.lambda_common.layers
  reserved_concurrency = local.reserved["ms-facturacion"]

  environment = merge(local.common_env, local.fault_env["ms-facturacion"], {
    POWERTOOLS_SERVICE_NAME = "ms-facturacion"
    KAFKA_BOOTSTRAP_SERVERS = var.kafka_bootstrap_servers
    KAFKA_TOPIC_EVENTOS     = var.kafka_topic_eventos
    TABLE_IDEMPOTENCIA      = module.dynamodb.table_names["idem-facturacion"]
    IDEMPOTENCY_TTL_ATTR    = var.idempotency_ttl_attribute
  })

  policy_statements = [
    {
      sid       = "Idempotencia"
      actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
      resources = [module.dynamodb.table_arns["idem-facturacion"]]
    },
  ]
}

module "lambda_comprobante" {
  source = "./modules/lambda"

  subnet_ids         = var.lambda_subnet_ids
  security_group_ids = var.lambda_security_group_ids

  function_name        = "${local.prefix}-ms-comprobante-factura"
  source_dir           = "${local.services_dir}/ms-comprobante-factura"
  timeout              = local.lambda_common.runtime_timeout
  memory_size          = local.lambda_common.memory_mb
  log_retention_days   = local.lambda_common.retention_days
  layers               = local.lambda_common.layers
  reserved_concurrency = local.reserved["ms-comprobante-factura"]

  environment = merge(local.common_env, local.fault_env["ms-comprobante-factura"], {
    POWERTOOLS_SERVICE_NAME = "ms-comprobante-factura"
    KAFKA_BOOTSTRAP_SERVERS = var.kafka_bootstrap_servers
    KAFKA_TOPIC_EVENTOS     = var.kafka_topic_eventos
    TABLE_IDEMPOTENCIA      = module.dynamodb.table_names["idem-comprobante"]
    IDEMPOTENCY_TTL_ATTR    = var.idempotency_ttl_attribute
  })

  policy_statements = [
    {
      sid       = "Idempotencia"
      actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
      resources = [module.dynamodb.table_arns["idem-comprobante"]]
    },
    {
      sid       = "ConsumirColaComprobantes"
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
      resources = [module.sqs_comprobantes.queue_arn]
    },
  ]
}

# Triggers
resource "aws_lambda_event_source_mapping" "outbox_stream" {
  event_source_arn               = module.dynamodb.stream_arns["outbox"]
  function_name                  = module.lambda_outbox_relay.function_arn
  starting_position              = "LATEST"
  batch_size                     = var.outbox_batch_size
  maximum_retry_attempts         = var.outbox_max_retry_attempts
  bisect_batch_on_function_error = true

  filter_criteria {
    filter {
      pattern = jsonencode({ eventName = ["INSERT"] })
    }
  }
}

resource "aws_lambda_event_source_mapping" "comprobantes_sqs" {
  event_source_arn        = module.sqs_comprobantes.queue_arn
  function_name           = module.lambda_comprobante.function_arn
  batch_size              = var.comprobantes_batch_size
  function_response_types = ["ReportBatchItemFailures"]
}

############################ Step Functions ############################
module "stepfunctions" {
  source = "./modules/stepfunctions"

  name                   = "${local.prefix}-facturacion"
  type                   = var.sfn_type
  definition_template    = "${path.root}/templates/facturacion.asl.json.tftpl"
  log_retention_days     = var.lambda_log_retention_days
  log_level              = var.sfn_log_level
  lambda_tarifas_arn     = module.lambda_tarifas.function_arn
  lambda_calculo_arn     = module.lambda_calculo.function_arn
  lambda_facturacion_arn = module.lambda_facturacion.function_arn
  dlq_transactions_url   = module.sqs_transactions.dlq_url
  dlq_transactions_arn   = module.sqs_transactions.dlq_arn
  comprobantes_queue_url = module.sqs_comprobantes.queue_url
  comprobantes_queue_arn = module.sqs_comprobantes.queue_arn
  retry_max_attempts     = var.sfn_retry_max_attempts
  retry_interval_seconds = var.sfn_retry_interval_seconds
  retry_backoff_rate     = var.sfn_retry_backoff_rate
}

# Trigger cola -> Step Functions: EventBridge Pipes.
# Justificación: es la opción más simple (sin código ni Lambda de arranque que mantener, sin permisos
# extra de runtime, y con batch/reintentos gestionados). El Event Mesh del proyecto NO es EventBridge,
# pero Pipes aquí es solo un conector SQS->SFN, no un mesh.
module "pipe_transactions" {
  source = "./modules/pipe"

  name              = "${local.prefix}-tx-a-sfn"
  source_queue_arn  = module.sqs_transactions.queue_arn
  state_machine_arn = module.stepfunctions.state_machine_arn
  sfn_type          = var.sfn_type
}

############################ EventBridge ############################
module "eventbridge" {
  source = "./modules/eventbridge"

  name_prefix         = local.prefix
  bus_name            = local.bus_name
  target_lambda_arn   = module.lambda_orchestrator.function_arn
  target_lambda_name  = module.lambda_orchestrator.function_name
  schedule_expression = var.cierre_mes_schedule_expression
  schedule_timezone   = var.cierre_mes_schedule_timezone
  schedule_enabled    = var.cierre_mes_schedule_enabled
}

############################ ECR ############################
module "ecr_process_billing" {
  source = "./modules/ecr"

  repository_name = "${local.prefix}/ms-process-billing"
  keep_images     = var.ecr_keep_images
}

############################ Observabilidad ############################
module "observability" {
  source = "./modules/observability"

  name_prefix   = local.prefix
  alarm_actions = var.alarm_actions
  dlq_names = {
    transacciones = module.sqs_transactions.dlq_name
    comprobantes  = module.sqs_comprobantes.dlq_name
  }
}
