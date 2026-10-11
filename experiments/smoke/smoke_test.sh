#!/usr/bin/env bash
# Prueba de humo del stack BASE (sin Kafka): siembra 2 transacciones, envia 2 mensajes a la cola de transacciones
# (lo que haria ms-process-billing) y comprueba que Step Functions -> Lambdas -> cola de comprobantes funciona.
# Cada comando se imprime antes de ejecutarse para que puedas replicarlo a mano.
#
# Uso:   experiments/smoke/smoke_test.sh [CICLO_ID]          (por defecto SMOKE-<fecha-hora>)
#        experiments/smoke/smoke_test.sh --cleanup CICLO_ID  (borra las transacciones sembradas)
# Requiere: credenciales AWS (AWS_PROFILE) y el venv del runner (experiments/runner/.venv) para el seed (boto3).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export AWS_REGION="${AWS_REGION:-us-east-1}" AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
P=voltera-exp2
PY="${PYTHON:-$ROOT/experiments/runner/.venv/bin/python}"
Q_TX="https://sqs.$AWS_REGION.amazonaws.com/$(aws sts get-caller-identity --query Account --output text)/$P-transacciones"
Q_COMP="${Q_TX%transacciones}comprobantes"
SM_ARN="arn:aws:states:$AWS_REGION:$(aws sts get-caller-identity --query Account --output text):stateMachine:$P-facturacion"

run() { printf '\n\033[1;36m$ %s\033[0m\n' "$*"; "$@"; }

if [ "${1:-}" = "--cleanup" ]; then
  C="${2:?indica el CICLO_ID}"
  for i in 1 2; do
    run aws dynamodb delete-item --table-name "$P-transacciones" \
      --key "{\"cicloId\":{\"S\":\"$C\"},\"facturaId\":{\"S\":\"$C-F000$i\"}}"
  done
  exit 0
fi

CICLO="${1:-SMOKE-$(date +%Y%m%d%H%M%S)}"
echo "Ciclo de prueba: $CICLO"

echo; echo "== 1. Sembrar 2 transacciones en DynamoDB (tabla $P-transacciones)"
run "$PY" "$ROOT/experiments/seed/seed_transacciones.py" --ciclo-id "$CICLO" --n 2 --periodo 2026-09 --table "$P-transacciones"

echo; echo "== 2. Enviar 2 mensajes a la cola de transacciones (simula la salida de ms-process-billing)"
for i in 1 2; do
  case $i in 1) T=RESIDENCIAL;; 2) T=COMERCIAL;; esac
  BODY="{\"cicloId\":\"$CICLO\",\"facturaId\":\"$CICLO-F000$i\",\"clienteId\":\"CLI-SMOKE\",\"tipoTarifa\":\"$T\",\"periodo\":\"2026-09\",\"ordinal\":$i,\"totalUnidades\":2,\"eventId\":\"smoke-$CICLO-$i\"}"
  run aws sqs send-message --queue-url "$Q_TX" --message-body "$BODY" --query MessageId --output text
done

echo; echo "== 3. Esperar al Pipe y a Step Functions (25 s)"; sleep 25

echo; echo "== 4. Ejecuciones recientes de la maquina de estados"
run aws stepfunctions list-executions --state-machine-arn "$SM_ARN" --max-results 5 \
  --query 'executions[].[name,status,startDate]' --output table

echo; echo "== 5. Salida de la ultima ejecucion (primeros 600 caracteres)"
EX=$(aws stepfunctions list-executions --state-machine-arn "$SM_ARN" --max-results 1 --query 'executions[0].executionArn' --output text)
run aws stepfunctions describe-execution --execution-arn "$EX" --query '[status,output,error,cause]' --output text | cut -c1-600

echo; echo "== 6. Profundidad de colas (comprobantes y DLQ)"
for q in "$P-transacciones" "$P-transacciones-dlq" "$P-comprobantes" "$P-comprobantes-dlq"; do
  U="${Q_TX%$P-transacciones}$q"
  printf '%-34s ' "$q"
  aws sqs get-queue-attributes --queue-url "$U" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes.[ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible]' --output text
done

echo; echo "== 7. Logs recientes de ms-comprobante-factura (ultimos 5 min)"
run aws logs tail "/aws/lambda/$P-ms-comprobante-factura" --since 5m --format short 2>&1 | tail -12

echo; echo "Listo. Grafana: http://localhost:3000  (dashboard 'Voltera Exp2 - Ciclo en vivo', variable cicloId = $CICLO)"
echo "Limpiar los datos sembrados:  experiments/smoke/smoke_test.sh --cleanup $CICLO"
