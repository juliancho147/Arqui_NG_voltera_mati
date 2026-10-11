#!/usr/bin/env bash
# Imprime el bootstrap (hostname del NLB interno:9094) del listener "vpc" del clúster Kafka "billing".
# Es el valor para la variable kafka_bootstrap_servers del stack BASE (outbox-relay). Solo lectura.
set -euo pipefail
NS="${KAFKA_NAMESPACE:-kafka}"
HOST="$(kubectl -n "$NS" get svc -l strimzi.io/cluster=billing,strimzi.io/kind=Kafka \
  -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.status.loadBalancer.ingress[0].hostname}{end}')"
if [[ -z "$HOST" ]]; then
  echo "El NLB interno aún no tiene hostname (tarda 2-5 min tras crear el Kafka 'billing')." >&2
  exit 1
fi
echo "${HOST}:9094"
