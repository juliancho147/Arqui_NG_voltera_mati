# Guía de redespliegue y ejecución de pruebas — Experimentación 2

> Para volver a levantar todo desde cero, ejecutar las pruebas y volver a apagar sin dejar sobrecostos.
> Escrita el 2026-10-10 a partir de la primera sesión real de despliegue. Todos los comandos se ejecutan desde la carpeta `codigo_fuente_voltera/` salvo que se indique otra cosa.

## 0. Estado actual (2026-10-10, ~13:00 hora Bogotá)

**Toda la infraestructura de AWS está dada de baja.** Verificado con consultas independientes:

| Recurso | Estado |
|---|---|
| Clúster EKS `voltera-exp2-eph`, nodos EC2, VPC, endpoints, NLB, EBS | Destruidos (49 + 9 recursos) |
| Stack base: DynamoDB, SQS y DLQ, Lambdas, Step Functions, Pipe, EventBridge, ECR, IAM, log groups | Destruido (55 recursos) |
| Usuario IAM `voltera-grafana`, su política y su clave de acceso | Borrados |
| Grafana local (Docker) | Detenido (`docker compose down`; el volumen de datos se conserva) y credenciales locales borradas |
| AWS Budgets | **Se conservan** (alertas en 3 y 5 USD `voltera-exp2-alertas-tempranas`, más los 3 que ya existían) |

Costo actual de Voltera en AWS: **0 USD/h**. No hay nada que pague por hora.

Lo que se conserva en tu máquina: el código, los reportes en `experiments/reports/`, la bitácora `experiments/RESULTADOS.md`, las imágenes de Docker locales y los `terraform.tfstate` locales (ahora vacíos). Los resultados de las pruebas están documentados en `experiments/RESULTADOS.md`.

> Dos EBS de 5 GB (`vol-0901e88eb9dcd808e`, `vol-0a477e11a36f569ea`) siguen libres en us-east-1: **son de otro proyecto (matching-engine)**, no de Voltera. No se tocaron.

---

## 1. Prerrequisitos

| Herramienta | Notas |
|---|---|
| AWS CLI v2 con credenciales en la cuenta `767397902469` | Exporta `AWS_REGION=us-east-1` (el perfil por defecto no tiene región). |
| Terraform ≥ 1.6 | Los stacks usan estado **local**. |
| kubectl, Docker Desktop con `buildx` | El daemon de Docker debe estar encendido. |
| Python 3.12 | Venv del runner en `experiments/runner/.venv`; el script de seed lo reutiliza. |
| Layer de Powertools | `arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-arm64:38` (versión vigente el 2026-10-10; si cambia, busca la última con `aws lambda get-layer-version --layer-name <ARN> --version-number N`). |
| Tu IP pública | Para restringir el API de EKS: `curl -s https://checkip.amazonaws.com`. |

Comprobaciones previas:

```bash
export AWS_REGION=us-east-1
aws sts get-caller-identity
aws budgets describe-budgets --account-id 767397902469 --query 'Budgets[].BudgetName' --output text   # alertas de costo activas
docker info >/dev/null && echo "docker ok"
```

---

## 2. Orden de despliegue

Tiempos y costos aproximados: **base** (centavos al mes) tarda 2–3 min. **Efímero** (≈ 0,30–0,33 USD/h) tarda unos 25 min entre clúster y plataforma.

### Paso 1 — Empaquetar las Lambdas (arm64)
```bash
./services/build.sh          # genera services/_dist/<servicio>/ (voltera_common + pydantic + confluent-kafka arm64)
```

### Paso 2 — Stack base
```bash
cd infra/terraform/base
terraform init
terraform plan -out=tfplan \
  -var "services_dir=$PWD/../../../services/_dist" \
  -var "powertools_layer_arn=arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-arm64:38"
terraform apply tfplan       # ~55 recursos
cd ../../..
```
Para acelerar el caso B del Experimento 2 (la DLQ de comprobantes en ~2 min en vez de ~9) añade `-var-file=experiment.tfvars` (copia de `experiment.tfvars.example`, visibilidad de 40 s).

### Paso 3 — Prueba de humo del stack base (sin Kafka)
```bash
experiments/smoke/smoke_test.sh            # siembra 2 transacciones, envía 2 mensajes y muestra cada comando
experiments/smoke/smoke_test.sh --cleanup <CICLO_ID>
```
Resultado esperado: 2 ejecuciones de Step Functions `SUCCEEDED`, colas en 0 y comprobantes `NOTIFICADA`. Los avisos "mesh sin configurar" son normales sin Kafka.

### Paso 4 — Imagen de `ms-process-billing` (**amd64**)
Los nodos t3.large son x86: **no** subas la imagen arm64.
```bash
REPO=767397902469.dkr.ecr.us-east-1.amazonaws.com/voltera-exp2/ms-process-billing
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 767397902469.dkr.ecr.us-east-1.amazonaws.com
docker buildx build --platform linux/amd64 --provenance=false \
  -f services/ms-process-billing/Dockerfile -t "${REPO}:latest" --push .
```
En zsh escribe siempre `"${REPO}:latest"` con llaves: `$REPO:latest` aplica un modificador de zsh y rompe el nombre.

### Paso 5 — Clúster EKS (stack efímero 1/2)
```bash
cd infra/terraform/ephemeral/cluster
cat > terraform.tfvars <<EOF
aws_region                = "us-east-1"
base_state_path           = "../../base/terraform.tfstate"
public_access_cidrs       = ["$(curl -s https://checkip.amazonaws.com | tr -d '[:space:]')/32"]
enable_container_insights = true
EOF
terraform init && terraform plan -out=tfplan && terraform apply tfplan     # ~12-15 min, 49 recursos
aws eks update-kubeconfig --region us-east-1 --name voltera-exp2-eph
kubectl get nodes            # 2 nodos Ready
cd ../../../..
```
**Empieza aquí el reloj de costo.**

### Paso 6 — Plataforma: Strimzi, Kafka x2, MirrorMaker 2, KEDA, Apicurio, `ms-process-billing`
```bash
cd infra/terraform/ephemeral/platform
terraform init && terraform plan -out=tfplan && terraform apply tfplan     # ~10 min
kubectl -n kafka get kafka,kafkatopic,kafkamirrormaker2
kubectl -n voltera get pods,scaledobject
cd ../../../..
```
Esperado: `billing` y `dominios` en `READY=True`, los 2 tópicos y MirrorMaker 2 listos, y `ms-process-billing` en `1/1 Running`.

### Paso 7 — Conectar las Lambdas a Kafka
```bash
BS=$(./scripts/kafka-relay-bootstrap.sh | tail -1)               # <hostname NLB>:9094
terraform -chdir=infra/terraform/ephemeral/cluster output          # subnets y SG de las Lambdas
```
Escribe `infra/terraform/base/ephemeral.tfvars`:
```hcl
kafka_bootstrap_servers   = "<BS>"
lambda_subnet_ids         = ["subnet-...", "subnet-..."]      # output lambda_subnet_ids
lambda_security_group_ids = ["sg-..."]                         # output lambda_security_group_ids
powertools_layer_arn      = "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-arm64:38"
```
```bash
cd infra/terraform/base
terraform plan -out=tfplan -var-file=ephemeral.tfvars -var "services_dir=$PWD/../../../services/_dist"
terraform apply tfplan      # +5 / ~10 cambios
cd ../../..
```

### Paso 8 — Grafana (opcional, para ver las pruebas)
Crear el usuario de solo lectura (detalle en `observability/README.md`):
```bash
cd observability
aws iam create-policy --policy-name voltera-grafana-readonly --policy-document file://iam/grafana-readonly-policy.json
aws iam create-user --user-name voltera-grafana
aws iam attach-user-policy --user-name voltera-grafana --policy-arn arn:aws:iam::767397902469:policy/voltera-grafana-readonly
aws iam create-access-key --user-name voltera-grafana     # guarda la clave en aws/credentials (perfil [voltera-grafana]), permisos 600
cp .env.example .env    # cambia GRAFANA_ADMIN_PASSWORD si no existe ya
docker compose up -d    # http://localhost:3000   (usuario admin; la clave está en .env, archivo oculto)
```
Si cambias un dashboard: `python3 tools/gen_dashboards.py && docker compose restart grafana`.

### Paso 9 — Ejecutar las pruebas
```bash
cd experiments/runner
export AWS_REGION=us-east-1
.venv/bin/python -m runner exp1 --n 10 --delay 5 --dry-run       # ver el plan sin tocar nada
.venv/bin/python -m runner exp1 --n 200 --delay 2                # prueba 1 (absorción del pico)
.venv/bin/python -m runner exp2 --yes                            # caída de un dependiente (pide confirmación sin --yes)
.venv/bin/python -m runner exp3 --yes
.venv/bin/python -m runner exp4
.venv/bin/python -m runner restore --list                        # revierte fallos inyectados pendientes
```
Los reportes quedan en `experiments/reports/<fecha-hora>-<exp>/report.md`. **Anota cada prueba en `experiments/RESULTADOS.md`.**
Para ver el Experimento 1 en Grafana: `Exp1 - Absorcion del pico`, rango "últimos 30 minutos", refresco automático (CloudWatch tarda 1–2 min en mostrar los primeros puntos).

---

## 3. Apagado completo (siempre al terminar)

Orden obligatorio: **primero** sacar las Lambdas de la VPC, **después** destruir el efímero, y **al final** el base.

```bash
# 1) Lambdas fuera de la VPC
cd infra/terraform/base
cat > ephemeral.tfvars <<'EOF'
kafka_bootstrap_servers   = ""
lambda_subnet_ids         = []
lambda_security_group_ids = []
powertools_layer_arn      = "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-arm64:38"
EOF
terraform plan -out=tfplan -var-file=ephemeral.tfvars -var "services_dir=$PWD/../../../services/_dist" && terraform apply tfplan
cd ../../..

# 2) Stack efímero (borra primero Strimzi y los PVC, espera los balanceadores, destruye platform y cluster)
AWS_REGION=us-east-1 ./scripts/destroy-ephemeral.sh --yes
```

**Dos bloqueos que ocurrieron y cómo se resolvieron** (el borrado de la VPC tardó ~1 h por esto):
1. La **subred** no se borraba porque quedó una **interfaz de red huérfana** `aws-K8S-i-…` (la deja el plugin de red del nodo): `aws ec2 describe-network-interfaces --filters Name=subnet-id,Values=<subnet>`, y si está `available`, `aws ec2 delete-network-interface --network-interface-id <eni>`.
2. La **VPC** no se borraba por el **grupo de seguridad `eks-cluster-sg-voltera-exp2-eph-*`** que EKS crea y deja huérfano: `aws ec2 delete-security-group --group-id <sg>`.

```bash
# 3) Stack base (ECR y tablas incluidos; los datos de prueba se pierden)
cd infra/terraform/base
terraform plan -destroy -out=tfdestroy -var-file=ephemeral.tfvars -var "services_dir=$PWD/../../../services/_dist" && terraform apply tfdestroy
cd ../../..

# 4) IAM de Grafana y Grafana local
aws iam delete-access-key --user-name voltera-grafana --access-key-id <ID>
aws iam detach-user-policy --user-name voltera-grafana --policy-arn arn:aws:iam::767397902469:policy/voltera-grafana-readonly
aws iam delete-user --user-name voltera-grafana
aws iam delete-policy --policy-arn arn:aws:iam::767397902469:policy/voltera-grafana-readonly
(cd observability && docker compose down && rm -f aws/credentials)
```

### Verificación final (todo debe dar 0 / vacío)
```bash
export AWS_DEFAULT_REGION=us-east-1
aws eks list-clusters --query 'length(clusters)' --output text
aws ec2 describe-instances --filters Name=instance-state-name,Values=running,pending --query 'length(Reservations[].Instances[])' --output text
aws elbv2 describe-load-balancers --query 'length(LoadBalancers)' --output text
aws ec2 describe-vpcs --filters Name=tag:proyecto,Values=voltera --query 'length(Vpcs)' --output text
aws ec2 describe-nat-gateways --filter Name=state,Values=available,pending --query 'length(NatGateways)' --output text
aws ec2 describe-addresses --query 'length(Addresses)' --output text
aws lambda list-functions --query "length(Functions[?starts_with(FunctionName,'voltera-exp2')])" --output text
aws dynamodb list-tables --query "length(TableNames[?starts_with(@,'voltera-exp2')])" --output text
aws ecr describe-repositories --query "length(repositories[?starts_with(repositoryName,'voltera')])" --output text
aws ec2 describe-volumes --filters Name=status,Values=available --query 'Volumes[].[VolumeId,Tags[?Key==`Name`]|[0].Value]' --output text   # ignora los de matching-engine
```

---

## 4. Lecciones de la primera sesión (errores ya corregidos en el código)

| Problema | Causa | Dónde quedó corregido |
|---|---|---|
| `apply` del clúster falló en una regla de seguridad | La descripción llevaba `>` (carácter no permitido) | `ephemeral/cluster/network.tf` |
| Los recursos de Kafka no se creaban | El grupo de API es `kafka.strimzi.io/v1`, no `strimzi.io/v1` | `k8s/kafka/*.tftpl` |
| `ms-process-billing` en `ErrImagePull` | Imagen arm64 en nodos amd64 | Construir con `--platform linux/amd64` (paso 4) |
| `ms-process-billing` en `CrashLoopBackOff` | boto3 no lee `AWS_REGION`, exige `AWS_DEFAULT_REGION` | `k8s/apps/ms-process-billing.yaml.tftpl` |
| Lag de Kafka sin datos en Grafana | `cwagent-prometheus` rechazaba su configuración y fallaba con credenciales | Apagado por defecto; ahora la app publica `KafkaConsumerLag` con `put_metric_data` |
| Métricas del pod ausentes en CloudWatch | El EMF por stdout del pod no se extrae | `METRICS_BACKEND=cloudwatch` + permiso `cloudwatch:PutMetricData` |
| Lag inflado en el panel | CloudWatch suma las 6 muestras por minuto (flush de 10 s) | El panel usa `Sum / 6` |
| Borrado del clúster muy lento | ENI y SG huérfanos | Sección 3 |

## 5. Cuidados de costo
- El stack efímero cuesta ≈ 0,30–0,33 USD/h (EKS 0,10 + 2 × t3.large 0,17 + NLB interno 0,02 + endpoints de interfaz 0,02). **Un olvido de un mes serían ~195 USD.**
- Alertas activas: 3 y 5 USD (`voltera-exp2-alertas-tempranas`), 10 USD mensual con pronóstico y dos de gasto cero. AWS Budgets tarda horas en reflejar el gasto: no sustituye al apagado.
- Una sesión completa (desplegar, 4 pruebas y apagar) ronda 1–2 USD.

## 6. Pendientes antes de repetir
- Investigar el **sobrecosto por mensaje** de `ms-process-billing` y volver a medir el criterio de 120 s (en la prueba de 200 el lote tardó unos 176 s).
- Decidir si la publicación de eventos al mesh sigue siendo *best-effort*: en la prueba de 200 se perdió un evento de estado (una factura sí se procesó, pero el ciclo quedó en 199/200).
- Probar los experimentos 2, 3 y 4 (solo el 1 se ha ejecutado contra AWS).
- Activar el consumidor de reportes (`-var reportes_consumer_enabled=true` en `platform`) y registrar los esquemas (`scripts/register-schemas.sh`) para el Experimento 4.
