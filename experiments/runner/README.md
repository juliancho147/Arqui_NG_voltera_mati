# Runner de la experimentacion 2 (Voltera)

```bash
cd experiments/runner
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                      # tests locales (moto + kubectl simulado), sin credenciales

export AWS_PROFILE=<perfil> AWS_REGION=us-east-1
.venv/bin/python -m runner exp1 --dry-run       # plan sin llamar a AWS ni kubectl
.venv/bin/python -m runner exp1 --n 10          # config via `terraform output -json` de infra/terraform/base (+ ephemeral/platform)
.venv/bin/python -m runner exp2 --config salidas.json --yes
.venv/bin/python -m runner restore [--list]     # revierte fallos inyectados pendientes (bitacora en experiments/reports/.runner-changes.json)
```

Reportes: `experiments/reports/<fecha-hora>-<exp>/report.{json,md}`. Exp2/Exp3 piden confirmacion (o `--yes`) y solo actuan sobre recursos
cuyo nombre empieza con el prefijo (`voltera-exp2-`, `--prefix`). El config JSON acepta la salida cruda de `terraform output -json`
y una clave `runner` con overrides (`app_namespace`, `kafka_namespace`, `deployment`, `scaledobject`, `kube_context`, ...).
Estados por criterio: PASS, FAIL, MANUAL (paso que el runner no puede verificar), SKIP.

Notas: el caso B del Exp. 2 espera `maxReceiveCount x visibilityTimeout` de la cola de comprobantes (180 s por defecto, ~9 min);
con el `experiment.tfvars.example` de base (40 s) llega a la DLQ en ~2 min. El runner lee el valor real de la cola.
Apicurio: el runner intenta `curl` desde el pod Kafka (no verificado que la imagen lo traiga); si falla, queda MANUAL
(alternativa: pod efimero con curl o port-forward, o scripts/register-schemas.sh cuando exista).
