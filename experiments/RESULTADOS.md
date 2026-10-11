# Bitácora de pruebas — Experimentación 2 (facturación dirigida por eventos)

> **Segunda tanda (grabación de Exp. 1, 2 y 3):** los registros nuevos se agregan abajo, en "Tanda de grabación". La sesión del 2026-10-10 se conserva más abajo como **sesión de diagnóstico** (referencia: arrancó con el rendimiento de 1,1 mensajes/s y el evento de estado perdido).

## Tanda de grabación

_(sin registros todavía; el modo demo del runner agrega cada prueba aquí automáticamente)_

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
