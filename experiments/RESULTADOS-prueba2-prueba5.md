# Resultados de la Prueba 2 (Exp. 1) y la Prueba 5 (Exp. 2)

> Datos medidos el 2026-10-11 (hora Bogotá, UTC−5) en AWS `us-east-1`. Fuentes: reportes del runner (`reports/20261011-122616-demo-exp1/` y `reports/20261011-140042-demo-exp2/`), DynamoDB y métricas de CloudWatch por minuto. Lo que no se pudo medir se marca **NO MEDIDO**.
> Entorno común: EKS 1.36, Kafka Strimzi 4.3.1 (KRaft), `ms-process-billing` con KEDA 1..5 réplicas, 6 microservicios del flujo de facturación. Los tableros de Grafana son `voltera-exp1-absorcion` y `voltera-exp2-resiliencia`.

---

## Prueba 2 — Exp. 1: absorción del pico de fin de mes

**Resultado: PASS** (7 criterios cumplidos, 0 fallidos, 1 manual).

### Qué se probó
Que un lote de facturas que llega de golpe se absorba sin pérdidas y dentro del SLA, escalando `ms-process-billing` según el lag de Kafka y volviendo a 1 pod sin intervención.

| Parámetro | Valor |
|---|---|
| Ciclo | `EXP-20261011172616` |
| Facturas inyectadas (N) | 500 |
| Retardo simulado por factura | 0,1 s |
| SLA del lote | 300 s (fijado antes de medir) |
| Réplicas | mín. 1, máx. 5 (5 particiones en el tópico) |
| Inicio → fin del runner | 12:26:16 → 12:34:30 |

### Lo que se generó

**Serie medida por el runner** (lag leído directamente de Kafka):

| Instante | Réplicas | Lag | Facturas terminadas |
|---|---|---|---|
| 14,9 s | 1 | 2 | 0 / 500 |
| 29,7 s | 1 | 335 | 91 / 500 |
| 42,6 s | 4 | 341 | 154 / 500 |
| 57,1 s | 5 | 177 | 304 / 500 |
| 70,5 s | 5 | 35 | 452 / 500 |
| 83,3 s | 5 | 0 | 486 / 500 |
| 96,7 s | 5 | 0 | 486 / 500 |
| 110,5 s | 5 | 0 | 486 / 500 |
| 123,5 s | 5 | 0 | **500 / 500** |

**Serie por minuto en CloudWatch:**

| Hora | Pods (máx.) | Emitidas | Notificadas | Mensajes de comprobante en vuelo |
|---|---|---|---|---|
| 12:26 | 1 | 119 | 119 | 0 |
| 12:27 | 5 | 381 | 381 | 0 |
| 12:28–12:31 | 5 | — | — | 0 |
| 12:32 | 1 | — | — | 0 |

### Tiempos medidos

| Medida | Valor | Cómo se midió |
|---|---|---|
| Tiempo del lote | **116,6 s** (SLA 300 s) | `CicloDuracionSegundos` del ciclo; el runner midió 123,5 s desde el disparo |
| Hasta la 1.ª réplica adicional | ≤ 42,6 s | el escalado fue 1 → 4 en un solo paso; resolución del muestreo ≈ 13 s |
| Hasta el máximo (5 réplicas) | ≤ 57,1 s | idem |
| Lag máximo observado | 341 mensajes | lectura directa del grupo de Kafka |
| Lag en 0 | 83,3 s | idem |
| Rendimiento medio | ≈ 4,3 facturas/s (500 ÷ 116,6 s) | |
| Rendimiento pico | 381 facturas/min ≈ 6,4/s | minuto 12:27 |
| Bajada a 1 pod | entre 3 y 4,5 min tras vaciar el lag | resolución de 1 min; **no es medida limpia**, ver abajo |

### Qué funcionó
- **El pico se absorbió sin perder nada:** 500 inyectadas, 500 emitidas y 500 notificadas, con DLQ de transacciones y de comprobantes en 0.
- **KEDA reaccionó al lag, no a CPU:** de 1 a 4 réplicas en un solo paso y a 5 en menos de 60 s.
- **El flujo aguas abajo no fue el cuello de botella:** las 500 notificaciones se procesaron en los minutos 12:26 y 12:27, sin reintentos ni mensajes atascados.
- **El tiempo del lote quedó 2,6 veces por debajo del SLA** (116,6 s contra 300 s).

### Observaciones y límites
1. **Cola final de 14 facturas.** El contador del runner se quedó en 486/500 desde los 83 s hasta los 123 s. Según CloudWatch, las 500 facturas ya estaban emitidas y notificadas al minuto 12:27, así que el retraso no estuvo en el procesamiento. Ese contador cuenta eventos de estado que llegan por Kafka, y 14 llegaron unos 40 s más tarde. **Causa NO MEDIDA.**
2. **El tiempo de bajada no es limpio.** La ventana de reducción del autoescalador estaba en 300 s por defecto y se cambió a 30 s durante esta corrida. La bajada de 3 a 4,5 min es consistente con la ventana original. La medida limpia con 30 s está en la Prueba 5.
3. **Los pods nuevos tardaron ~30 s en arrancar** por cuatro contenedores de instrumentación que no usamos. Ya se quitaron después de esta corrida; el efecto en el tiempo de escalado no se re-midió.
4. **El retardo de 0,1 s por factura es simulado.** La prueba valida el comportamiento de absorción, no la capacidad real de producción.

---

## Prueba 5 — Exp. 2: resiliencia ante fallos (aislamiento + cero pérdida)

**Resultado del runner: FAIL (15 criterios PASS, 1 FAIL, 2 manuales).** El único FAIL es el reproceso de la DLQ de **transacciones** (E2.8). Como se pidió, ese caso queda fuera de este análisis, que se centra en la DLQ de **comprobantes**. Sobre lo demás, ningún criterio de aislamiento, cero pérdida, idempotencia o recuperación falló.

### Qué se probó
Un escenario único con cinco inyecciones, en este orden:

| Fase | Hora | Qué se inyectó |
|---|---|---|
| Estado inicial | 14:00:45 | Sistema sano, colas y DLQ en 0 |
| Disparo | 14:00:53 | 300 facturas y cierre de mes (retardo 1 s) |
| **Fallo del dependiente** | **14:01:05** | `ms-comprobante-factura` caído (`FORCE_FAIL`) |
| Pods muertos | 14:01:43 | 2 pods de `ms-process-billing` matados con mensajes en vuelo |
| Fallo en Lambda | 14:02:08 | 25 % de fallos en `ms-facturacion` durante 30 s |
| Duplicados | 14:03:03 | 30 copias por SQS y 30 por Kafka |
| **Recuperación** | **14:04:01** | Se restauran las Lambdas y se reprocesa la DLQ |
| Veredicto | 14:11:43 | Contabilidad final |

Parámetros: ciclo `EXP-20261011190042`, N = 300, caso B (`ms-comprobante-factura`), cola de comprobantes con visibilidad de 10 s y 2 intentos antes de ir a la DLQ.

### Lo que se generó

**Serie del runner** (muestras seleccionadas; la serie completa tiene 40 puntos):

| Instante | Hora | Fase | Emitidas | Enviadas | Pods | Cola comp. | DLQ comp. |
|---|---|---|---|---|---|---|---|
| 0,0 s | 14:00:42 | estado inicial | 0 | 0 | 1 | 0 | 0 |
| 23,8 s | 14:01:05 | fallo dependiente | 9 | 10 | 1 | 0 | 0 |
| 38,7 s | 14:01:20 | fallo dependiente | 37 | 35 | 4 | 0 | 0 |
| 57,4 s | 14:01:39 | pods muertos | 124 | 121 | 3 | 91 | 18 |
| 88,1 s | 14:02:10 | fallo Lambda | 239 | 243 | 5 | 75 | — |
| 111,4 s | 14:02:33 | fallo Lambda | 299 | 300 | 5 | 28 | 191 |
| 130,4 s | 14:02:52 | duplicados | 299 | 300 | 1 | 0 | 228 |
| 191,8 s | 14:03:53 | recuperación | 299 | 300 | 1 | 30 | **329** |
| 341,5 s | 14:06:23 | recuperación | 299 | 300 | 1 | 0 | **0** |

> Entre los 191,8 s y los 341,5 s el runner no tomó muestras (estaba haciendo el reproceso). Por eso la tabla no permite ver cuándo se vació la DLQ; ese dato sale de CloudWatch.
> El conteo de la DLQ del runner es aproximado (`ApproximateNumberOfMessages`) y fluctúa entre muestras.

**Serie por minuto en CloudWatch (comprobantes):**

| Hora | DLQ comprobantes (máx.) | Mensajes en vuelo | Fallas inyectadas | Notificadas | Invocaciones de la Lambda |
|---|---|---|---|---|---|
| 14:00 | 0 | 0 | — | — | — |
| 14:01 | 0 | 18 | 257 | — | 257 |
| 14:02 | 166 | 86 | 341 | — | 341 |
| 14:03 | 271 | 28 | 60 | — | 60 |
| **14:04** | **329** | 0 | — | **298** | 329 |
| **14:05** | **0** | 0 | — | 1 | 3 |

### Tiempo de recuperación de la DLQ de comprobantes

| Hito | Hora | Tiempo desde el hito anterior |
|---|---|---|
| `ms-comprobante-factura` cae | 14:01:05 | — |
| Primeros mensajes en la DLQ | ≈ 14:01:39 (18 mensajes) | **≈ 34 s** (2 intentos × 10 s de visibilidad, más espera de cola) |
| DLQ en su máximo | 14:03:53–14:04:00 (**329 mensajes**) | ≈ 2 min 50 s de acumulación |
| Se restaura la Lambda | **14:04:01** | — |
| El runner confirma la convergencia | ≈ 14:04:25 | 23,6 s (medido por el runner) |
| **DLQ de comprobantes vacía** | **antes de las 14:05:00** | **≤ 59 s desde la restauración** |
| Las 299 facturas pendientes notificadas | 14:04 (298) y 14:05 (1) | **≤ 2 min desde la restauración** |

- **Qué significa "≤ 59 s".** CloudWatch reporta un máximo de 0 en todo el minuto 14:05, así que la DLQ ya estaba vacía antes de que empezara ese minuto. El máximo de 329 corresponde al minuto 14:04, que arranca 1 s antes de la restauración. La resolución es de 1 minuto, así que es una cota superior, no el tiempo exacto.
- **Rendimiento del reproceso:** ≥ 5,5 mensajes/s (329 mensajes en menos de 60 s).
- **Cálculo que cuadra:** 658 fallas inyectadas (257 + 341 + 60) ÷ 2 intentos por mensaje = 329 mensajes, igual al máximo de la DLQ. Cada mensaje falló exactamente dos veces antes de ir a la DLQ, como estaba configurado.
- **Qué hay en esos 329:** ≈ 299 facturas emitidas con la notificación pendiente, más ≈ 30 copias duplicadas que entraron por SQS durante la fase de duplicados.
- **Detalle del reproceso:** la operación de SQS terminó en estado `COMPLETED` tras 2 rondas. El contador de mensajes movidos que devuelve la API suma 160 y es aproximado, así que no se usa como medida.

### Qué funcionó

**Aislamiento (el negocio siguió con el dependiente caído)**
- Con `ms-comprobante-factura` caído desde las 14:01:05, **299 de 300 facturas se emitieron antes de la recuperación** (a los 111 s). Las notificaciones fueron 0 en todo ese tiempo.
- `ms-process-billing` siguió consumiendo: de 0 a 47 mensajes enviados durante el fallo del dependiente, con réplicas listas en todo momento.
- Las facturas emitidas **no esperaron a las notificaciones**: la emisión terminó mientras la cola de comprobantes y la DLQ crecían.

**Cero pérdida**
- Antes del reproceso, 300 inyectadas = 299 emitidas + 1 en DLQ. Después, 300 = 300 emitidas + 0 en DLQ. No quedó ninguna factura sin contabilizar.
- Los 2 pods matados fueron reemplazados y estuvieron listos **en 5 s**. Los 5 mensajes que iban en vuelo se reentregaron y se procesaron (5 de 5).
- Tras la recuperación, las 300 facturas emitidas quedaron notificadas.

**Idempotencia**
- Se forzaron 30 duplicados por SQS y 30 por Kafka. El sistema registró 60 replays de idempotencia y descartó 30 duplicados en el ingreso.
- **Facturas finales: 300 (no 330), 0 repetidas.**

**Recuperación**
- Colas y DLQ en 0 al final, Lambdas restauradas, y estado del ciclo `COMPLETADO` con 300 facturas OK.
- **Los pods bajaron de 5 a 1 entre dos muestras consecutivas** (111,4 s y 130,4 s, es decir 19 s de diferencia), compatible con la ventana de reducción de 30 s. Es la medida que faltaba en la Prueba 2; como el runner no registra el instante exacto en que el lag llegó a 0, la bajada exacta desde ese instante queda **NO MEDIDA**.

### Observaciones y límites
1. **El tiempo exacto de vaciado de la DLQ no se pudo medir mejor que 1 minuto.** Hubo un hueco de 150 s sin muestras del runner durante el reproceso. Quedó como mejora pendiente: muestrear con más frecuencia durante la recuperación.
2. **Las 658 fallas son por diseño.** La cola de comprobantes se configuró con 10 s de visibilidad y 2 intentos para acortar el experimento. En un entorno real los reintentos serían más espaciados, y la acumulación en la DLQ llevaría más tiempo.
3. **Duplicados por Kafka:** se contaron 30 descartados en los logs, pero la métrica de CloudWatch solo registró 1 (`MensajesDuplicados`). La diferencia se debe a que la métrica se emite por lotes y tarda en reflejarse; **NO MEDIDO** con más precisión.
4. **El FAIL del runner no es una pérdida.** Es una factura que quedó en la DLQ de transacciones y que el runner no supo reprocesar; está excluida de este análisis a petición y ya tiene corrección en el runner.

---

## Resumen de tiempos

| Medida | Prueba 2 (Exp. 1) | Prueba 5 (Exp. 2) |
|---|---|---|
| Tiempo del lote completo | 116,6 s | 111 s hasta emitir 299 de 300 |
| Primera réplica adicional | ≤ 42,6 s | ≤ 38,7 s (1 → 4 pods) |
| Máximo de réplicas (5) | ≤ 57,1 s | ≤ 49,8 s |
| Bajada a 1 pod tras terminar el lote | 3–4,5 min (ventana de 300 s) | entre dos muestras de 19 s (ventana de 30 s) |
| Primera factura en la DLQ de comprobantes | — | ≈ 34 s tras caer el dependiente |
| Máximo en la DLQ de comprobantes | — | 329 mensajes |
| **Vaciado de la DLQ de comprobantes** | — | **≤ 59 s tras restaurar la Lambda** |
| Reemplazo de pods matados | — | 5 s |
| Facturas perdidas | 0 | 0 |
| Facturas duplicadas | 0 | 0 |
