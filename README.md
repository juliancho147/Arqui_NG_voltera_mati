# Voltera — Experimentación 2: facturación y liquidación dirigida por eventos

Prueba de arquitectura (ARTI4208, Maestría en Arquitectura, Uniandes) del **cierre de facturación de fin de mes**: miles de facturas llegan a la vez y el sistema debe absorber el pico, aislar fallos y no perder ninguna solicitud. Se construye sobre AWS con 6 microservicios, un Event Mesh en Kafka y tres experimentos que se ejecutan con una línea y se observan en Grafana.

> Código de la experimentación anterior: [`_legacy/`](_legacy/) (se conserva, no se borra).

## Los experimentos

| # | Experimento | Atributo de calidad | Criterio principal |
|---|---|---|---|
| 1 | Absorción del pico | Escalabilidad / desempeño | El lote termina dentro del SLA; KEDA escala y vuelve a 1 pod |
| 2 | Resiliencia ante fallos (aislamiento + cero pérdida) | Disponibilidad / confiabilidad | Con un dependiente caído, pods muertos, una Lambda con fallos y duplicados a propósito: las facturas siguen saliendo, inyectadas = emitidas + rechazadas + DLQ (antes y después del redrive), emitidas == N (no N+D) y colas/DLQ vuelven a 0 |

Los antiguos Exp. 2 (caída de un dependiente) y Exp. 3 (cero pérdida) se unieron en el **Exp. 2**, con una sola vista de Grafana; `exp=3` queda como alias. Un tercer experimento (Event Mesh: observabilidad y contexto de eventos, `exp4` en el runner) se muestra como capa visible dentro de los otros dos.

## Arquitectura en una mirada

```
EventBridge Scheduler → Lambda ms-orchestrator-billing → DynamoDB (outbox) → outbox-relay
        → Kafka "billing" (Event Mesh) → ms-process-billing (EKS, KEDA 1..5)
        → SQS → EventBridge Pipe → Step Functions
              → ms-tarifas → ms-calculo-consumo-neto → ms-facturacion
        → SQS → ms-comprobante-factura
Eventos de estado ──► Kafka "billing" ──MirrorMaker 2──► Kafka "dominios"
Observabilidad: CloudWatch + X-Ray + Grafana (local)
```

Diagrama oficial: [`../voltera_arquitectura_aws.drawio`](../voltera_arquitectura_aws.drawio). Patrones: Queue-Based Load Leveling, Competing Consumers, autoescalado por eventos, Bulkhead, Retry/backoff, DLQ, Idempotencia, Outbox.

## Mapa del repositorio

| Carpeta / archivo | Contenido |
|---|---|
| [`services/`](services/) | Los 6 microservicios + `outbox-relay`, con sus pruebas (`build.sh`, `run_tests.sh`) |
| [`libs/voltera_common/`](libs/voltera_common/) | Eventos CloudEvents, publicación al mesh, métricas y logs |
| [`infra/terraform/`](infra/terraform/) | `base/` (persistente), `ephemeral/cluster/` (EKS) y `ephemeral/platform/` (Kafka, KEDA, apps) |
| [`k8s/`](k8s/) | Plantillas de Kafka (Strimzi), MirrorMaker 2, Apicurio y `ms-process-billing` |
| [`mesh/asyncapi.yaml`](mesh/asyncapi.yaml) | Catálogo de los 13 eventos del Event Mesh |
| [`scripts/`](scripts/) | Apagado del efímero, bootstrap de Kafka, registro de esquemas |
| [`experiments/`](experiments/) | Runner, lanzador `correr.py`, semillas, humo, reportes y bitácora de resultados |
| [`observability/`](observability/) | Grafana en Docker, 5 dashboards y guion de exposición |
| [`spikes/`](spikes/) | Pruebas de concepto descartadas (Apache EventMesh) |

## Inicio rápido

```bash
# 1. Desplegar (≈ 35 min, ≈ 0,31 USD/h mientras esté encendido): ver REDESPLIEGUE.md §2
# 2. Ensayo corto
cd experiments && python3 correr.py fact=100
# 3. Grabar un experimento con Grafana abierto en http://localhost:3000
python3 correr.py exp=1 fact=500
python3 correr.py exp=2 caso=B matar=2 fallos=0.25 ventana=90 dupl=50
# 4. Apagar todo al terminar: REDESPLIEGUE.md §3 (obligatorio)
```

Parámetros y fases: [`experiments/README.md`](experiments/README.md).

## Qué necesitas

Cuenta AWS (`us-east-1`), AWS CLI v2, Terraform ≥ 1.6, kubectl, Docker con `buildx`, Python 3.12 y tu IP pública para el API de EKS. Detalle completo en [`experiments/README.md`](experiments/README.md) §9.

## Documentación

| Documento | Para qué |
|---|---|
| [`experiments/README.md`](experiments/README.md) | Cómo ejecutar los experimentos y qué se requiere para montarlos |
| [`REDESPLIEGUE.md`](REDESPLIEGUE.md) | Desplegar, probar y **apagar** sin dejar sobrecostos; lecciones aprendidas |
| [`experiments/RESULTADOS.md`](experiments/RESULTADOS.md) | Bitácora de cada prueba (parámetros, medidas, hallazgos) |
| [`observability/GUION-EXPOSICION.md`](observability/GUION-EXPOSICION.md) | Guion de 6–8 min por experimento para grabar y explicar los gráficos |
| [`PLAN-EXPERIMENTACION.md`](PLAN-EXPERIMENTACION.md) | Caso de negocio, decisiones, parámetros y plan de experimentos |
| [`ORQUESTACION.md`](ORQUESTACION.md) | Tablero de agentes, incidencias y observaciones |
| [`../Voltera_Memoria_Proyecto.md`](../Voltera_Memoria_Proyecto.md) | Memoria del proyecto (sección 9: experimentación 2) |

## Decisiones clave

- **Event Mesh = Kafka + Strimzi sobre EKS** (plano de datos y de control). EventBridge se descartó por no ser un mesh; Apache EventMesh se probó en un spike y se descartó.
- **Dos stacks de Terraform:** `base` casi gratis y persistente; `ephemeral` (EKS) solo mientras se prueba.
- **Publicación al mesh *best-effort*** con reintentos y reconciliación del ciclo contra DynamoDB (cubre facturas notificadas).
- **Sin NAT** y API de EKS restringido a una IP.

## Estado de los resultados

| Prueba | Resultado |
|---|---|
| Exp. 1, N = 10 | PASS (65 s) |
| Exp. 1, N = 100 / 200 (primera sesión) | Fuera del SLA de 120 s (150 s / ~176 s); cero pérdidas salvo un evento de estado |
| Exp. 1, N = 100 (ensayo 2026-10-11) | 188 s; el código por mensaje no es el cuello (sobrecosto 4,5 %); causa: arranque de pods y reajustes de particiones |
| Exp. 1, N = 1500 | Ejecutado por el usuario; ver `experiments/RESULTADOS.md` |
| Exp. 2 y Exp. 3 antiguos (demo del 2026-10-11) | Registrados en `experiments/RESULTADOS.md` (pruebas 3 y 4); ya unidos |
| Exp. 2 unificado (aislamiento + cero pérdida + duplicados) | Listo con modo demo y 52 pruebas locales (moto/mocks); pendiente de ejecución sobre AWS |

## Costos

Efímero ≈ 0,31 USD/h; sesión típica ≈ 2–3 USD; olvidarlo un mes ≈ 195 USD. **Apaga siempre** y verifica con la lista de `REDESPLIEGUE.md` §3.
