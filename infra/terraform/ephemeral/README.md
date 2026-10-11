# Stack EFÍMERO — Experimentación 2 (Voltera, facturación EDA)

> **COSTO ~0,28 USD/h mientras exista. DESTRÚYELO AL TERMINAR** (`make down`). No lo dejes de un día para otro.

Event Mesh con **Kafka vía Strimzi** sobre EKS (sustituye al EventMesh/MSK descartados en el spike).
Data plane = Kafka; control plane = CRDs de Strimzi + Apicurio Registry + catálogo `../../../mesh/asyncapi.yaml`.

## Qué crea
Dos raíces Terraform (Terraform no puede planear recursos Kubernetes antes de que exista el clúster, y el proveedor se configura con el endpoint del clúster; por eso se aplican en orden):

| Raíz | Crea |
|---|---|
| `cluster/` | VPC mínima **sin NAT** (2 subredes públicas, IGW, endpoints gateway DynamoDB/S3), EKS (por defecto v1.36, soporte estándar), 1 managed node group (2 × t3.large), add-ons (vpc-cni, kube-proxy, coredns, pod-identity-agent, EBS CSI, Container Insights), roles IAM (Pod Identity para `ms-process-billing`), SG para el relay, log groups con retención de 3 días |
| `platform/` | Helm: Strimzi 1.2.0 (OCI), KEDA 2.21.0. Manifiestos (`../../../k8s/`): StorageClass `gp3-delete`, Kafka `billing` y `dominios` (KRaft, 1 broker, `deleteClaim: true`), `KafkaTopic` x2, `KafkaMirrorMaker2` billing→dominios, Apicurio Registry 3.3.3 (en memoria), `ms-process-billing` (Deployment + Service + `ScaledObject` kafka 1..5) |

Se usa `kubectl_manifest` (alekc/kubectl) y no `kubernetes_manifest` porque no exige CRDs en el plan: `validate`/`plan` funcionan limpio.

### Sin NAT Gateway (justificación)
NAT cuesta ~0,045 USD/h + datos (>15 % del presupuesto horario). Los nodos van en subredes públicas con IP pública (~0,005 USD/h c/u) y el SG del clúster **no admite ningún ingreso desde internet** (solo desde sí mismo y desde la VPC en el rango NodePort). Aceptable para laboratorio efímero; no es patrón de producción.

### Relay (Lambda de base) → Kafka
Decisión: **listener `vpc` de Strimzi tipo `loadbalancer` con NLB interno** (un solo LB, `createBootstrapService: false`; con 1 broker su DNS es el bootstrap) + **Lambda `outbox-relay` adjunta a la VPC** (sin internet; DynamoDB por endpoint gateway gratis; el event source mapping de Streams no necesita red de la Lambda). Costo extra ≈ 0,0225 USD/h (+ LCU mínimas). Alternativas descartadas: mover el relay a un pod (habría que escribir un lector de DynamoDB Streams con KCL/polling), o NLB público (expone Kafka sin auth a internet).
Sin auth/TLS (**TODO**: SCRAM + `KafkaUser`); protegido solo por SG/`loadBalancerSourceRanges` a la VPC.

## Comandos
```bash
# 0) Base aplicado (estado local en ../base/terraform.tfstate)
make validate            # fmt + init -backend=false + validate (local, sin AWS)
make up                  # cluster -> kubeconfig -> platform (CREA recursos, ~15-20 min)
make relay-bootstrap     # hostname:9094 del NLB interno -> kafka_bootstrap_servers en base
make status
make down                # scripts/destroy-ephemeral.sh: borra Strimzi/PVC, destruye, lista huérfanos
```
Variables: `cluster/variables.tf`, `platform/variables.tf` (ejemplo en `cluster/terraform.tfvars.example`). Región `us-east-1`; tags `proyecto=voltera`, `experimento=exp2-eda`, `stack=efimero`. Imagen: `process_billing_image_tag` (por defecto `latest`; sin imagen en ECR el pod queda en `ImagePullBackOff` hasta publicarla).

## Cambios requeridos en el stack BASE (no aplicados aquí)
1. `kafka_bootstrap_servers` = salida de `make relay-bootstrap`.
2. `outbox-relay`: añadir `vpc_config` (variable `relay_vpc_config` opcional, valor = output `relay_vpc_config` de `cluster`: subnet_ids + security_group_ids) y la política `AWSLambdaVPCAccessExecutionRole` (ENI). Debe poder volver a `null`.
3. Empaquetar un cliente Kafka (p. ej. `kafka-python`/`confluent-kafka`) en el zip del relay y usar `KAFKA_BOOTSTRAP_SERVERS` / `KAFKA_TOPIC`. El rol del relay **no** necesita `kafka-cluster:*` (eso era de MSK).
4. **Orden de cierre:** antes de `make down`, aplicar base con `relay_vpc_config = null` y esperar a que se liberen las ENI de la Lambda (10-30 min); si no, la VPC no se puede borrar. El script lo verifica y aborta.
5. Opcional: el relay debe publicar `ConsumoFacturablePreparado` con clave = `facturaId` y headers `cicloId`/`facturaId`.

## Lambdas en la VPC (incidencia #7)
Todas las Lambdas que publican a `voltera.eventos` (relay + 4 microservicios) usan los outputs `lambda_subnet_ids` y `lambda_security_group_ids` del stack `cluster`, y como `KAFKA_BOOTSTRAP_SERVERS` la salida de `make relay-bootstrap`. Los nodos aceptan el rango NodePort desde la VPC y desde ese SG. Alcanzan DynamoDB (endpoint gateway gratis) y SQS/X-Ray (endpoints de interfaz en una sola AZ, ~0,02 USD/h; variable `lambda_interface_endpoints`). No hay subredes privadas (sin NAT). Al destruir, TODAS esas Lambdas deben quedar sin `vpc_config`.

## Costo estimado por hora
EKS 0,10 + 2 × t3.large 0,166 + NLB interno 0,0225 + endpoints de interfaz 0,02 + IPv4 públicas 0,01 + EBS/logs/CloudWatch ≈ **0,30–0,33 USD/h** (exporter + agente Prometheus: +~170 MiB, sin costo horario adicional salvo ~0,30 USD/mes por métrica custom; Container Insights añade centavos por métricas/logs). Con `enable_container_insights=false` baja un poco.

## Lag de Kafka en CloudWatch
El lag ahora lo publica **la app** (`ms-process-billing`, `METRICS_BACKEND=cloudwatch`): métrica `KafkaConsumerLag`, namespace `Voltera/Exp2`, dimensiones `service=ms-process-billing` y `topic=voltera.consumo-facturable-preparado`, estadística **Sum**. El rol Pod Identity de la app tiene `cloudwatch:PutMetricData` restringido a ese namespace (`metrics_namespace`).
`kafkaExporter` sigue habilitado en el CR `billing`. El agente `cwagent-prometheus` (k8s/observability) queda **apagado** (`enable_prometheus_lag_agent=false`): su configuración no funciona (claves inválidas `global/scrape_configs` para el receiver y fallo de credenciales del exportador EMF); no se borró.

## Exp. 4: consumidor de reportes y esquemas
- `reportes-consumer` (k8s/consumers/, ns `kafka`): consume `billing.voltera.eventos` en el clúster dominios con el grupo `reportes` y emite una línea JSON por evento (cicloId/facturaId de los headers). Es opcional y no toca nada existente: `terraform -chdir=platform apply -var reportes_consumer_enabled=true` (solo crea ese Deployment). Logs: `kubectl -n kafka logs deploy/reportes-consumer`.
- `scripts/register-schemas.sh [--mode port-forward|pod] [--dry-run]`: registra en Apicurio (grupo `voltera`) un esquema JSON por cada uno de los 13 mensajes de `mesh/asyncapi.yaml`; idempotente (`ifExists=FIND_OR_CREATE_VERSION`). Repetir si Apicurio se reinicia (memoria).

## Supuestos / pendientes
- `ms-process-billing` expone salud en `:8080/healthz` (variable) y lee las env definidas en `k8s/apps/ms-process-billing.yaml.tftpl`.
- Los eventos replicados en `dominios` se llaman `billing.voltera.eventos` (prefijo del MirrorMaker2).
- El registro de esquemas es un paso manual (`scripts/register-schemas.sh`); el cuerpo de la API v3 de Apicurio (grupo + artifact con `firstVersion`) no se probó contra un Apicurio real.
- Las anotaciones del NLB usan el proveedor en el árbol de EKS (`aws-load-balancer-type: nlb` + `internal`); si instalas el AWS Load Balancer Controller habría que cambiarlas.
