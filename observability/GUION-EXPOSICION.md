# Guion de exposición — Experimentación 2 (Voltera)

Tres guiones de 6 a 8 minutos, uno por experimento, para grabar sobre los dashboards `exp1-absorcion-pico`, `exp2-caida-dependiente` y `exp3-cero-perdida` (carpeta "Voltera Exp2" en Grafana).

## Antes de grabar (común)
- Grafana en `http://localhost:3000`, pantalla completa (tecla `d` + `k` activa el modo kiosco), refresh de 5 s y rango de 15 min ya vienen por defecto. Navegador al 100 % o 125 %.
- CloudWatch publica con 1 a 2 minutos de retraso: lo que se dispara en el segundo 0 se ve en pantalla hacia el minuto 1-2. Narra con calma en ese hueco (el guion lo prevé) o graba la corrida y sincroniza después.
- Las métricas de la aplicación no llevan `cicloId`: se acota con el rango de tiempo. Haz **una corrida limpia por experimento** (ventana de 15 min sin otras corridas).
- Las líneas verticales "Pico inyectado", "Fallo inyectado" y "Recuperación" salen de la métrica `FaseExperimento` (namespace `Voltera/Exp2`, dimensiones `experimento` = `exp1|exp2|exp3` y `fase` = `pico_inyectado|fallo_inyectado|recuperacion`, valor 1, el runner la publica). **Pendiente de verificar en Grafana real** que la anotación se dibuje (usa la fuente "-- Dashboard --" sobre los paneles de la fila final "Fuente de anotaciones", que no se explican en cámara; si no se dibuja, esos paneles muestran igualmente los instantes).
- Orden de lectura en los tres tableros: fila superior de números grandes (izquierda a derecha), luego los gráficos de arriba-izquierda a abajo-derecha. En los gráficos de series el eje X siempre es la hora local; el eje Y está rotulado en cada gráfico.

---

# Experimento 1 — Absorción del pico de fin de mes

**Dashboard:** `Exp1 - Absorcion del pico (autoescalado)` · **Duración:** 7 min

## 1. Hipótesis y criterio (1 min)
- **Hipótesis:** al cierre de mes llega una ráfaga de consumos. La cola (Kafka) la absorbe, KEDA escala `ms-process-billing` de 1 a 5 réplicas según el lag, el backlog se drena dentro del SLA y el sistema vuelve a 1 réplica solo.
- **Criterio de aceptación:** tiempo del lote ≤ 120 s, cero pérdidas por saturación, réplicas de vuelta a 1.
- **Alcance:** valida comportamiento con N de 10 a 200, no capacidad a millones.

## 2. Mapa del flujo (1 min)
EventBridge → `ms-orchestrator-billing` → tabla outbox → Streams → relay → **Kafka** (`voltera.consumo-facturable-preparado`, 5 particiones) → **`ms-process-billing`** (KEDA 1..5) → SQS → Step Functions → tarifas, cálculo, facturación. Señala en el diagrama el tramo Kafka → `process-billing`: es donde se forma y se drena el backlog.

## 3. Estado inicial (30 s)
Tablero en reposo: números en 0 o sin datos, 1 réplica, lag en 0. Di: "un pod, cola vacía, ninguna factura".

## 4. Disparo (30 s)
`python -m runner exp1 --n 100` (o `--n 200`; el retardo simulado de 2 s por mensaje fuerza el backlog). Aparece la anotación naranja "Pico inyectado".

## 5. Narración gráfico por gráfico (3 min)

| # | Gráfico (posición) | Eje X / eje Y | Qué decir | Patrón de arquitectura |
|---|---|---|---|---|
| 1 | **Tiempo del lote en segundos (SLA: 120 s)** — stat, arriba izquierda | Un valor, en segundos | "Es la nota final: cuánto tardó el lote. Verde si ≤ 120 s, rojo si no." Se llena al final, con el retraso de CloudWatch. | SLA de cierre de ciclo / criterio del ASR |
| 2 | **Réplicas escaladas (pico)** — stat, arriba centro | Un valor, número de pods (máximo del rango) | "Pasamos de 1 pod a 5 sin que nadie interviniera." | Autoescalado por evento (KEDA) |
| 3 | **Mensajes pendientes al llegar el pico (máximo)** — stat, arriba derecha | Un valor, mensajes (lag máximo) | "Este es el tamaño del pico que tuvo que absorber la cola." | Queue-Based Load Leveling |
| 4 | **Pendientes por procesar (lag) y réplicas que escalan** — serie ancha | X: hora. Y izquierdo: mensajes pendientes. Y derecho: réplicas (línea naranja gruesa) | "La anotación marca el pico: el lag salta de golpe. Unos 35 s después las réplicas suben 1, 4, 5. Mientras hay 5, el lag baja en rampa hasta 0, y luego las réplicas vuelven a 1." | Queue-Based Load Leveling + Competing Consumers + autoescalado por evento (lagThreshold 2). Lag = `KafkaConsumerLag` Sum/6 |
| 5 | **Facturas emitidas acumuladas (el lote avanza)** — serie, abajo izquierda | X: hora. Y: facturas acumuladas | "Dos curvas: la meta (inyectadas) y las emitidas. El punto donde la segunda alcanza a la primera es el fin del lote." | Cero pérdida por saturación (durable messaging) |
| 6 | **Tiempo por mensaje en segundos (total y sobrecosto)** — serie, abajo derecha | X: hora. Y: segundos por mensaje | "El total ronda el retardo simulado de 2 s; el sobrecosto es lo que añade nuestra mensajería (claim, SQS, commit) y debe ser pequeño. Si el lote se pasó del SLA, esta curva nos dice que la demora no viene del servicio sino del escalado y del reparto de claves entre particiones." | Medición del costo de la mensajería durable |

## 6. Veredicto (30 s)
Lee el número 1. Con los datos reales de la sesión del 2026-10-10: N=10 → **65,1 s PASS**; N=100 → **149,8 s FAIL**; N=200 → 199 de 200 en 176 s (no concluyente). Escalado correcto 1→4→5 en ~35 s, lag a 0, réplicas a 1, DLQ en 0. Si en la grabación el número 1 queda rojo, dilo tal cual: el patrón funciona pero el rendimiento por réplica (≈ 1,1 mensajes/s con 5 pods, esperado ≈ 2,5) no alcanza el SLA para N grande.

## 7. Qué demuestra y qué no (30 s)
- **Demuestra:** la cola desacopla la ráfaga del consumo; KEDA escala y des-escala solo; no se pierde nada al saturar.
- **No demuestra:** capacidad real (millones), ni que el SLA se cumpla a cualquier N sin ajustar particiones, retardo y réplicas; el sobrecosto de reparto desigual y de rebalanceos sigue sin cuantificarse del todo.

---

# Experimento 2 — Caída de un dependiente sin detener el negocio

**Dashboard:** `Exp2 - Caida de un dependiente (aislamiento)` · **Duración:** 8 min

## 1. Hipótesis y criterio (1 min)
- **Hipótesis:** si se degrada un dependiente (caso a: `ms-tarifas`; caso b: `ms-comprobante-factura`, que simula al tercero), las transacciones afectadas se reintentan y, al agotar reintentos, caen a la DLQ. El resto del flujo sigue y el ingreso sigue encolando. Al recuperarse, la DLQ se reprocesa.
- **Criterio:** facturas emitidas siguen subiendo durante el fallo; lo fallido queda en DLQ (no se pierde); tras el redrive la DLQ vuelve a 0; el ingreso permanece en línea.

## 2. Mapa del flujo (1 min)
Kafka → `process-billing` → **cola de transacciones** → Pipe → **Step Functions** (Retry ×3, backoff ×2, Catch → DLQ) → tarifas → cálculo → facturación → **cola de comprobantes** → `ms-comprobante-factura`. Señala los dos bulkheads: colas separadas y concurrencia por Lambda.

## 3. Estado inicial (30 s)
DLQ en 0, "EN LINEA" en verde, facturas emitidas en 0 o plano, colas vacías.

## 4. Disparo (1 min)
`python -m runner exp2 --case b` (o `a`). El runner inyecta el fallo (`FORCE_FAIL=true` o concurrencia reservada 0): anotación roja "Fallo inyectado". Más adelante restaura el servicio y ejecuta el redrive: anotación verde "Recuperación".

## 5. Narración gráfico por gráfico (4 min)

| # | Gráfico (posición) | Eje X / eje Y | Qué decir | Patrón de arquitectura |
|---|---|---|---|---|
| 1 | **Mensajes atascados en DLQ (lo que falló de verdad)** — stat, arriba izquierda | Un valor, mensajes (DLQ transacciones + DLQ comprobantes) | "Empieza en 0. Cuando se agotan los reintentos sube: es lo que realmente falló, apartado sin perderse." | Dead Letter Queue |
| 2 | **Facturas emitidas (siguen subiendo)** — stat, arriba centro | Un valor, facturas en el rango | "El contador no se congela por el fallo: el negocio sigue." | Bulkhead |
| 3 | **Servicios en línea (ms-process-billing)** — stat, arriba derecha | EN LINEA / CAIDO | "El ingreso nunca se cayó: no depende del dependiente degradado." | Mensajería asíncrona (desacople productor/consumidor) |
| 4 | **Cola y DLQ del dependiente caído** — serie, izquierda | X: hora. Y: mensajes en cola | "Tras la línea roja, la cola del dependiente (o la DLQ de transacciones en el caso a) crece. Tras la línea verde baja a 0: eso es el redrive." | Queue-Based Load Leveling + Retry con backoff + DLQ |
| 5 | **Facturas emitidas y notificadas (acumulado)** — serie, derecha | X: hora. Y: facturas acumuladas | "Emitidas sigue subiendo durante el fallo. Notificadas se aplana si cae el comprobante y alcanza a emitidas después de la recuperación." | Bulkhead + desacople por cola (emitir no espera a notificar) |
| 6 | **Errores de Step Functions y reintentos** — serie ancha, abajo | X: hora. Y: eventos por minuto | "Los errores de Lambda son los reintentos del backoff. Las ejecuciones 'fallidas' casi no se mueven porque el Catch manda a la DLQ y la ejecución termina bien: el fallo quedó contenido." | Retry con backoff + Catch → DLQ en la orquestación (Step Functions) |

## 6. Veredicto (30 s)
Cumple si: (1) el número 2 siguió subiendo con el fallo activo, (2) el número 1 pasó por valores > 0 y terminó en 0 tras la recuperación, (3) el número 3 nunca marcó CAIDO. Caso b: con `maxReceiveCount` 3 y visibility timeout 180 s tarda ≥ 9 min en llegar a DLQ; usa el valor reducido (~40 s) de `experiment.tfvars.example` para que quepa en la grabación.

## 7. Qué demuestra y qué no (30 s)
- **Demuestra:** aislamiento de fallos, apartado en DLQ sin pérdida, y reproceso tras recuperar.
- **No demuestra:** protección de servicios de tiempo real (se aproxima con el salud del ingreso y colas separadas) ni comportamiento ante un tercero real; "servicios en línea" es la salud de `process-billing`, no un endpoint de tiempo real.

---

# Experimento 3 — Cero pérdida de solicitudes ante fallos

**Dashboard:** `Exp3 - Cero perdida de solicitudes` · **Duración:** 8 min

## 1. Hipótesis y criterio (1 min)
- **Hipótesis:** si un consumidor muere a mitad de proceso, los mensajes no confirmados se reentregan y la idempotencia evita facturas duplicadas.
- **Criterio (ecuación de conservación):** `inyectadas = emitidas + rechazadas por negocio + en DLQ`, saldo final 0, cero facturas duplicadas.

## 2. Mapa del flujo (1 min)
Orchestrator → **outbox** (DynamoDB) → Streams → relay → Kafka → **`process-billing`** (dedup de ingreso) → SQS → Step Functions → **`ms-facturacion`** (idempotencia por factura) → cola de comprobantes → **`ms-comprobante-factura`** (idempotencia por entrega). Marca las tres capas de idempotencia y el outbox.

## 3. Estado inicial (30 s)
Todo en 0; SALDO en verde con 0.

## 4. Disparo (1 min)
`python -m runner exp3` (borra el pod de `process-billing` con mensajes en vuelo y falla `ms-comprobante-factura` a mitad). Anotación roja "Fallo inyectado (pod muerto)" y, al restaurar, verde "Recuperación".

## 5. Narración gráfico por gráfico (4 min)

| # | Gráfico (posición) | Eje X / eje Y | Qué decir | Patrón de arquitectura |
|---|---|---|---|---|
| 1 | **Solicitudes inyectadas** — stat, arriba izquierda | Un valor, solicitudes | "Lado izquierdo de la ecuación: lo que entró." | Transactional Outbox |
| 2 | **Emitidas + rechazadas + en DLQ** — stat, arriba centro-izq. | Un valor, solicitudes | "Lado derecho: todo lo que terminó en algún estado final conocido." | At-least-once + DLQ (conservación) |
| 3 | **SALDO (inyectadas − contabilizadas)** — stat grande, arriba centro-der. | Un valor; 0 = verde | "Este es el veredicto en un número. Se pone naranja mientras hay trabajo en vuelo y debe volver a 0." | Verificación de cero pérdida |
| 4 | **Ciclos y facturas reconciliados** — stat, arriba derecha | Cuatro valores (completados, fallidos, reconciliados, facturas reconciliadas) | "Completado sube al cerrar el ciclo, fallidos debe ser 0. Reconciliados > 0 significa que se perdió un evento de estado y la reconciliación contra DynamoDB cerró el ciclo: se perdió información de observación, no una factura." | Reconciliación / compensación periódica |
| 5 | **Conservación en el tiempo: inyectadas vs contabilizadas** — serie, abajo izquierda | X: hora. Y: solicitudes acumuladas | "Las dos curvas se separan durante el fallo y se vuelven a juntar. Una separación que no cierra sería una pérdida." | Durable Messaging (Kafka/SQS) + outbox |
| 6 | **Reintentos, duplicados descartados y replays** — serie, abajo derecha | X: hora. Y: eventos por minuto | "Tras la línea roja aparecen reenvíos y duplicados: el sistema entrega más de una vez, pero cada duplicado se descarta o se repite sin re-emitir. Por eso el saldo sigue en 0." | At-least-once + consumidor idempotente (dedup de ingreso, idempotencia en facturación y comprobante) |

## 6. Veredicto (30 s)
Aprobado si: número 3 en 0 y verde al final, número 4 con "ciclos fallidos" = 0, y el gráfico 6 mostró reentregas o replays (prueba de que el fallo realmente ocurrió). Hallazgo conocido: en la prueba de N=200 una factura se procesó de punta a punta pero su evento de estado se perdió; el ciclo quedó EN_CURSO. La reconciliación (`CiclosReconciliados`, `FacturasReconciliadas`) está diseñada para cerrar ese caso; si en la grabación no aparece, el número 4 lo evidencia.

## 7. Qué demuestra y qué no (30 s)
- **Demuestra:** no se pierde ninguna solicitud ante la muerte de un consumidor, y los reintentos no duplican facturas.
- **No demuestra:** tolerancia a la pérdida de un broker (Kafka corre con 1 broker, factor de replicación 1), ni ausencia de pérdidas de eventos de observabilidad (publicación al mesh best-effort), ni escala real.

---

## Referencia rápida de métricas
`Voltera/Exp2` (dim `service`): `UnidadesEnOutbox`, `FacturasEmitidas`, `FacturasNotificadas`, `TarifasRechazadas`, `CalculosRechazados`, `EmisionesRechazadas`, `NotificacionesFallidas`, `MensajesReenviados`, `MensajesDuplicados`, `IdempotenciaReplays`, `HealthCheckOk` (+`pod`), `KafkaConsumerLag` (+`topic`; se grafica como Sum/6), `MensajeTotalMs`, `MensajeSobrecostoMs`, `CicloDuracionSegundos`, `CiclosCompletados`, `CiclosFallidos`, **`CiclosReconciliados`** y **`FacturasReconciliadas`** (service=`ms-process-billing`, nuevas). `FaseExperimento` (dim `experimento` y `fase`). AWS: SQS, Step Functions, Lambda, ContainerInsights (`service_number_of_running_pods`).
