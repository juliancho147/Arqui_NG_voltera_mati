# Bitácora de pruebas — Experimentación 2 (facturación dirigida por eventos)

> **Segunda tanda (grabación de Exp. 1, 2 y 3; el 2 y el 3 se unieron, ver la nota siguiente):** los registros nuevos se agregan abajo, en "Tanda de grabación". La sesión del 2026-10-10 se conserva más abajo como **sesión de diagnóstico** (referencia: arrancó con el rendimiento de 1,1 mensajes/s y el evento de estado perdido).

## Nota (2026-10-11) — Unión de los antiguos Exp. 2 y Exp. 3 en un solo "Exp. 2 — Resiliencia ante fallos (aislamiento + cero pérdida)"

Decisión del usuario: los experimentos "Caída de un dependiente" (antiguo Exp. 2) y "Cero pérdida" (antiguo Exp. 3) se ejecutan ahora como **un solo escenario** con una sola vista de Grafana (`voltera-exp2-aislamiento`). El Exp. 1 (absorción) no cambia. Las pruebas 3 (antiguo Exp. 2, caso B, N = 200) y 4 (antiguo Exp. 3, N = 300) de más abajo se **conservan tal cual**: son registros del diseño anterior y siguen siendo válidos como tales; no se reescriben.

- **Fases del nuevo Exp. 2** (métrica `FaseExperimento`, `Voltera/Exp2`, `experimento=exp2`): `estado_inicial`, `disparo`, `fallo_dependiente`, `fallo_pod`, `fallo_lambda`, `duplicados`, `recuperacion`, `veredicto`.
- **Novedad:** fase `duplicados` (por defecto 50 copias de mensajes ya enviados): por SQS a la cola de transacciones (replays de idempotencia) y por Kafka al tópico de ingreso con `kubectl exec` en el broker (duplicados descartados en process-billing). El criterio nuevo es que **emitidas == N, no N+D**.
- **Criterios del veredicto:** AISLAMIENTO, CERO PÉRDIDA (antes y después del redrive), IDEMPOTENCIA y RECUPERACIÓN (detalle en `README.md` §2).
- **Cambio de metodología respecto del antiguo Exp. 2:** el fallo del dependiente se mantiene hasta la recuperación (ya no se espera a que la DLQ de comprobantes se llene antes de restaurar); el redrive actúa sobre lo que haya en las DLQ de transacciones y comprobantes.
- **Compatibilidad:** `python3 correr.py exp=3 ...` y `python -m runner demo exp3` avisan de la unión y ejecutan el Exp. 2.
- **Estado:** el Exp. 2 unificado solo se ha verificado con pruebas locales (moto + kubectl simulado, 52 pruebas); aún no se ejecutó sobre AWS/EKS. Cuando se corra, se agregará su "Prueba n" automáticamente.

## Tanda de grabación

## Prueba 1 (grabación) — Exp. 1 absorción del pico, N = 500, retardo 0,1 s
- **Fecha/hora:** 2026-10-11 12:26:17 → ~12:28:30 (Bogotá) · **Ciclo:** `EXP-20261011172616` · **Marcas:** `reports/20261011-122616-demo-exp1/marcas.json` · **Lanzado con:** `python3 correr.py` (modo demo).
- **Estado del registro:** *reconstruido a mano desde DynamoDB y CloudWatch*; al guardar, el runner aún no había escrito `report.md` (seguía esperando en la terminal). Si se completa la ejecución, el runner agregará su propia sección con la tabla PASS/FAIL.
- **Parámetros:** N = 500, retardo simulado 0,1 s/mensaje, SLA 300 s (fijado por el usuario antes de medir), KEDA 1..5, `CONSUMER_CONCURRENCY` = 1, orquestadora con 16 hilos y timeout 300 s (corrección del incidente de N = 1500).
- **Resultado:** **500/500 facturas, ciclo `COMPLETADO`** (emitidas 500, rechazadas 0, fallidas 0), DLQ de transacciones y de comprobantes en 0. **Duración del lote: 116,6 s (SLA 300 s → cumple).** Ritmo medio ≈ 4,3 facturas/s (vs 0,5–1,7 de las sesiones anteriores).
- **Escalado:** 1 → 5 pods (visto en CloudWatch a las 12:27, con el lag máximo ≈ 96 mensajes); de vuelta a 1 pod hacia las 12:32 (≈ 3–4 min tras el fin del lote, con resolución de 1 min).
- **Hallazgos / observaciones:**
  - Los arreglos de la orquestadora (escritura paralela del outbox) resolvieron la pérdida del lote que apareció con N = 1500.
  - Con retardo 0,1 s el lag es pequeño y el escalado es poco vistoso (pico ≈ 96 mensajes); para una grabación del escalado conviene un retardo mayor (≈ 0,5 s).
  - La ventana de reducción del HPA se cambió de 300 s a 30 s **durante** esta ejecución, así que el tiempo de bajada no es una medida limpia del nuevo ajuste; falta repetir para medirlo.
- **Pendiente:** completar el reporte del runner (Enter en la terminal) o repetir; medir la bajada de pods con la ventana de 30 s; decidir el retardo definitivo para grabar.

---

## Ensayo previo a la grabación — Exp. 1, N = 100 (2026-10-11)
- **Fecha/hora:** 11:26:48 → 11:29:59 (Bogotá) · **Ciclo:** `EXP-20261011162649` · **Reporte:** `reports/20261011-113405-exp1/`
- **Parámetros:** N = 100, retardo 2 s, SLA 120 s, KEDA 1..5, imagen nueva (con reintentos de publicación, reconciliación y concurrencia por pod = 1).
- **Resultado:** **FAIL en tiempo** (188,0 s vs 120 s); 7 criterios PASS, 1 FAIL, 1 MANUAL. 100/100 facturas terminadas, DLQ en 0, cero pérdidas, réplicas 1 → 4 → 5 → 1.
- **Diagnóstico (logs de CloudWatch, 100 mensajes):** tiempo medio por mensaje 2,01 s; sobrecosto medio 89 ms (4,5 %), p50 28 ms, p99 934 ms. El código por mensaje NO es el cuello.
  - Los pods nuevos tardan ~30 s en arrancar porque el add-on de CloudWatch inyecta 4 init-containers de auto-instrumentación (java, nodejs, python, dotnet) que no se usan.
  - Entre los segundos ~15 y ~77 hubo reajustes repetidos de particiones (cooperative-sticky) mientras KEDA escalaba; los pods quedaron ociosos parte de ese tiempo (pollMs alto). Los pods procesaron 20, 9, 38, 27 y 6 mensajes: reparto muy desigual.
  - Cola: el último mensaje tardó ~40 s más (reintento de la cola de comprobantes, visibilidad 40 s).
- **Acciones derivadas:** quitar la inyección de auto-instrumentación en `ms-process-billing`; estabilizar el reparto (p. ej. membresía estática); valorar `CONSUMER_CONCURRENCY` > 1.
- **Otros hallazgos del despliegue:** Apicurio no arrancaba (Container Insights inyecta `OTEL_PROPAGATORS=xray`); corregido en el manifiesto. Credenciales de Grafana mal escritas (clave y secreto en la misma línea); corregido.

---

## Incidente — Exp. 1, N = 1500 (2026-10-11 11:53) · prueba INVÁLIDA
- **Ciclo:** `EXP-20261011165256` · **Reporte:** `reports/20261011-115256-demo-exp1/` (solo `marcas.json`).
- **Qué pasó:** el lote se detuvo en 1.299 facturas terminadas de 1.500 y el ciclo pasó a `FALLIDO` por timeout (600 s). DLQ en 0 y Step Functions sin fallos: no hubo pérdida en el flujo, **faltaban mensajes de entrada**.
- **Causa raíz:** la Lambda `ms-orchestrator-billing` (timeout 30 s) escribía las 1.500 filas del outbox con `PutItem` secuenciales. Se agotó (3 intentos con `status: timeout`) tras escribir 1.308, y a Kafka solo llegaron 1.308 de 1.500 mensajes. El evento de inicio sí declaraba 1.500.
- **Evidencia:** outbox del ciclo con 1.309 filas (1.308 + inicio); offsets del tópico = 1.408 (100 del ensayo + 1.308); `DEDUP#ENVIADO` = 1.308; `idem` y Step Functions = 1.308 ejecuciones exitosas.
- **Corrección:** escrituras del outbox en paralelo (`OUTBOX_WORKERS`, 16 hilos) y timeout de la orquestadora a 300 s (`orchestrator_timeout_seconds`). Desplegado el 2026-10-11 ~12:25. Pruebas del servicio: 4 OK.
- **Lección:** el límite de 30 s no se notó hasta N > ~1.300; los ensayos con N ≤ 500 pasaban. Revisar los límites de cada Lambda al subir N.
- **Acción:** repetir el Exp. 1 (los 1.299 resultados parciales no cuentan como medición).

---

# Sesión de diagnóstico (2026-10-10)


> Un registro por cada prueba ejecutada, en orden cronológico. Los reportes crudos del runner están en `experiments/reports/<fecha-hora>-<exp>/report.{md,json}`; aquí se guarda el resumen, los parámetros, los datos medidos y lo aprendido.
> Zona horaria de las horas: America/Bogota (UTC−5). Región AWS: us-east-1.

## Entorno común (sesión del 2026-10-10)

| Elemento | Valor |
|---|---|
| Clúster | EKS `voltera-exp2-eph` v1.36, 2 × t3.large (amd64), VPC sin NAT |
| Kafka | Strimzi, Kafka 4.3.1 (KRaft), clústeres `billing` y `dominios` (1 broker c/u), MirrorMaker 2 |
| Tópico de ingreso | `voltera.consumo-facturable-preparado`, 5 particiones, factor de replicación 1 |
| `ms-process-billing` | Pod Python 3.12 (amd64), consumer group `ms-process-billing`, KEDA 1..5 réplicas, `lagThreshold` 2 |
| Flujo aguas abajo | SQS → Pipe → Step Functions Standard → `ms-tarifas` → `ms-calculo-consumo-neto` → `ms-facturacion` → SQS comprobantes → `ms-comprobante-factura` |
| SLA del lote | 120 s |
| Retardo simulado por defecto en el pod | 5 s (`SIMULATED_DELAY_SECONDS`) |

---

## Prueba 0 — Humo del stack base (sin Kafka)
- **Fecha/hora:** 2026-10-10 10:38 · **Ciclo:** `SMOKE-001` · **Script:** `experiments/smoke/smoke_test.sh`
- **Objetivo:** comprobar Pipe → Step Functions → Lambdas → cola de comprobantes sin Kafka.
- **Parámetros:** 2 transacciones sembradas en DynamoDB, 2 mensajes enviados a mano a la cola de transacciones.
- **Resultados:**
  - 2 ejecuciones de Step Functions `SUCCEEDED`.
  - Facturas emitidas, p. ej. `FV-000002` (valor 125.450 COP, tarifa residencial 650 COP/kWh, consumo neto 193 kWh).
  - Comprobantes: 2 `NOTIFICADA`. Colas de transacciones y comprobantes y sus DLQ en 0.
  - Duración de `ms-comprobante-factura`: 1,2–1,5 s (incluye arranque en frío de ~0,9–1,1 s).
- **Observaciones:** los eventos de dominio se descartaron con la advertencia "mesh sin configurar" (no había Kafka todavía), comportamiento best-effort esperado. Quedó validado el formato que el Pipe entrega a `NormalizarEntrada`.
- **Veredicto:** OK.

## Prueba 1a — Exp. 1 (absorción del pico), N = 10
- **Fecha/hora:** 2026-10-10 11:14:44 → 11:20:15 · **Ciclo:** `EXP-20261010161444` · **Reporte:** `reports/20261010-112015-exp1/`
- **Parámetros:** N = 10, retardo simulado 5 s por mensaje, SLA 120 s, réplicas 1..5.
- **Resultado global:** **PASS** (7 criterios PASS, 1 MANUAL).
- **Medidas:**

| Instante | Réplicas | Lag | Terminadas |
|---|---|---|---|
| 8,8 s | 1 | n/d | 0/10 |
| 23,5 s | 4 | 5 | 1/10 |
| 38,8 s | 5 | 3 | 7/10 |
| 52,1 s | 5 | 1 | 9/10 |
| 65,1 s | 5 | 0 | 10/10 |

  - Tiempo del lote: **65,1 s** (SLA 120 s). Pico de réplicas 5; lag pico 5, final 0; réplicas volvieron a 1 sin intervención.
  - Conservación: inyectadas 10 = emitidas 10 + rechazadas 0 + DLQ 0. Notificadas 10, sin duplicados.
- **Observaciones:** primer despliegue real. Hubo que corregir antes tres fallos de configuración (descripción de regla de seguridad con `>`, grupo de API de Strimzi `kafka.strimzi.io`, imagen arm64 en nodos amd64 y falta de `AWS_DEFAULT_REGION`). Pendiente MANUAL E1.8 (concurrencia de Lambdas).

## Prueba 1b — Exp. 1 (absorción del pico), N = 100
- **Fecha/hora:** 2026-10-10 11:23:04 → 11:30:20 · **Ciclo:** `EXP-20261010162302` · **Reporte:** `reports/20261010-113020-exp1/`
- **Parámetros:** N = 100, retardo simulado 2 s por mensaje, SLA 120 s, réplicas 1..5. Imagen anterior a la instrumentación (sin métricas propias en CloudWatch).
- **Resultado global:** **FAIL** (6 criterios PASS, 1 FAIL, 1 MANUAL).
- **Medidas:**

| Instante | Réplicas | Lag | Terminadas |
|---|---|---|---|
| 8,6 s | 1 | 99 | 0/100 |
| 22,3 s | 4 | 92 | 8/100 |
| 35,1 s | 5 | 83 | 16/100 |
| 48,0 s | 5 | 70 | 32/100 |
| 60,7 s | 5 | 59 | 42/100 |
| 73,3 s | 5 | 46 | 55/100 |
| 86,5 s | 5 | 32 | 68/100 |
| 99,6 s | 5 | 21 | 79/100 |
| 112,0 s | 5 | 15 | 85/100 |
| 124,7 s | 5 | 11 | 89/100 |
| 137,2 s | 5 | 4 | 96/100 |
| 149,8 s | 5 | 0 | 100/100 |

  - Tiempo del lote: **149,8 s** → **FAIL** frente al SLA de 120 s (E1.2).
  - Escalado correcto (1→4→5 en ~35 s), lag pico 99 y final 0, réplicas de vuelta a 1, cero pérdidas (100 = 100 + 0 + 0), DLQ en 0.
- **Hallazgos:**
  - Rendimiento observado ≈ 0,7 mensajes/s con 5 réplicas, es decir ≈ 7 s por mensaje por réplica, frente a ≈ 2–3 s esperados con 2 s de retardo simulado. Hay un sobrecosto por mensaje sin explicar (hipótesis: réplicas que nacen tarde y rebalances, reparto desigual de claves en 5 particiones, trabajo secuencial por pod).
  - La cola SQS de transacciones se vio siempre en 0: el backlog real vive en el lag de Kafka (el Pipe vacía SQS al instante).
  - El panel de lag de Grafana no mostraba datos: el agente `cwagent-prometheus` no publicaba (configuración inválida y fallo de credenciales) y las métricas EMF por stdout de `ms-process-billing` no llegaban a CloudWatch.
- **Acciones derivadas:** métricas publicadas directo con `put_metric_data`, métrica de lag propia (`KafkaConsumerLag`), instrumentación por mensaje (`MensajeTotalMs`, `MensajeSobrecostoMs`), apagado del agente de Prometheus.

---

## Prueba 1c — Exp. 1 (absorción del pico), N = 200
- **Fecha/hora:** 2026-10-10 11:44:56 → ~11:50 (interrumpida a mano para dar de baja la infraestructura) · **Ciclo:** `EXP-20261010164452` · **Reporte:** no se generó (el runner se detuvo antes de escribirlo; los datos salen de su log en pantalla y de DynamoDB).
- **Parámetros:** N = 200, retardo simulado 2 s por mensaje, SLA 120 s, réplicas 1..5. Imagen **nueva** (métricas directo a CloudWatch con `put_metric_data`, `KafkaConsumerLag`, `MensajeTotalMs`/`MensajeSobrecostoMs`, clientes boto3 con pool y reintentos).
- **Resultado:** **no concluyente / FAIL en tiempo.** 199 de 200 facturas llegaron a estado terminal; el criterio de tiempo del lote (≤ 120 s) **no se cumplió**: 199 facturas en ~176 s (la 200 nunca registró estado, ver hallazgo).
- **Medidas:**

| Instante | Réplicas | Lag | Terminadas |
|---|---|---|---|
| 9,0 s | 1 | 159 | 0/200 |
| 22,8 s | 4 | 193 | 0/200 |
| 35,7 s | 5 | 173 | 25/200 |
| 48,4 s | 5 | 153 | 44/200 |
| 60,7 s | 5 | 132 | 61/200 |
| 73,8 s | 5 | 100 | 99/200 |
| 86,4 s | 5 | 75 | 124/200 |
| 99,1 s | 5 | 63 | 136/200 |
| 111,9 s | 5 | 44 | 155/200 |
| 125,4 s | 5 | 27 | 173/200 |
| 138,0 s | 5 | 17 | 183/200 |
| 150,6 s | 5 | 9 | 191/200 |
| 163,3 s | 5 | 3 | 196/200 |
| 176,0 s | 5 | 0 | **199/200** |

  - Escalado: 1 → 4 → 5 réplicas en ~36 s. Lag pico 193, final 0. DLQ de transacciones y de comprobantes en 0; ninguna ejecución de Step Functions fallida, `TIMED_OUT` ni `ABORTED`.
  - **Rendimiento:** ≈ 1,1 mensajes/s con 5 réplicas (199 en 176 s), frente a ≈ 0,67 mensajes/s en la prueba de 100 (100 en 150 s). **El ritmo mejoró ~70 %** con la imagen nueva, aunque sigue por debajo del esperado (2 s de retardo y 5 réplicas darían ≈ 2,5 mensajes/s).
- **Hallazgo: un evento de estado perdido.** La factura `EXP-20261010164452-F0011` está en la tabla de dedup como `ENVIADO` y sus rastros aparecen en los logs de `ms-tarifas`, `ms-calculo-consumo-neto`, `ms-facturacion` y `ms-comprobante-factura` (se procesó de punta a punta), pero **el consumidor de estado de `process-billing` nunca registró su evento `FACT#`**. El ciclo quedó `EN_CURSO` con `emitidas = 199`. No se perdió ninguna factura, se perdió un **evento de observabilidad**: es el costo del diseño *best-effort* de publicación al mesh.
  - Sugerencias: que el estado del ciclo no dependa de un solo evento (p. ej. reconciliación contra DynamoDB al vencer un temporizador), o publicar con reintentos / outbox desde las Lambdas.
- **Observabilidad:** las métricas propias del pod llegaron a CloudWatch (`KafkaConsumerLag`, `MensajeTotalMs`, etc.). El lag de Grafana usa `Sum/6` (6 muestras por minuto). Se añadieron etiquetas de eje a todos los gráficos.

## Cierre de la sesión — baja de la infraestructura
- **Fecha/hora:** 2026-10-10 ~12:05 → ~13:00. Orden: Lambdas fuera de la VPC (base), `scripts/destroy-ephemeral.sh --yes`, destrucción del base, borrado del usuario IAM de Grafana, Grafana local detenido.
- **Resultado:** plataforma 9 recursos, clúster 49, base 55 destruidos. Verificado: sin EKS, EC2, balanceadores, VPC, NAT, IP elásticas, Lambdas, tablas, colas, ECR ni roles de Voltera.
- **Incidentes del cierre:** el borrado de la VPC tardó ~1 h por (1) una interfaz de red huérfana `aws-K8S-…` que bloqueaba la subred y (2) el grupo de seguridad `eks-cluster-sg-…` que EKS deja sin borrar. Ambos se eliminaron a mano; el procedimiento está en `REDESPLIEGUE.md` §3.
- **Costo de la sesión (estimado):** el clúster estuvo encendido ≈ 10:45–12:15 (≈ 1,5 h × 0,31 USD/h ≈ 0,5 USD) más unos 30 min de cierre; total cercano a 1 USD.

## Prueba 2 — Exp. 1 - Absorcion del pico de fin de mes (auto-escalado) (demo en pantalla)
- **Fecha/hora:** 2026-10-11T12:26:16-0500 → 2026-10-11T12:34:30-0500 · **Ciclo:** `EXP-20261011172616` · **Reporte:** `reports/20261011-122616-demo-exp1/`
- **Parametros:** N=500, cicloId=EXP-20261011172616, retardoSegundos=0.1, slaSegundos=300.0, replicasMin=1, replicasMax=5
- **Resultado global:** **PASS** (7 PASS, 0 FAIL, 1 MANUAL)
- **Medidas:**

| Instante | Replicas | Lag | Terminadas |
|---|---|---|---|
| 14.9 s | 1 | 2 | 0/500 |
| 29.7 s | 1 | 335 | 91/500 |
| 42.6 s | 4 | 341 | 154/500 |
| 57.1 s | 5 | 177 | 304/500 |
| 70.5 s | 5 | 35 | 452/500 |
| 83.3 s | 5 | 0 | 486/500 |
| 96.7 s | 5 | 0 | 486/500 |
| 110.5 s | 5 | 0 | 486/500 |
| 123.5 s | 5 | 0 | 500/500 |

- **Hallazgos / observaciones:**
  - Todos los criterios automaticos cumplidos.
  - La escala validada es <=10 solicitudes: comportamiento, no capacidad. El backlog se fuerza con retardoSegundos por mensaje.
- **Acciones derivadas:** (completar tras revisar la grabacion)

## Prueba 3 — Exp. 2 - Caida de un dependiente sin detener el negocio (aislamiento) (demo en pantalla)
- **Fecha/hora:** 2026-10-11T12:40:22-0500 → 2026-10-11T12:51:40-0500 · **Ciclo:** `EXP-20261011174022` · **Reporte:** `reports/20261011-124022-demo-exp2/`
- **Parametros:** N=200, cicloId=EXP-20261011174022, modoFallo=env
- **Resultado global:** **FAIL** (7 PASS, 2 FAIL, 0 MANUAL)
- **Medidas:**

Caso B:
| Instante | Emitidas | Cola tx | DLQ tx | Cola comp | DLQ comp |
|---|---|---|---|---|---|
| 0.0 s | 0 | 0 | 0 | 0 | 0 |
| 43.6 s | 8 | 0 | 0 | 4 | 0 |
| 78.4 s | 42 | 0 | 0 | 32 | 0 |
| 113.5 s | 69 | 0 | 0 | 60 | 0 |
| 149.8 s | 98 | 0 | 0 | 93 | 0 |
| 185.3 s | 120 | 0 | 0 | 95 | 30 |
| 220.6 s | 140 | 1 | 0 | 81 | 45 |
| 255.7 s | 153 | 0 | 0 | 79 | 88 |
| 291.6 s | 167 | 0 | 0 | 56 | 77 |
| 327.5 s | 186 | 0 | 0 | 54 | 126 |
| 362.6 s | 200 | 0 | 0 | 53 | 146 |
| 425.7 s | 200 | 0 | 0 | 37 | 169 |
| 503.8 s | 200 | 0 | 0 | 9 | 200 |
| 591.5 s | 200 | 0 | 0 | 0 | 0 |

- **Hallazgos / observaciones:**
  - E2.B.2 FAIL: Tras 3 entregas fallidas, los 200 comprobantes caen a la DLQ de comprobantes — esperado 200 en DLQ; observado 167 en DLQ (200 aprox.)
  - E2.B.3 FAIL: process-billing registra las notificaciones definitivamente fallidas (FACT# FALLIDA) — esperado 200 FALLIDA; observado 199 FALLIDA
- **Acciones derivadas:** (completar tras revisar la grabacion)

## Prueba 4 — Exp. 3 - Cero perdida de solicitudes ante fallos (demo en pantalla)
- **Fecha/hora:** 2026-10-11T12:59:23-0500 → 2026-10-11T13:04:37-0500 · **Ciclo:** `EXP-20261011175923` · **Reporte:** `reports/20261011-125923-demo-exp3/`
- **Parametros:** N=300, cicloId=EXP-20261011175923, retardoSegundos=0.1, failRate=0.25, podsMatados=2
- **Resultado global:** **PASS** (6 PASS, 0 FAIL, 3 MANUAL)
- **Medidas:**

| Criterio | Esperado | Observado |
|---|---|---|
| E3.1 Los pods de process-billing muertos son reemplazados y vuelven a estar listos | pod(s) nuevo(s) listo(s) | muertos=['ms-process-billing-574f8877c6-cqtk7'], reemplazo listo en 29 s |
| E3.2 Lambdas (ms-comprobante-factura y ms-facturacion) restauradas tras el fallo a mitad del lote | sin pendientes en bitacora | 0 pendientes |
| E3.4 Ecuacion de conservacion: inyectadas = facturas emitidas + rechazadas + mensajes en DLQ | inyectadas(300) = emitidas(300) + rechazadas_negocio(0) + DLQ(0) -> suma 300 | faltantes=[] ajenas=[] |
| E3.5 Cero facturas duplicadas (idempotencia): un registro por facturaId, numeroFactura unico, DEDUP# == N | 0 duplicados; DEDUP# == N | duplicadas=[] numerosRepetidos=[] DEDUP#=300 consecutivo=2408 emitidas=300 |
| E3.6 Comprobantes: toda factura emitida termina notificada (reentrega tras el fallo del tercero) | emitidas subset de notificadas (o en DLQ de comprobantes) | notificadas=300 dlqComprobantes=0 |
| E3.9 Eventos FacturaEmitida: una sola emision por factura en el mesh | 1 evento por factura | 300 facturas con evento; repetidas=0 |

- **Hallazgos / observaciones:**
  - Todos los criterios automaticos cumplidos.
- **Acciones derivadas:** (completar tras revisar la grabacion)

## Prueba 5 — Exp. 2 - Resiliencia ante fallos (aislamiento + cero perdida) (demo en pantalla)
- **Fecha/hora:** 2026-10-11T14:00:42-0500 → 2026-10-11T14:12:25-0500 · **Ciclo:** `EXP-20261011190042` · **Reporte:** `reports/20261011-140042-demo-exp2/`
- **Parametros:** N=300, cicloId=EXP-20261011190042, caso=B, modoFallo=env, retardoSegundos=1.0, failRate=0.25, podsMatados=2, ventanaSegundos=30.0, duplicadosSolicitados=30
- **Resultado global:** **FAIL** (15 PASS, 1 FAIL, 2 MANUAL)
- **Medidas:**

| Instante | Fase | Emitidas | Enviadas | Pods | Cola tx | DLQ tx | Cola comp | DLQ comp |
|---|---|---|---|---|---|---|---|---|
| 0.0 s | estado_inicial | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| 16.5 s | fallo_dependiente | 0 | 2 | 1 | 0 | 0 | 0 | 0 |
| 32.6 s | fallo_dependiente | 18 | 17 | 1 | 0 | 0 | 0 | 0 |
| 38.7 s | fallo_dependiente | 37 | 35 | 4 | 1 | 0 | 0 | 0 |
| 57.4 s | fallo_pod | 124 | 121 | 3 | 0 | 0 | 91 | 18 |
| 88.1 s | fallo_lambda | 239 | 243 | 5 | 0 | 0 | 75 | 0 |
| 103.7 s | fallo_lambda | 292 | 293 | 5 | 0 | 1 | 88 | 156 |
| 130.4 s | duplicados | 299 | 300 | 1 | 0 | 1 | 0 | 228 |
| 341.5 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 367.1 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 392.6 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 417.5 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 441.7 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 466.4 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 491.2 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 515.9 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 541.6 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 565.1 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 589.5 s | recuperacion | 299 | 300 | 1 | 0 | 1 | 0 | 0 |
| 615.0 s | recuperacion | 300 | 300 | 1 | 0 | 0 | 0 | 0 |
| 643.8 s | recuperacion | 300 | 300 | 1 | 0 | 0 | 0 | 0 |

| Criterio | Esperado | Observado |
|---|---|---|
| E2.1 AISLAMIENTO: las facturas emitidas siguen subiendo con ms-comprobante-factura caido (bulkhead) | emitidas(fin) > emitidas(inicio del fallo) | 0 -> 30 de 300 |
| E2.2 AISLAMIENTO: ms-process-billing no cae del todo y sigue consumiendo/encolando durante el fallo del dependiente | DEDUP# ENVIADO sube y >= 1 replica lista | ENVIADO 0 -> 47 de 300; replicas listas=5 |
| E2.3 Endpoint de salud dummy (servicios 'en linea'): /healthz de ms-process-billing responde | HTTP 200 via proxy del API server | ver evidencia |
| E2.4 CERO PERDIDA: los pods de process-billing muertos son reemplazados y vuelven a estar listos | pod(s) nuevo(s) listo(s) | muertos=['ms-process-billing-65ccb6f9d8-98pdt', 'ms-process-billing-65ccb6f9d8-j499z'], reemplazo listo en 5 s |
| E2.5 IDEMPOTENCIA: se forzaron 30 duplicados (a) por SQS y (b) por Kafka | 30 por SQS y 30 por Kafka | SQS=30, Kafka=30 |
| E2.6 CERO PERDIDA (antes del redrive): inyectadas = emitidas + rechazadas + mensajes en DLQ | inyectadas(300) = emitidas(299) + rechazadas_negocio(0) + DLQ(1) -> suma 300 | faltantes=[] ajenas=[] |
| E2.8 Redrive de las DLQ exitoso (mensajes devueltos a la cola de origen) | COMPLETED | transacciones:FAILED, comprobantes:COMPLETED |
| E2.7 CERO PERDIDA: los mensajes en vuelo al morir el pod se reentregan y se procesan (DEDUP# PROCESANDO -> ENVIADO) | todos los PROCESANDO terminan ENVIADO y contabilizados | 5/5 reentregados; perdidos=[] |
| E2.9 CERO PERDIDA (despues del redrive): inyectadas = emitidas + rechazadas + DLQ y todas contabilizadas | inyectadas(300) = emitidas(300) + rechazadas_negocio(0) + DLQ(0) -> suma 300 | faltantes=[] ajenas=[] |
| E2.10 CERO PERDIDA: tras la recuperacion todas las facturas emitidas estan notificadas | emitidas subset de notificadas | emitidas=300 notificadas=300 |
| E2.11 IDEMPOTENCIA: los duplicados NO crean facturas extra (emitidas == N, no N+D) | emitidas == 300 (N=300, D=30); un registro por facturaId; DEDUP# == N | emitidas=300 duplicadas=[] numerosRepetidos=[] DEDUP#=300 consecutivo=3306 |
| E2.12 IDEMPOTENCIA: se conto al menos un duplicado descartado (Kafka) o un replay de idempotencia (SQS) | >= 1 duplicado descartado o replay | replays=60.0 MensajesDuplicados(CW)=1.0 descartados en logs=30 |
| E2.13 RECUPERACION: Lambdas restauradas al estado original (FORCE_FAIL / FAIL_RATE) | sin entradas pendientes en la bitacora y sin fallos activos | 0 pendientes |
| E2.14 RECUPERACION: colas y DLQ en 0 al final | transacciones, comprobantes y sus DLQ en 0 | cola-tx=0 cola-comp=0 DLQ-tx=0 DLQ-comp=0 |
| E2.15 RECUPERACION: estado del ciclo consistente (FACT# OK y META COMPLETADO) | 300 OK y COMPLETADO | 300 OK, estado COMPLETADO |
| E2.16 Eventos FacturaEmitida: una sola emision por factura en el mesh | 1 evento por factura | 300 facturas con evento; repetidas=0 |

- **Hallazgos / observaciones:**
  - E2.8 FAIL: Redrive de las DLQ exitoso (mensajes devueltos a la cola de origen) — esperado COMPLETED; observado transacciones:FAILED, comprobantes:COMPLETED
  - AISLAMIENTO: PASS (E2.1=PASS, E2.2=PASS)
  - CERO PERDIDA: PASS (E2.6=PASS, E2.9=PASS, E2.10=PASS)
  - IDEMPOTENCIA: PASS (E2.11=PASS, E2.12=PASS)
  - RECUPERACION: PASS (E2.13=PASS, E2.14=PASS)
- **Acciones derivadas:** (completar tras revisar la grabacion)

---
## Plantilla para pruebas siguientes

```
## Prueba <n> — <experimento> (<variante>)
- **Fecha/hora:** · **Ciclo:** · **Reporte:** reports/<carpeta>/
- **Parámetros:** N, retardo, SLA, fallos inyectados, imagen/versión
- **Resultado global:** PASS/FAIL (n PASS, n FAIL, n MANUAL)
- **Medidas:** tabla (instante, réplicas, lag, terminadas) o cifras clave
- **Hallazgos / observaciones:**
- **Acciones derivadas:**
```
