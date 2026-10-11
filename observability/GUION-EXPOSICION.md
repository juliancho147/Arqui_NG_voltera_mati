# Guion de exposición — Experimentación 2 (Voltera)

Dos guiones de 6 a 8 minutos (Exp. 1 y Exp. 2 unificado) para grabar sobre los dashboards `exp1-absorcion-pico` y `exp2-resiliencia` (los antiguos Exp. 2 y Exp. 3 se unieron; sus JSON están en `dashboards/_legacy/` y solo se regeneran con `--legacy`) (carpeta "Voltera Exp2" en Grafana).

## Antes de grabar (común)
- Grafana en `http://localhost:3000`, pantalla completa (tecla `d` + `k` activa el modo kiosco), refresh de 5 s y rango de 15 min ya vienen por defecto. Navegador al 100 % o 125 %.
- CloudWatch publica con 1 a 2 minutos de retraso: lo que se dispara en el segundo 0 se ve en pantalla hacia el minuto 1-2. Narra con calma en ese hueco (el guion lo prevé) o graba la corrida y sincroniza después.
- Las métricas de la aplicación no llevan `cicloId`: se acota con el rango de tiempo. Haz **una corrida limpia por experimento** (ventana de 15 min sin otras corridas).
- Las líneas verticales de fase salen de la métrica `FaseExperimento` (namespace `Voltera/Exp2`, dimensiones `experimento` = `exp1|exp2` y `fase`, valor 1, la publica el runner). Exp1: `disparo`. Exp2: `estado_inicial`, `disparo`, `fallo_dependiente`, `fallo_pod`, `fallo_lambda`, `duplicados`, `recuperacion` (colores distintos). **Pendiente de verificar en Grafana real** que la anotación se dibuje (usa la fuente "-- Dashboard --" sobre los paneles de la fila final "Fuente de anotaciones", que no se explican en cámara; si no se dibuja, esos paneles muestran igualmente los instantes).
- Orden de lectura en los dos tableros: fila superior de números grandes (izquierda a derecha), luego los gráficos de arriba-izquierda a abajo-derecha. En los gráficos de series el eje X siempre es la hora local; el eje Y está rotulado en cada gráfico.

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
`python -m runner exp1 --n 100` (o `--n 200`; el retardo simulado de 2 s por mensaje fuerza el backlog). Aparece la anotación naranja "Disparo".

## 5. Narración gráfico por gráfico (3 min)

| # | Gráfico (posición) | Eje X / eje Y | Qué decir | Patrón de arquitectura |
|---|---|---|---|---|
| 1 | **Tiempo del lote en segundos (SLA: 120 s)** — stat, arriba izquierda | Un valor, en segundos | "Es la nota final: cuánto tardó el lote. Verde si ≤ 120 s, rojo si no." Se llena al final, con el retraso de CloudWatch. | SLA de cierre de ciclo / criterio del ASR |
| 2 | **Réplicas escaladas (pico)** — stat, arriba centro | Un valor, número de pods (máximo del rango) | "Pasamos de 1 pod a 5 sin que nadie interviniera." | Autoescalado por evento (KEDA) |
| 3 | **Mensajes pendientes al llegar el pico (máximo)** — stat, arriba derecha | Un valor, mensajes (lag máximo) | "Este es el tamaño del pico que tuvo que absorber la cola." | Queue-Based Load Leveling |
| 4 | **Pendientes por procesar (lag) y réplicas que escalan** — serie ancha | X: hora. Y izquierdo: mensajes pendientes. Y derecho: réplicas (línea naranja gruesa) | "La anotación marca el disparo: el lag salta de golpe. Unos 35 s después las réplicas suben 1, 4, 5. Mientras hay 5, el lag baja en rampa hasta 0, y luego las réplicas vuelven a 1." | Queue-Based Load Leveling + Competing Consumers + autoescalado por evento (lagThreshold 2). Lag = `KafkaConsumerLag` Sum/6 |
| 5 | **Facturas emitidas acumuladas (el lote avanza)** — serie, abajo izquierda | X: hora. Y: facturas acumuladas | "Dos curvas: la meta (inyectadas) y las emitidas. El punto donde la segunda alcanza a la primera es el fin del lote." | Cero pérdida por saturación (durable messaging) |
| 6 | **Tiempo por mensaje en segundos (total y sobrecosto)** — serie, abajo derecha | X: hora. Y: segundos por mensaje | "El total ronda el retardo simulado de 2 s; el sobrecosto es lo que añade nuestra mensajería (claim, SQS, commit) y debe ser pequeño. Si el lote se pasó del SLA, esta curva nos dice que la demora no viene del servicio sino del escalado y del reparto de claves entre particiones." | Medición del costo de la mensajería durable |

## 6. Veredicto (30 s)
Lee el número 1. Con los datos reales de la sesión del 2026-10-10: N=10 → **65,1 s PASS**; N=100 → **149,8 s FAIL**; N=200 → 199 de 200 en 176 s (no concluyente). Escalado correcto 1→4→5 en ~35 s, lag a 0, réplicas a 1, DLQ en 0. Si en la grabación el número 1 queda rojo, dilo tal cual: el patrón funciona pero el rendimiento por réplica (≈ 1,1 mensajes/s con 5 pods, esperado ≈ 2,5) no alcanza el SLA para N grande.

## 7. Qué demuestra y qué no (30 s)
- **Demuestra:** la cola desacopla la ráfaga del consumo; KEDA escala y des-escala solo; no se pierde nada al saturar.
- **No demuestra:** capacidad real (millones), ni que el SLA se cumpla a cualquier N sin ajustar particiones, retardo y réplicas; el sobrecosto de reparto desigual y de rebalanceos sigue sin cuantificarse del todo.

---

# Experimento 2 — Resiliencia ante fallos (aislamiento + cero pérdida)

**Dashboard:** `Exp2 - Resiliencia ante fallos` (uid `voltera-exp2-resiliencia`, http://localhost:3000/d/voltera-exp2-resiliencia) · **Duración:** 8 min

Un solo escenario, un solo tablero. Une los antiguos Exp. 2 (caída de un dependiente) y Exp. 3 (cero pérdida): se inyectan, uno tras otro, una caída de dependiente, la muerte de pods, una falla de Lambda y duplicados a propósito, y se demuestra que el ingreso no se cae y que el saldo vuelve a 0.

## 1. Hipótesis y criterio (1 min)
- **Hipótesis:** ante fallos de distinto tipo, `ms-process-billing` (el ingreso) sigue en línea, lo que no se puede procesar se reintenta y luego se aparta en DLQ, los mensajes no confirmados se reentregan y los duplicados no generan facturas repetidas.
- **Criterio (ecuación de conservación):** `inyectadas = emitidas + rechazadas por negocio + en DLQ`; saldo final 0; ingreso EN LINEA todo el tiempo; facturas emitidas sin duplicados.

## 2. Mapa del flujo (30 s)
Orchestrator → outbox → relay → Kafka → **`ms-process-billing`** → cola de transacciones → Step Functions (Retry ×3, backoff, Catch → DLQ) → tarifas → cálculo → **`ms-facturacion`** → cola de comprobantes → **`ms-comprobante-factura`**. Señala los bulkheads (colas separadas, Lambdas independientes) y las capas de idempotencia.

## 3. Fases en orden (el runner las publica como `FaseExperimento`; cada una es una línea vertical de color)

| # | Fase (color) | Qué ocurre | Qué narrar | Qué mirar |
|---|---|---|---|---|
| 1 | `estado_inicial` (gris) | Todo en reposo | "Ingreso en línea, saldo 0, colas vacías." | Stats: EN LINEA verde, errores 0, SALDO 0 verde |
| 2 | `disparo` (naranja) | Se inyecta el lote | "Entran las facturas; el outbox las registra antes de publicarlas." | Stat de emitidas empieza a subir; gráfico A |
| 3 | `fallo_dependiente` (rojo) | Cae `ms-comprobante-factura` (o `ms-tarifas` en el caso A) | "Un dependiente cae: sus errores suben, pero el ingreso sigue en línea y se siguen emitiendo facturas. Emitir no espera a notificar." | Stat 2 (errores) en rojo; gráfico A (notificadas se aplana, emitidas sigue); gráfico B (crece la cola o DLQ del caído) |
| 4 | `fallo_pod` (morado) | Se matan pods de `ms-process-billing` | "Matamos pods en pleno proceso: Kubernetes los repone y Kafka reentrega lo que no se confirmó." | Gráfico C (pods bajan y suben; `MensajesReenviados` > 0); stat 1 sigue EN LINEA |
| 5 | `fallo_lambda` (amarillo) | `FAIL_RATE` en `ms-facturacion` | "Una de cada cuatro invocaciones falla: Retry con backoff y, si se agota, DLQ." | Gráfico E (errores de Lambda; Step Functions casi plano); gráfico B |
| 6 | `duplicados` (azul) | Se reenvían copias a propósito por SQS y Kafka | "Entregamos todo dos veces a propósito. Los contadores de duplicados suben, pero las facturas emitidas no se repiten." | Gráfico D (única fase donde `MensajesDuplicados` e `IdempotenciaReplays` > 0); SALDO sigue en 0 |
| 7 | `recuperacion` (verde) | Se restaura el servicio y se hace redrive | "Todo vuelve: las colas se drenan, notificadas alcanza a emitidas, la DLQ queda en 0." | Gráfico B a 0; gráfico A (curvas juntas); SALDO 0 verde |

Disparo: `python -m runner demo exp2` (o `python -m runner exp2 --case b|a`).

## 3b. Cómo narrar el "Estado de los servicios en el tiempo" (protagonista, ancho completo bajo los stats)
State timeline: una fila por servicio (`ms-process-billing`, `ms-tarifas`, `ms-calculo-consumo-neto`, `ms-facturacion`, `ms-comprobante-factura`), eje X = hora; verde OK, amarillo DEGRADADO, rojo OFF. Narra con el cursor sobre la línea de tiempo: "en este minuto el servicio está OK y en el siguiente está OFF".
1. Primero todo verde (`estado_inicial`, `disparo`).
2. `fallo_dependiente`: la fila de `ms-comprobante-factura` pasa a rojo OFF; las demás siguen verdes ("el fallo queda aislado").
3. `fallo_lambda`: `ms-facturacion` pasa a amarillo DEGRADADO (falla una parte de las invocaciones, no todas).
4. `fallo_pod`: `ms-process-billing` pasa a amarillo DEGRADADO (menos pods o reentregas) pero nunca rojo: el ingreso no se cae.
5. `recuperacion`: todas las filas vuelven a verde.
Derivación: Lambdas con `Errors`/`Invocations`/`Throttles` por minuto (sin invocaciones = OK). `ms-process-billing`: OFF con 0 pods o `HealthCheckOk`=0; DEGRADADO si los pods bajan respecto al minuto anterior o hay `MensajesReenviados`>0. Límite: no hay métrica de pods esperados, así que un escalado KEDA hacia abajo también se vería amarillo; métrica mínima propuesta: `PodsEsperados` (gauge) en `ms-process-billing`. Las anotaciones de fase sobre este panel están sin verificar en Grafana real.

## 4. Lectura del tablero (orden: arriba-izquierda a abajo-derecha)

| # | Panel | Eje X / eje Y | Patrón de arquitectura |
|---|---|---|---|
| 1 | **ms-process-billing: el ingreso, no se cae** (stat EN LINEA/CAIDO) | Un valor | Bulkhead / mensajería asíncrona |
| 2 | **Servicio que se cae: errores por minuto** (stat) | Un valor, errores/min de `ms-comprobante-factura` y `ms-tarifas` | Bulkhead + Retry con backoff |
| 3 | **Facturas emitidas por ms-facturacion** (stat) | Un valor | Bulkhead + Outbox |
| 4 | **SALDO de conservación** (stat grande, verde en 0) | Un valor: inyectadas − (emitidas + rechazadas + DLQ) | DLQ + Idempotencia + Outbox |
| T | **Estado de los servicios en el tiempo** (state timeline, 24 col.) | X: hora. Y: un servicio por fila (OK/DEGRADADO/OFF) | Bulkhead (aislamiento visible) |
| A | **Emitidas vs notificadas (acumuladas)** | X: hora. Y: facturas acumuladas | Desacople por cola |
| B | **DLQ: mensajes apartados por servicio** | X: hora. Y: mensajes en cola | Retry/backoff + DLQ |
| C | **Pods de ms-process-billing y mensajes reenviados** | X: hora. Y izq.: reenvíos/min; Y der.: pods | At-least-once + réplicas |
| D | **Duplicados descartados por idempotencia** | X: hora. Y: duplicados/min | Idempotencia |
| E | **Errores de las Lambdas y de Step Functions** | X: hora. Y: errores/min | Retry + Catch → DLQ (Saga) |

## 5. Veredicto (30 s)
Aprobado si: (1) el stat 1 nunca marcó CAIDO, (2) el stat 3 siguió subiendo durante los fallos, (3) el SALDO terminó en 0 y verde, (4) el gráfico D solo se movió en la fase `duplicados` y las emitidas no se duplicaron, (5) el gráfico B terminó en 0 tras la recuperación. Caso b: con `maxReceiveCount` 3 y visibility timeout 180 s tarda ≥ 9 min en llegar a DLQ; usa el valor reducido (~40 s) de `experiment.tfvars.example`.

## 6. Qué demuestra y qué no (30 s)
- **Demuestra:** aislamiento de fallos, apartado en DLQ sin pérdida, reentrega tras la muerte de consumidores e idempotencia ante duplicados.
- **No demuestra:** tolerancia a la pérdida de un broker (Kafka con 1 broker, replicación 1), comportamiento ante un tercero real, ni escala real. "EN LINEA" es la salud de `ms-process-billing`, no un endpoint de tiempo real. Hallazgo conocido: en una prueba un evento de estado se perdió y el ciclo quedó EN_CURSO; la reconciliación (`CiclosReconciliados`) está pensada para cerrarlo.

---

## Referencia rápida de métricas
`Voltera/Exp2` (dim `service`): `UnidadesEnOutbox`, `FacturasEmitidas`, `FacturasNotificadas`, `TarifasRechazadas`, `CalculosRechazados`, `EmisionesRechazadas`, `NotificacionesFallidas`, `MensajesReenviados`, `MensajesDuplicados`, `IdempotenciaReplays`, `HealthCheckOk` (+`pod`), `KafkaConsumerLag` (+`topic`; se grafica como Sum/6), `MensajeTotalMs`, `MensajeSobrecostoMs`, `CicloDuracionSegundos`, `CiclosCompletados`, `CiclosFallidos`, **`CiclosReconciliados`** y **`FacturasReconciliadas`** (service=`ms-process-billing`, nuevas). `FaseExperimento` (dim `experimento` y `fase`). AWS: SQS, Step Functions, Lambda, ContainerInsights (`service_number_of_running_pods`).
