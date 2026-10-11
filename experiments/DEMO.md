# Modo demo — grabar UN experimento por vez

Requisitos: infraestructura desplegada (base + clúster), Grafana local arriba (`observability/`), `kubectl` apuntando al clúster y credenciales AWS.

```bash
cd experiments/runner
source .venv/bin/activate            # o el python con requirements.txt
export AWS_PROFILE=<perfil> AWS_REGION=us-east-1
# Opcional, para anotaciones automaticas en Grafana (si no, se usa marcas.json + metrica CloudWatch):
export GRAFANA_URL=http://localhost:3000 GRAFANA_TOKEN=<service-account-token>   # o GRAFANA_USER/GRAFANA_PASSWORD
```

## Comandos exactos

| Experimento | Dashboard (uid) | Comando |
|---|---|---|
| Exp1 absorcion del pico | `voltera-exp1-absorcion` | `python -m runner demo exp1 --n 500 --delay 2` |
| Exp2 resiliencia ante fallos (aislamiento + cero perdida) | `voltera-exp2-resiliencia` (vista unica) | `python -m runner demo exp2 --n 300 --delay 2 --case B --kill-pods 2 --fail-rate 0.25 --fault-window 90 --dupl 50` (`--case A` = ms-tarifas) |

`demo exp3` sigue existiendo como **alias**: avisa que el antiguo Exp. 3 se unio al Exp. 2 y ejecuta `exp2`. Equivalente con una linea: `python3 correr.py exp=2` (perfil rapido: fact=150 retardo=1 ventana=30 dupl=30).

Ensayo sin tocar nada: agregue `--dry-run`. Sin pausas: `--no-pause`. Sin confirmacion de cambios: `--yes`.

## Que pasa en cada demo

Cada fase muestra un banner con la hora y espera **Enter** (sincronice con el dashboard). Antes de cada llamada se imprime el comando (`$ aws ...`, `$ kubectl ...`; las lecturas repetitivas salen una vez).

- **Exp1:** estado inicial (1 replica) -> disparo (seed + CierreDeMes) -> absorcion (KEDA sube replicas, lag crece y drena) -> recuperacion (vuelta a 1 replica) -> veredicto.
- **Exp2** (una sola corrida, 8 fases; metrica `FaseExperimento`, namespace `Voltera/Exp2`, dims `experimento=exp2` y `fase`):
  1. `estado_inicial` - todo sano, colas y DLQ en 0.
  2. `disparo` - seed + CierreDeMes.
  3. `fallo_dependiente` - FORCE_FAIL en ms-comprobante-factura (`--case A`: ms-tarifas; `--fault-mode concurrency` para concurrencia 0). Mira: las facturas emitidas siguen subiendo, ms-process-billing sigue consumiendo, la DLQ de comprobantes crece.
  4. `fallo_pod` - se matan `--kill-pods` pods de process-billing con mensajes en vuelo.
  5. `fallo_lambda` - FAIL_RATE en ms-facturacion durante `--fault-window` s (se restaura al terminar la ventana).
  6. `duplicados` - se reenvian `--dupl` copias (50) de mensajes ya enviados: (a) por SQS a `voltera-exp2-transacciones` (replays de idempotencia en ms-facturacion/ms-comprobante-factura) y (b) por Kafka al topico `voltera.consumo-facturable-preparado` con `kubectl exec` en el broker (`billing-billing-nodes-0`, `kafka-console-producer` con la misma clave/cabeceras/valor; MensajesDuplicados descartados en process-billing). Si (b) no es posible, E2.5 queda MANUAL con el motivo y sigue (a).
  7. `recuperacion` - se restaura todo, se verifica inyectadas = emitidas + rechazadas + DLQ antes del redrive, redrive de las DLQ y drenado.
  8. `veredicto` - AISLAMIENTO, CERO PERDIDA, IDEMPOTENCIA (emitidas == N, no N+D; duplicados contados) y RECUPERACION (colas/DLQ en 0, Lambdas restauradas). Espera hasta `--timeout-metricas` (150 s) a que CloudWatch refleje los replays.

## Marcas para anotar el dashboard

Por cada fase se registra, a la hora en que se pulsa Enter:
1. `experiments/reports/<run>/marcas.json` (fase, descripcion, hora local, epoch ms).
2. Metrica CloudWatch `FaseExperimento` (namespace `Voltera/Exp2`, dimensiones `experimento` y `fase`, valor 1). Puede graficarse o usarse como consulta de anotaciones del datasource CloudWatch.
3. Anotacion de Grafana (`POST /api/annotations` con `dashboardUID`), solo si hay `GRAFANA_TOKEN` o `GRAFANA_PASSWORD`; usa la anotacion integrada de cada dashboard.

## Parametros de escala

- `--n` hasta 500+. Timeouts del exp2 crecen con N (`--time-per-msg`, defecto +2-3 s por mensaje sobre 10) o fijelos con `--timeout`.
- Exp1: el SLA es proporcional a N en demo: `max(120, N*delay/replicas_max*1.5 + 60)` (`--sla-factor`); alternativas `--sla-per-msg 0.6` o `--sla 300`.

## Si algo se interrumpe

Ctrl-C (o error) restaura automaticamente las Lambdas (FORCE_FAIL y FAIL_RATE); los pods muertos los repone el Deployment. Para verificar o forzar: `python -m runner restore --list` y `python -m runner restore`.

## Al final

Se imprime la tabla PASS/FAIL, se guarda `reports/<run>/report.{md,json}` y se agrega una seccion "Prueba <n>" a `experiments/RESULTADOS.md` (antes de la plantilla; `--no-resultados` para omitirlo, `--resultados <ruta>` para otro archivo). Complete a mano "Acciones derivadas".
