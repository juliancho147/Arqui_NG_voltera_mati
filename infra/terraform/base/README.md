# Stack BASE — Experimentación 2 (Voltera, facturación EDA)

Infraestructura barata y persistente. **No** incluye EKS, MSK/Kafka, EventMesh ni KEDA (stack efímero).

## Qué crea
- **DynamoDB** (on-demand): `transacciones` (PK `cicloId`, SK `facturaId`), `outbox` (PK `eventId`, Streams NEW_IMAGE, TTL), `process-billing` (PK `cicloId`, SK `sk` = `META` | `DEDUP#<facturaId>`, TTL), `idem-facturacion` y `idem-comprobante` (PK `facturaId`, TTL `expiresAt`).
- **SQS**: `transacciones` + DLQ, `comprobantes` + DLQ (`maxReceiveCount`=3, visibility = 6 x timeout Lambda, SSE, redrive permitido).
- **EventBridge**: bus custom `...-bus` + regla `CierreDeMes` -> orchestrator, y Scheduler mensual **deshabilitado**. No es el Event Mesh.
- **6 Lambdas** Python 3.12 (arm64) con handlers placeholder en `../../../services/<nombre>/`: un rol de mínimo privilegio y log group (retención 3 días) por Lambda, X-Ray activo, `FAIL_RATE`/`FORCE_FAIL`, concurrencia reservada configurable.
- **Step Functions** (STANDARD o EXPRESS): tarifas -> cálculo -> facturación -> `FacturaEmitida` a SQS comprobantes; Retry configurable; Catch -> DLQ de transacciones; logs + X-Ray. Disparada por **EventBridge Pipes** desde la cola (lo más simple: sin código).
- **ECR** `voltera-exp2/ms-process-billing`, **alarmas** de DLQ no vacía.

## Variables clave
`aws_region` (us-east-1), `n_solicitudes` (10), `max_receive_count` (3), `sfn_type`, `sfn_retry_max_attempts/interval_seconds/backoff_rate` (3/2/2.0), `fault_injection`, `reserved_concurrency`, `powertools_layer_arn`, `kafka_bootstrap_servers`, `cierre_mes_schedule_enabled`. Ver `variables.tf`.

Ejemplos (Exp. 2):
```hcl
fault_injection      = { "ms-tarifas" = { force_fail = true } }
reserved_concurrency = { "ms-comprobante-factura" = 0 }
```
Layer Powertools (público): `arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-arm64:<versión>` (verifica la versión vigente en la doc de Powertools).

## Comandos
```bash
export AWS_REGION=us-east-1   # o -var aws_region=...
terraform init
terraform validate
terraform plan -out tfplan
terraform apply tfplan
terraform destroy
```
`terraform output -json` entrega ARNs/URLs para el stack efímero y el runner (`sqs`, `eventbridge`, `lambdas`, `step_functions`, `outbox_stream_arn`, `ecr_process_billing`, `experiment_parameters`).

## Costo esperado
Casi cero en reposo: DynamoDB on-demand, SQS, Lambda y Step Functions cobran por uso (centavos con 10 solicitudes). Fijos aproximados: 2 alarmas CloudWatch (~USD 0.20/mes), almacenamiento ECR/logs (centavos). Estimado < USD 1/mes en reposo.

## Integración con el stack efímero (Strimzi)
- `kafka_bootstrap_servers` = salida de `make relay-bootstrap` (`<NLB>:9094`) -> env `KAFKA_BOOTSTRAP_SERVERS` del relay.
- `relay_vpc_config = { subnet_ids = [...], security_group_ids = [...] }` (output `relay_vpc_config` de `ephemeral/cluster`); default `null` = sin VPC. Al configurarlo se adjunta `AWSLambdaVPCAccessExecutionRole`.
- El rol del relay no tiene permisos `kafka-cluster:*`. El cliente `confluent-kafka` va en el zip del relay o en un layer (`relay_extra_layer_arns`).
- El relay debe publicar con clave = `facturaId` y headers `cicloId` y `facturaId` (envs `KAFKA_KEY_FIELD`, `KAFKA_HEADER_FIELDS`; lógica en `services/outbox-relay`).
- **Orden de destrucción:** antes de `make down` en el efímero, aplicar base con `relay_vpc_config = null` y esperar la liberación de ENIs (10-30 min); si no, la VPC no se puede borrar.

## Experimentos: acelerar el Exp. 2
Default seguro: visibilidad de comprobantes = 6 x timeout Lambda = 180 s (el mensaje llega a la DLQ en ~9 min). Para llegar en ~2 min usa `terraform apply -var-file=experiment.tfvars` (copia de `experiment.tfvars.example`, visibilidad 40 s). Riesgo: con 40 s un throttle puede duplicar la entrega; la idempotencia por `facturaId` lo cubre.
