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
| Exp2 caida de un dependiente | `voltera-exp2-aislamiento` | `python -m runner demo exp2 --n 200 --case B` (comprobante) · `--case A` (ms-tarifas) |
| Exp3 cero perdida ante fallos | `voltera-exp3-cero-perdida` | `python -m runner demo exp3 --n 300 --delay 2 --kill-pods 2 --fail-rate 0.25 --fault-window 90` |

Ensayo sin tocar nada: agregue `--dry-run`. Sin pausas: `--no-pause`. Sin confirmacion de cambios: `--yes`.

## Que pasa en cada demo

Cada fase muestra un banner con la hora y espera **Enter** (sincronice con el dashboard). Antes de cada llamada se imprime el comando (`$ aws ...`, `$ kubectl ...`; las lecturas repetitivas salen una vez).

- **Exp1:** estado inicial (1 replica) -> disparo (seed + CierreDeMes) -> absorcion (KEDA sube replicas, lag crece y drena) -> recuperacion (vuelta a 1 replica) -> veredicto.
- **Exp2:** estado inicial -> **fallo inyectado** (FORCE_FAIL en el dependiente; `--fault-mode concurrency` para concurrencia 0) -> disparo -> **acumulacion** (cola/DLQ crecen; caso B: el resto sigue facturando; caso A: reintentos de Step Functions y luego DLQ) -> **recuperacion** (se restaura la Lambda y se hace redrive de la DLQ; drena) -> veredicto.
- **Exp3:** estado inicial -> disparo -> **fallo_pod** (se matan pods de process-billing con mensajes en vuelo) -> **fallo_lambda** (a mitad del lote: FAIL_RATE en ms-facturacion y ms-comprobante-factura caido) -> recuperacion -> veredicto con `inyectadas = emitidas + rechazadas + DLQ` y cero duplicados.

## Marcas para anotar el dashboard

Por cada fase se registra, a la hora en que se pulsa Enter:
1. `experiments/reports/<run>/marcas.json` (fase, descripcion, hora local, epoch ms).
2. Metrica CloudWatch `FaseExperimento` (namespace `Voltera/Exp2`, dimensiones `experimento` y `fase`, valor 1). Puede graficarse o usarse como consulta de anotaciones del datasource CloudWatch.
3. Anotacion de Grafana (`POST /api/annotations` con `dashboardUID`), solo si hay `GRAFANA_TOKEN` o `GRAFANA_PASSWORD`; usa la anotacion integrada de cada dashboard.

## Parametros de escala

- `--n` hasta 500+. Timeouts de exp2/exp3 crecen con N (`--time-per-msg`, defecto +2-3 s por mensaje sobre 10) o fijelos con `--timeout`.
- Exp1: el SLA es proporcional a N en demo: `max(120, N*delay/replicas_max*1.5 + 60)` (`--sla-factor`); alternativas `--sla-per-msg 0.6` o `--sla 300`.

## Si algo se interrumpe

Ctrl-C (o error) restaura automaticamente las Lambdas. Para verificar o forzar: `python -m runner restore --list` y `python -m runner restore`.

## Al final

Se imprime la tabla PASS/FAIL, se guarda `reports/<run>/report.{md,json}` y se agrega una seccion "Prueba <n>" a `experiments/RESULTADOS.md` (antes de la plantilla; `--no-resultados` para omitirlo, `--resultados <ruta>` para otro archivo). Complete a mano "Acciones derivadas".
