# Observabilidad (Grafana OSS local) — Experimentación 2

Grafana 11.4.0 en Docker, solo lectura sobre CloudWatch (métricas y Logs Insights) y X-Ray, región `us-east-1`.
Todo se provisiona como código; no se crean recursos en AWS.

## Contenido
| Ruta | Qué es |
|---|---|
| `docker-compose.yml`, `.env.example` | Grafana con versión fija, solo en `127.0.0.1:3000` |
| `provisioning/datasources/` | CloudWatch (uid `cloudwatch`) y X-Ray (uid `xray`, plugin `grafana-x-ray-datasource`) |
| `provisioning/dashboards/` | Proveedor de archivos (carpeta "Voltera Exp2") |
| `dashboards/` | `00-ciclo-en-vivo`, `exp1-absorcion-pico`, `exp2-caida-dependiente`, `exp3-cero-perdida`, `exp4-event-mesh` (schemaVersion 39) |
| `iam/grafana-readonly-policy.json` | Política IAM de mínimo privilegio |
| `tools/gen_dashboards.py` | Genera los JSON (`--prefix`, `--cluster`, `--namespace` si cambian los nombres) |

## 1. Crear el usuario de solo lectura (ejemplo, NO ejecutado por el agente)
```bash
aws iam create-policy --policy-name voltera-grafana-readonly \
  --policy-document file://iam/grafana-readonly-policy.json
aws iam create-user --user-name voltera-grafana
aws iam attach-user-policy --user-name voltera-grafana \
  --policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/voltera-grafana-readonly
aws iam create-access-key --user-name voltera-grafana   # copia AccessKeyId/SecretAccessKey
```
La política limita Logs a `/aws/lambda/voltera-exp2-*`, `/aws/vendedlogs/states/voltera-exp2-*` y `/aws/containerinsights/voltera-exp2-eph/*`.
Al terminar la experimentación: `aws iam delete-access-key ...`, `detach-user-policy`, `delete-user`, `delete-policy`.

## 2. Credenciales mínimas (no se monta `~/.aws`)
```bash
cp .env.example .env            # cambia GRAFANA_ADMIN_PASSWORD
cp aws/credentials.example aws/credentials && chmod 600 aws/credentials
# edita aws/credentials: solo el perfil [voltera-grafana]
docker compose config           # valida sin iniciar
docker compose up -d            # http://localhost:3000
```
`aws/credentials` y `.env` están en `.gitignore`. El contenedor recibe únicamente ese archivo (solo lectura) mediante `AWS_SHARED_CREDENTIALS_FILE`.
Opcional: `AWS_CREDENTIALS_FILE=/ruta/otro/archivo` en `.env`.

## 3. Cómo leer los dashboards
- Variables: `cicloId` y `facturaId` (texto, regex; `.` = todos), `sfn` (State machine, se descubre por `StateMachineArn`), rango de tiempo de Grafana.
- **Las métricas EMF (`Voltera/Exp2`) solo llevan la dimensión `service`** (no `cicloId`, no pod). Por eso `cicloId` filtra los paneles de Logs Insights, y las métricas se acotan con el **rango de tiempo** de la corrida.
- Saldo de conservación = `RUNNING_SUM(inyectadas) - RUNNING_SUM(emitidas) - rechazos de negocio - DLQ(transacciones)`; es positivo mientras hay trabajo en vuelo y debe quedar en 0 al finalizar.
- Ya no quedan paneles `[PENDIENTE]`; si aparece alguno en el futuro cita su incidencia (OBS-n) en `ORQUESTACION.md`.

## Dashboards para grabar (exp1, exp2, exp3)
- ~6 paneles cada uno, fila superior de stats con fuente grande, refresh 5 s y rango 15 min. Cada panel trae en su descripción "Qué mirar" y "Patrón de arquitectura". Guion de exposición en `GUION-EXPOSICION.md`.
- Anotaciones: métrica `FaseExperimento` (namespace `Voltera/Exp2`, dims `experimento`=`exp1|exp2|exp3`, `fase`=`pico_inyectado|fallo_inyectado|recuperacion`, valor 1) que publica el runner. El datasource CloudWatch de Grafana no admite anotaciones por métrica, así que se leen del resultado de los paneles de la fila final "Fuente de anotaciones" (datasource `-- Dashboard --`). Sin verificar en Grafana real.
- Nuevas métricas (ms-process-billing): `CiclosReconciliados`, `FacturasReconciliadas`. Lag: `KafkaConsumerLag` Sum/6.

## Métricas y campos usados
- `Voltera/Exp2` (dim `service`): `UnidadesEnOutbox`, `EventosPublicadosOutbox`, `TarifasValidadas/Rechazadas`, `CargosCalculados`, `CalculosRechazados`, `FacturasEmitidas`, `EmisionesRechazadas`, `FacturasNotificadas`, `NotificacionesFallidas`, `TransaccionesEnviadasASqs`, `MensajesDuplicados` (volcado cada 10 s), `MeshPublishFailures`, `MensajesReenviados`, `MensajesProcesadosPorPod` y `HealthCheckOk` (dims `service`+`pod`), `IdempotenciaReplays`, `CiclosCompletados`, `CiclosFallidos`, `CicloDuracionSegundos`.
- Exp1: `KafkaConsumerLag` (dims `service`, `topic`; Sum) y `MensajeTotalMs`/`MensajeSobrecostoMs` (dim `service`).
- `AWS/SQS` (`QueueName` = `voltera-exp2-transacciones[-dlq]`, `voltera-exp2-comprobantes[-dlq]`), `AWS/Lambda` (búsqueda por `voltera-exp2`), `AWS/States` (`StateMachineArn`), `ContainerInsights` (`service_number_of_running_pods`, `pod_cpu_utilization`, `pod_number_of_container_restarts`).
- Logs JSON de Powertools: `message`, `service`, `cicloId`, `facturaId`, `aprobado`, `numero`; mensajes `evento publicado` (tipo), `ciclo iniciado`, `comprobante recibido/procesado`, `tarifa procesada`, `calculo procesado`, `factura procesada`.

## Sin verificar (no se llamó a AWS)
- Que los logs JSON de `ms-process-billing` (Container Insights, log group `application`) lleguen con los campos en el primer nivel; si Fluent Bit los anida bajo `log`, ajustar la consulta de la línea de tiempo de Exp4.
- Sintaxis exacta de consultas Logs Insights y nombres de eventos del log de Step Functions (`TaskScheduled`, etc.).
- Que el add-on de Container Insights publique `service_number_of_running_pods` con dimensiones `ClusterName/Namespace/Service` y que el EMF de `ms-process-billing` (stdout del contenedor) sea extraído por CloudWatch tras pasar por Fluent Bit.
- Query types del plugin X-Ray (`getTraceSummaries`, `getTimeSeriesServiceStatistics`, `getServiceMap`) y renderizado en Grafana. Ajustar desde la UI y re-exportar si alguno falla.
- Si el lab usa otra versión de Grafana, cambia `GRAFANA_VERSION` en `.env`.
