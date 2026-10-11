# Plan de experimentación 2 — Facturación y liquidación dirigida por eventos

> Documento vivo. Versión 1 (2026-10-10). Reemplaza al plan de la fase síncrona, que quedó en `_legacy/PLAN-EXPERIMENTACION.md`.
> Los puntos marcados **[POR CONFIRMAR]** son propuestas mías que el usuario aún no ha validado.

## 0. Caso de negocio

Cada fin de mes Voltera cierra su ciclo y recibe una oleada de solicitudes de liquidación concentradas en pocas horas. Hay que emitir todas las facturas a tiempo, sin perder ninguna solicitud y sin frenar los servicios de tiempo real. El cierre de mes solo avisa que ocurrió; cada servicio trabaja a su propio ritmo.

**Escala del experimento:** controlada. Inicialmente **≤ 10 solicitudes**, parametrizable (`N_SOLICITUDES`). Se valida el comportamiento de la arquitectura, no la capacidad. La infraestructura se destruye al terminar cada corrida (EKS y los nodos cobran por hora).

**Fuera de alcance:** DIAN, tercero real, servicios de tiempo real.

## 1. Microservicios (6, mínimo por lineamiento)

| Bounded context | Microservicio | Rol | Cómputo | Eventos que emite | Eventos que consume |
|---|---|---|---|---|---|
| Orquestación del ciclo | `ms-orchestrator-billing` | Iniciador: dispara el cierre y hace el fan-out | Lambda (reemplaza a Glue por costo) | `CicloDeFacturacionIniciado`*, `ConsumoFacturablePreparado` | Disparador temporal (EventBridge) |
| Gestión del conjunto de facturación | `ms-process-billing` | Receptor (dedup, armado inicial, puente Kafka→SQS) y gestor de estado del ciclo | Contenedor en EKS + KEDA (1..n) | `ProcesoDeFacturacionCompletado`, `ProcesoDeFacturacionFallido` | `ConsumoFacturablePreparado` (Kafka) y eventos del Event Mesh |
| Validación tarifaria | `ms-tarifas` | Valida la tarifa | Lambda (paso de Step Functions) | `TarifaValidada`, `TarifaRechazada` | — (orquestado) |
| Cálculo de cargos | `ms-calculo-consumo-neto` | Calcula el cargo energético | Lambda (paso de Step Functions) | `CargoEnergeticoCalculado`, `CálculoDeCargoRechazado` | — (orquestado) |
| Emisión de facturas | `ms-facturacion` | Emite la factura (idempotente) | Lambda (paso de Step Functions) | `FacturaEmitida`, `EmisionDeFacturaRechazada` | — (orquestado) |
| Notificación de facturas | `ms-comprobante-factura` | Notifica la factura (simula al tercero) | Lambda desde SQS propia | `NotificacionRegistrada`, `FacturaNotificada`, `NotificacionFallida` | `FacturaEmitida` (vía SQS) |

\* Evento nuevo: lleva `cicloId` y el total de unidades, para que `process-billing` sepa cuántas facturas esperar.

### Decisiones tomadas
- **Orquestación + coreografía mixta:** el flujo tarifas → cálculo → facturación lo lleva **Step Functions** (pasa el estado entre pasos). Aun así, cada paso **publica su evento de dominio al Event Mesh** para observabilidad; esos eventos no conducen el flujo.
- **Eventos con referencias:** los datos pesados viven en DynamoDB; los eventos llevan ids (`cicloId`, `facturaId`).
- **Kafka (Strimzi en EKS)** como ingreso durable y replayable; **SQS** como cola de trabajo con DLQ. `process-billing` es el puente.
- **Event Mesh = Kafka + Strimzi** (decidido tras un spike que descartó Apache EventMesh: sin SDK Python, control plane eliminado en `develop`, sin schema registry ni catálogo vivo).
  - **Data plane:** 2 clústeres Kafka (KRaft, 1 broker c/u): `billing` (núcleo) y `dominios` (otros dominios), unidos con **MirrorMaker 2**. Eventos en CloudEvents JSON sobre `voltera.eventos` (clave `facturaId`).
  - **Control plane:** CRDs de Strimzi (Kafka, KafkaTopic, KafkaMirrorMaker2) + **Apicurio Schema Registry** + catálogo **AsyncAPI** (`mesh/asyncapi.yaml`).
  - Un **consumidor nuevo de reportes** en el clúster `dominios` demuestra que se suma sin tocar lo existente.
  - EventBridge queda solo para el disparo del cierre. Observabilidad: CloudWatch y X-Ray, con Grafana local.
  - Todo evento lleva `cicloId` + `facturaId` (correlación).

## 2. Arquitectura (resumen del flujo)

1. EventBridge (regla / disparo manual) → `ms-orchestrator-billing` (Lambda).
2. Orchestrator lee las transacciones preprocesadas de DynamoDB y las escribe en una **tabla outbox** (DynamoDB).
3. DynamoDB Streams → Lambda *relay* (outbox) → publica `ConsumoFacturablePreparado` en Kafka. (EventBridge Pipes no tiene Kafka como destino, por eso Streams + Lambda.)
4. `ms-process-billing` (KEDA, 1..n) consume Kafka, deduplica (escritura condicional en DynamoDB), arma la transacción y la publica en SQS.
5. SQS → *event source mapping* → Step Functions → `ms-tarifas` → `ms-calculo-consumo-neto` → `ms-facturacion`. DLQ propia.
6. `FacturaEmitida` → SQS de comprobantes → `ms-comprobante-factura`. DLQ propia.
7. Todos los pasos publican su evento al Event Mesh (Kafka `voltera.eventos`); `process-billing` lo consume para emitir `ProcesoDeFacturacionCompletado` / `Fallido`.

**Pendiente de decidir [POR CONFIRMAR]:** Step Functions Standard vs. Express (con ≤10 ejecuciones el costo no pesa; se deja Standard por trazabilidad visual y se documenta que a escala real Express sería más barato).

## 3. Parámetros

| Parámetro | Valor inicial |
|---|---|
| `N_SOLICITUDES` | 10 (configurable) |
| Retardo simulado por mensaje en `process-billing` (Exp. 1) | 5 s **[POR CONFIRMAR]** |
| KEDA `lagThreshold` | 2 **[POR CONFIRMAR]** |
| Réplicas `process-billing` | min 1, max 5 |
| Particiones del tópico Kafka | ≥ 5 (≥ max réplicas) |
| SLA del lote (Exp. 1) | 10 facturas en ≤ 2 min **[POR CONFIRMAR]** |
| Step Functions `Retry` | 3 intentos, intervalo 2 s, backoff ×2 **[POR CONFIRMAR]** |
| SQS `maxReceiveCount` | 3 **[POR CONFIRMAR]** |

## 4. Experimentos

### Exp. 1 — Absorción del pico de fin de mes (auto-escalado)
- **Patrones:** Queue-Based Load Leveling, Competing Consumers, Event-driven Autoscaling.
- **Hipótesis:** EventBridge dispara el cierre y se inyectan N transacciones en Kafka. KEDA escala `ms-process-billing` de 1 a n según el lag, drena el backlog dentro de la ventana objetivo y vuelve a 1 réplica al vaciarse, sin intervención manual.
- **Cómo se fuerza el backlog:** retardo simulado por mensaje (y/o `lagThreshold` bajo), porque con ≤10 mensajes no se acumula cola por sí solo.
- **Se mide:** crecimiento y drenaje ordenado del lag; tiempo del lote vs. SLA; réplicas suben con el lag y bajan al estabilizarse; cero transacciones perdidas por saturación; (opcional) concurrencia de Lambdas/Step Functions para ubicar el cuello de botella.
- **No valida:** capacidad real a millones. Limitación documentada.

### Exp. 2 — Caída de un dependiente sin detener el negocio (aislamiento)
- **Patrones:** Asynchronous Messaging, Bulkhead, Dead Letter Queue, Retry with backoff.
- **Hipótesis:** si se degrada un dependiente, las transacciones afectadas se reintentan y, al agotar reintentos, caen a la DLQ; el resto del flujo sigue y Kafka/`process-billing` siguen encolando. Al recuperarse el servicio, la DLQ se reprocesa.
- **Inyección de fallo:** variable de entorno que hace fallar la Lambda, o concurrencia reservada en 0. Dos casos: (a) `ms-tarifas` (dependiente interno); (b) `ms-comprobante-factura` (simula al tercero, por ejemplo el proveedor de correo).
- **Bulkhead concreto:** colas separadas (flujo principal vs. comprobantes) y concurrencia reservada por Lambda.
- **Se mide:** fallos aislados en DLQ; backlog sigue acumulándose; reproceso exitoso de la DLQ (SQS redrive); un endpoint de salud dummy como referencia de "servicios en línea" (no hay tiempo real real en esta fase).

### Exp. 3 — Cero pérdida de solicitudes ante fallos
- **Patrones:** Durable Messaging, At-least-once Delivery, Idempotency/Deduplication, Transactional Outbox.
- **Hipótesis:** si un consumidor muere a mitad de procesamiento, los mensajes no confirmados permanecen en Kafka/SQS y se reentregan; la deduplicación y las claves de idempotencia evitan facturas duplicadas.
- **Idempotencia en tres puntos:** `process-billing` (dedup de ingreso), `ms-facturacion` (escritura condicional por `facturaId`, por los reintentos de Step Functions) y `ms-comprobante-factura` (por la entrega repetida de SQS).
- **Outbox:** en el orchestrator (tabla outbox + Streams + relay), para evitar el *dual write* DynamoDB/Kafka.
- **Cómo se induce el fallo:** eliminar el pod de `process-billing` con mensajes en vuelo; reiniciar/fallar `ms-comprobante-factura` a mitad.
- **Se mide:** ecuación de conservación **inyectadas = facturas emitidas + mensajes en DLQ**; mensajes en vuelo reentregados tras el reinicio; cero facturas duplicadas; no procesables terminan en DLQ.

### Exp. 4 — Event Mesh (observabilidad y contexto de eventos) *(nuevo)*
- **Hipótesis:** el Event Mesh registra todos los eventos con su correlación, permite reconstruir el recorrido de cada factura, enruta entre brokers y gobierna el contrato de eventos.
- **Se mide:**
  - Cada evento queda en el mesh con `cicloId` y `facturaId` (completitud: eventos esperados vs. recibidos).
  - Se reconstruye la línea de tiempo completa de una factura a partir del mesh.
  - Replay por offset sobre `voltera.eventos` reproduce eventos sin efectos duplicados.
  - MirrorMaker 2 replica los eventos de `billing` a `dominios`, y el consumidor de reportes los recibe sin cambios en los servicios existentes.
  - Los eventos validan contra el esquema del registro (Apicurio) y están descritos en el catálogo AsyncAPI; un evento inválido se rechaza o se detecta.
  - Trazas X-Ray / dashboard de CloudWatch muestran el estado del ciclo en vivo.

## 5. Limitaciones documentadas
- Escala ≤10 solicitudes: valida comportamiento, no capacidad.
- Sin DIAN ni tercero real; el tercero se simula con fallos inyectados.
- Sin servicios de tiempo real; "no frenar el tiempo real" se aproxima con un endpoint dummy y el aislamiento por colas y concurrencia.
- Lectura de consumo desde DynamoDB aislada: no demuestra por sí sola ausencia de impacto en medición.

## 6. Entregables de arquitectura
- Diagrama AWS en `voltera_arquitectura_aws.drawio` (raíz del proyecto): íconos oficiales AWS (`mxgraph.aws4`), líneas ortogonales a 90°, mínimos cruces. Se actualiza a medida que se implementa.
- Código nuevo en esta carpeta; el anterior está en `_legacy/`.
