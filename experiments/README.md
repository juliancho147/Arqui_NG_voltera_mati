# Cómo ejecutar los experimentos (Voltera — Experimentación 2)

Dos experimentos principales (más un cuarto de observabilidad del mesh) sobre la facturación de fin de mes dirigida por eventos. Se lanzan con **una línea** y se ven en vivo en Grafana.

| # | Experimento | Qué demuestra | Patrones que se ven |
|---|---|---|---|
| 1 | Absorción del pico | El lote de facturas termina dentro del SLA aunque llegue de golpe | Queue-Based Load Leveling, Competing Consumers, autoescalado por eventos (KEDA) |
| 2 | Resiliencia ante fallos (aislamiento + cero pérdida) | Con un dependiente caído, pods muertos, una Lambda fallando y duplicados a propósito: el resto sigue facturando, inyectadas = emitidas + rechazadas + DLQ (antes y después del redrive), los duplicados no crean facturas extra y todo se recupera | Bulkhead, Retry con backoff, DLQ, Durable Messaging, Idempotencia, Outbox |

> **El antiguo Exp. 3 (cero pérdida) se unió al Exp. 2** en un solo escenario con una sola vista de Grafana. `exp=3` sigue funcionando como alias: avisa y ejecuta el Exp. 2. Ver la nota en [`RESULTADOS.md`](RESULTADOS.md).

El guion para explicar cada gráfico está en [`../observability/GUION-EXPOSICION.md`](../observability/GUION-EXPOSICION.md). El detalle de fases del modo demo está en [`DEMO.md`](DEMO.md).

---

## 1. Antes de empezar

La infraestructura debe estar **desplegada** (cuesta ≈ 0,31 USD/h mientras esté encendida). Pasos en [`../REDESPLIEGUE.md`](../REDESPLIEGUE.md) §2. Comprueba:

```bash
export AWS_REGION=us-east-1
aws sts get-caller-identity --query Account --output text       # 767397902469
kubectl -n voltera get pods                                      # ms-process-billing 1/1 Running
kubectl -n kafka get kafka                                       # billing y dominios READY=True
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/login   # Grafana: 200
```

Grafana: http://localhost:3000 (usuario `admin`, clave en `observability/.env`). Si no está arriba: `cd observability && docker compose up -d`.

## 2. Lanzar un experimento (una línea)

Desde `experiments/`:

```bash
python3 correr.py fact=1500                       # Exp. 1 con 1500 facturas
python3 correr.py exp=2 caso=B           # Exp. 2: cae ms-comprobante-factura (caso A: ms-tarifas)
python3 correr.py exp=2 matar=2 fallos=0.25 ventana=90 dupl=50
python3 correr.py fact=500 ensayo=1               # solo muestra el plan, no toca nada
python3 correr.py --help
```

### Parámetros (todos opcionales)

| Parámetro | Qué hace | Por defecto |
|---|---|---|
| `exp` | 1 o 2 (`3` = alias de 2, con aviso) | 1 |
| `fact` | Número de facturas inyectadas | 500 (Exp. 1) · 300 (Exp. 2) |
| `retardo` | Segundos de espera simulada por factura en `ms-process-billing` (0 = rendimiento natural del flujo) | 0.1 (Exp. 1) · 2 (Exp. 2, para que haya mensajes en vuelo y el lote dure) |
| `sla` | Límite del lote en segundos (solo Exp. 1). Si no se pone, es proporcional a `fact` | automático |
| `caso` | Exp. 2: dependiente que cae. `A` = `ms-tarifas`, `B` = `ms-comprobante-factura` | B |
| `matar` | Exp. 2: pods de `ms-process-billing` que se matan (con mensajes en vuelo) | 2 |
| `fallos` | Exp. 2: fracción de fallos inyectada en `ms-facturacion` (0,25 = 25 %); 0 = omitir | 0.25 |
| `ventana` | Exp. 2: segundos que dura el fallo parcial de `ms-facturacion` | 90 |
| `dupl` | Exp. 2: copias de mensajes ya enviados que se reenvían a propósito (por SQS y por Kafka); 0 = omitir | 50 |
| `sinpausa=1` | No espera Enter entre fases | pausa |
| `si=1` | No pide confirmaciones | confirma |
| `resultados=0` | No escribe en `RESULTADOS.md` | escribe |
| `ensayo=1` | Solo muestra el plan (`--dry-run`) | no |

> **Cuánto tarda.** Cada factura espera `retardo` segundos y KEDA escala hasta 5 pods (5 particiones), así que el tiempo ideal es `fact × retardo ÷ 5`. En la práctica el ritmo medido es ≈ 1,7 facturas/s con 5 pods. Para una grabación de 6–8 min usa `fact=500 retardo=2`. Con 1500 facturas son ≈ 14 min.

### Qué pasa al ejecutar
El script imprime cada comando `aws`/`kubectl` antes de ejecutarlo y, en cada **fase**, muestra un banner con la hora y **espera Enter** (así controlas el ritmo de la narración):

- **Exp. 1:** estado inicial → disparo (siembra + cierre de mes) → absorción → recuperación → veredicto.
- **Exp. 2** (8 fases, nombres exactos de la métrica `FaseExperimento`, namespace `Voltera/Exp2`, dimensiones `experimento=exp2` y `fase`):

| # | Fase | Qué ocurre |
|---|---|---|
| 1 | `estado_inicial` | Todo sano: `ms-process-billing` en línea, colas y DLQ en 0 |
| 2 | `disparo` | Seed de N transacciones + `CierreDeMes` |
| 3 | `fallo_dependiente` | `FORCE_FAIL` en `ms-comprobante-factura` (caso A: `ms-tarifas`); se mantiene hasta la recuperación. Se comprueba el **aislamiento**: las facturas emitidas siguen subiendo y `ms-process-billing` sigue consumiendo |
| 4 | `fallo_pod` | Se matan K pods de `ms-process-billing` con mensajes en vuelo (`DEDUP# PROCESANDO`) |
| 5 | `fallo_lambda` | `FAIL_RATE` en `ms-facturacion` durante la ventana; se restaura al terminar la ventana |
| 6 | `duplicados` | Se reenvían D copias de mensajes ya enviados: **(a)** por SQS a `voltera-exp2-transacciones` (replays de idempotencia) y **(b)** por Kafka al tópico `voltera.consumo-facturable-preparado` con `kubectl exec` en el broker `billing-billing-nodes-0` (`MensajesDuplicados` descartados) |
| 7 | `recuperacion` | Se restaura todo, se verifica la conservación **antes** del redrive, redrive de las DLQ y drenado |
| 8 | `veredicto` | PASS/FAIL por criterio con evidencia (abajo) |

- **Exp. 1:** estado inicial → disparo → absorción → recuperación → veredicto.

Cada fase queda marcada en Grafana (anotaciones) y en `marcas.json`.

#### Criterios del veredicto del Exp. 2

| Grupo | Criterios (ids en el informe) |
|---|---|
| **AISLAMIENTO** | E2.1 las facturas emitidas siguen subiendo durante el fallo del dependiente (caso A: no se emiten nuevas); E2.2 `ms-process-billing` no cae del todo y sigue consumiendo (`DEDUP# ENVIADO` sube); E2.3 `/healthz` |
| **CERO PÉRDIDA** | E2.4 pods repuestos; E2.6 inyectadas = emitidas + rechazadas + DLQ **antes** del redrive; E2.7 mensajes en vuelo reentregados; E2.8 redrive; E2.9 la misma ecuación **después**; E2.10 todas las emitidas notificadas |
| **IDEMPOTENCIA** | E2.5 se forzaron D duplicados (SQS y Kafka); E2.11 emitidas == N (no N+D), un registro por `facturaId`, `DEDUP# == N`; E2.12 se contó al menos un duplicado descartado (Kafka) o replay de idempotencia (SQS) |
| **RECUPERACIÓN** | E2.13 Lambdas restauradas; E2.14 colas y DLQ en 0 al final; E2.15 ciclo `COMPLETADO` y todas `FACT# OK` |

Detalles: la evidencia de los duplicados por Kafka se cuenta en los logs de los pods (`mensaje duplicado descartado`) y en CloudWatch (`MensajesDuplicados`); la de SQS, en `IdempotenciaReplays` (CloudWatch tarda 1–2 min, por eso el veredicto espera hasta `--timeout-metricas`, 150 s). Si el reenvío por Kafka no es posible (sin `kubectl exec` al broker o sin eventos del ciclo en el tópico), E2.5 queda `MANUAL` con el motivo y el experimento sigue solo con (a). En el caso A (`ms-tarifas` caído) la fase `fallo_lambda` apenas ve tráfico, porque ningún mensaje llega a `ms-facturacion` hasta restaurar.

> **Duración.** El perfil por defecto es *rápido* (≈ 3–5 min de ejecución, más tus pausas Enter): `fact=150 retardo=1 ventana=30 dupl=30`, con la cola de comprobantes en 10 s de visibilidad y 2 intentos (`infra/terraform/base/experiment.tfvars`). Si el lote termina antes de `fallo_pod`, E2.1/E2.2/E2.7 quedan `MANUAL` (no `FAIL`): sube `fact` o `retardo`.

## 3. Qué ver en Grafana

| Experimento | Dashboard |
|---|---|
| 1 | http://localhost:3000/d/voltera-exp1-absorcion |
| 2 (unido) | http://localhost:3000/d/voltera-exp2-resiliencia (una sola vista; reemplaza a los antiguos de Exp. 2 y 3) |

Rango "últimos 15 min" y refresco de 5 s. **CloudWatch tarda 1–2 minutos** en mostrar datos nuevos: espera ese tiempo antes de empezar a narrar. Si cambias un dashboard: `cd observability && python3 tools/gen_dashboards.py && docker compose restart grafana`.

## 4. Dónde quedan los resultados

Todo se guarda solo al terminar:

| Qué | Dónde |
|---|---|
| Tabla PASS/FAIL, medidas y reporte crudo | `reports/<fecha-hora>-demo-expN/report.md` y `report.json` |
| Marcas de cada fase (hora y epoch) | `reports/<…>/marcas.json` |
| Resumen para la bitácora | `RESULTADOS.md` (sección "Prueba n"; completa a mano "Acciones derivadas") |

## 5. Si algo sale mal

| Situación | Qué hacer |
|---|---|
| Interrumpiste con Ctrl-C o falló | Se revierten solos `FORCE_FAIL` y `FAIL_RATE` (también con Ctrl-C). Para verificarlo: `cd runner && .venv/bin/python -m runner restore --list` |
| Grafana sin datos | Revisa `observability/aws/credentials` (clave y secreto en líneas separadas), `docker compose restart grafana`, y espera 1–2 min |
| Lote más lento de lo esperado | Mide el sobrecosto: `kubectl -n voltera logs …` o CloudWatch + `services/ms-process-billing/tools/analizar_sobrecosto.py` (ver `RESULTADOS.md`, ensayo del 2026-10-11) |
| Un pod en `CrashLoopBackOff` | `kubectl -n voltera describe pod …`; las causas ya vistas están en `REDESPLIEGUE.md` §4 |

## 6. Al terminar la sesión: apagar todo

**No dejes la infraestructura encendida.** Sigue el orden de [`../REDESPLIEGUE.md`](../REDESPLIEGUE.md) §3 (Lambdas fuera de la VPC → `scripts/destroy-ephemeral.sh --yes` → base → IAM de Grafana) y ejecuta la verificación final: todo debe dar 0.

## 7. Estructura de esta carpeta

| Ruta | Contenido |
|---|---|
| `correr.py` | Lanzador de una línea (este README) |
| `DEMO.md` | Detalle del modo demo, fases y marcas |
| `runner/` | CLI (`python -m runner …`) y sus pruebas |
| `seed/` | Siembra de transacciones en DynamoDB |
| `smoke/` | Prueba de humo del stack base (sin Kafka) |
| `reports/` | Un directorio por ejecución |
| `RESULTADOS.md` | Bitácora de todas las pruebas |

---

## 8. Qué se construyó (inventario)

### Arquitectura (ver `../../voltera_arquitectura_aws.drawio`)
Cierre de mes dirigido por eventos: EventBridge Scheduler → Lambda orquestadora → DynamoDB (outbox) → Kafka (Event Mesh) → `ms-process-billing` en EKS (escala con KEDA) → SQS → EventBridge Pipe → Step Functions → 3 Lambdas → SQS → Lambda de comprobante. Eventos de estado de vuelta por el mesh. Observabilidad con CloudWatch, X-Ray y Grafana local.

### Microservicios (`../services/`)
| Servicio | Cómputo | Rol |
|---|---|---|
| `ms-orchestrator-billing` | Lambda | Dispara el cierre y hace el fan-out (outbox transaccional) |
| `ms-process-billing` | Contenedor en EKS + KEDA 1..5 | Consume Kafka, deduplica, arma y envía a SQS; lleva el estado del ciclo |
| `ms-tarifas` | Lambda (Step Functions) | Valida la tarifa |
| `ms-calculo-consumo-neto` | Lambda (Step Functions) | Calcula el cargo energético |
| `ms-facturacion` | Lambda (Step Functions) | Emite la factura (idempotente) |
| `ms-comprobante-factura` | Lambda desde SQS | Notifica la factura |
| `outbox-relay` | Lambda (DynamoDB Streams) | Publica el outbox en Kafka |

Librería común `../libs/voltera_common/`: eventos CloudEvents, publicación al mesh con reintentos, métricas y logs estructurados.

### Mejoras de la segunda tanda
- Reintentos al publicar al mesh (`MESH_PUBLISH_ATTEMPTS`, 3 por defecto).
- Reconciliación del ciclo contra `idem-comprobante` si un evento de estado se pierde (`RECONCILE_AFTER_SECONDS`).
- Concurrencia opcional por pod (`CONSUMER_CONCURRENCY`, 1 por defecto).
- Analizador de sobrecosto (`services/ms-process-billing/tools/analizar_sobrecosto.py`).
- Apicurio corregido para Container Insights (`OTEL_PROPAGATORS`).

### Infraestructura como código (`../infra/terraform/`)
- `base/` — persistente y barato: DynamoDB (5 tablas), SQS + DLQ, 6 Lambdas, Step Functions, EventBridge, Pipe, ECR, observabilidad.
- `ephemeral/cluster/` — VPC sin NAT, EKS 1.36, 2 × t3.large (amd64), IAM por Pod Identity.
- `ephemeral/platform/` — Strimzi (Kafka 4.3.1 KRaft, clústeres `billing` y `dominios`), MirrorMaker 2, KEDA, Apicurio, `ms-process-billing`.
- `../scripts/destroy-ephemeral.sh`, `kafka-relay-bootstrap.sh`, `register-schemas.sh`.
- Catálogo de eventos AsyncAPI: `../mesh/asyncapi.yaml` (13 CloudEvents).

### Experimentación y observabilidad
- `experiments/runner/` — CLI con modo demo (`demo exp1|exp2`; `exp3` = alias de `exp2`), marcas de fase, informe PASS/FAIL (52 pruebas).
- `experiments/correr.py` — lanzador de una línea.
- `../observability/` — Grafana OSS 11.4 en Docker, 5 dashboards, `GUION-EXPOSICION.md`.
- Documentos: `../REDESPLIEGUE.md`, `../ORQUESTACION.md`, `../PLAN-EXPERIMENTACION.md`, `RESULTADOS.md`.
- Código anterior conservado en `../_legacy/` (no se borra).

## 9. Qué se requiere para montarlo

### Cuenta y permisos
- Cuenta AWS (en este proyecto `767397902469`, región `us-east-1`) con permisos para crear EKS, EC2/VPC, IAM, DynamoDB, SQS, Lambda, Step Functions, EventBridge, ECR, CloudWatch y X-Ray.
- Quedan fuera del código: **AWS Budgets** (alertas de 3 y 5 USD) y la política de gasto; revísalos antes de encender.

### Herramientas locales
| Herramienta | Versión / nota |
|---|---|
| AWS CLI v2 | Con credenciales activas y `AWS_REGION=us-east-1` |
| Terraform | ≥ 1.6 (estado local) |
| kubectl | Compatible con EKS 1.36 |
| Docker Desktop + `buildx` | Daemon encendido. Imagen de `ms-process-billing` en **amd64** (nodos x86), Lambdas en **arm64** |
| Python | 3.12. Venv del runner en `experiments/runner/.venv` |
| Navegador | Para Grafana en `http://localhost:3000` |
| Tu IP pública | Para restringir el API de EKS (`curl -s https://checkip.amazonaws.com`) |

### Valores que debes tener a mano
- ARN de la capa de Powertools (arm64, versión 38 el 2026-10-10): `arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-arm64:38`.
- Archivo `infra/terraform/base/experiment.tfvars` (copia de `experiment.tfvars.example`, visibilidad de 40 s en la cola de comprobantes para acelerar el Exp. 2).
- Archivo `infra/terraform/base/ephemeral.tfvars` con el bootstrap de Kafka y las subredes/SG de las Lambdas (se rellena en el paso 7 de `REDESPLIEGUE.md`).
- `observability/.env` con la clave de Grafana, y `observability/aws/credentials` con el usuario IAM de solo lectura `voltera-grafana` (**clave y secreto en líneas separadas**).

### Orden de montaje (resumen; comandos en `REDESPLIEGUE.md` §2)
1. `./services/build.sh` (empaqueta Lambdas arm64).
2. Stack `base` (`terraform apply`, ~55 recursos, 2–3 min).
3. Imagen `ms-process-billing` amd64 a ECR.
4. Stack `ephemeral/cluster` (~15 min) y `aws eks update-kubeconfig`.
5. Stack `ephemeral/platform` (~10 min).
6. Conectar las Lambdas a Kafka (`ephemeral.tfvars` + `apply` del base).
7. Usuario IAM de Grafana + `docker compose up -d` en `observability/`.
8. Ensayo corto (`python3 correr.py fact=100`) y luego las grabaciones.

### Costos y tiempos
| Concepto | Valor |
|---|---|
| Stack efímero encendido | ≈ 0,31 USD/h (EKS 0,10 + 2 × t3.large 0,17 + NLB + endpoints) |
| Montaje completo | ≈ 30–40 min |
| Base persistente | centavos al mes |
| Sesión típica (montar, ensayar, grabar los experimentos, apagar) | ≈ 2–3 USD |
| Olvidar el efímero un mes | ≈ 195 USD → **apaga siempre** (§6) |

### Cuidados conocidos
- Los nodos son x86 y las Lambdas arm64: no mezcles las imágenes.
- En zsh escribe `"${REPO}:latest"` con llaves.
- Al apagar, el orden es obligatorio y pueden quedar una ENI y un grupo de seguridad huérfanos (`REDESPLIEGUE.md` §3).
- Los dos EBS libres de `matching-engine` son de otro proyecto: no los toques.
- Limitaciones documentadas: el mesh es *best-effort* (la reconciliación cubre solo facturas notificadas); un rechazo de negocio perdido termina en timeout del ciclo.
