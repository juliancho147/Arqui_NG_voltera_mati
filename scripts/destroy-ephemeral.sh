#!/usr/bin/env bash
# Cierre SEGURO del stack efímero (exp2-eda). NO se ejecuta automáticamente.
#
# Orden:
#   0. Verifica que la Lambda outbox-relay (base) ya NO esté adjunta a la VPC (si no, sus ENI bloquean el borrado de la VPC).
#   1. Borra recursos de Strimzi y PVC primero (para que el CSI borre los EBS y el controlador borre el NLB).
#   2. Espera a que desaparezcan PVC, servicios LoadBalancer y NLB del clúster.
#   3. terraform destroy de platform y luego de cluster.
#   4. Lista EBS / balanceadores / ENI / log groups que pudieran quedar con tag del proyecto.
#
# Uso: scripts/destroy-ephemeral.sh [--yes] [--skip-relay-check]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EPH="$ROOT/infra/terraform/ephemeral"
REGION="${AWS_REGION:-us-east-1}"
KAFKA_NS="${KAFKA_NAMESPACE:-kafka}"
APP_NS="${APP_NAMESPACE:-voltera}"
TAG_KEY="${TAG_KEY:-proyecto}"
TAG_VAL="${TAG_VALUE:-voltera}"
LAMBDA_PREFIX="${LAMBDA_PREFIX:-voltera-exp2-}"
YES=0; SKIP_RELAY=0
for a in "$@"; do case "$a" in --yes) YES=1;; --skip-relay-check) SKIP_RELAY=1;; *) echo "Opción desconocida: $a"; exit 2;; esac; done

log() { printf '\n== %s\n' "$*"; }
tf_out() { terraform -chdir="$EPH/cluster" output -raw "$1" 2>/dev/null; }

CLUSTER="$(tf_out cluster_name || true)"; CLUSTER="${CLUSTER:-voltera-exp2-eph}"
RELAY_SG="$(tf_out relay_security_group_id || true)"

echo "Región: $REGION | Clúster: $CLUSTER | Tag de proyecto: $TAG_KEY=$TAG_VAL"
if [[ $YES -ne 1 ]]; then
  read -r -p "Esto DESTRUYE el stack efímero. Escribe 'destruir' para continuar: " ans
  [[ "$ans" == "destruir" ]] || { echo "Cancelado."; exit 1; }
fi

# 0. Lambda relay fuera de la VPC
if [[ $SKIP_RELAY -ne 1 ]]; then
  log "0. Comprobando que ninguna Lambda ${LAMBDA_PREFIX}* esté adjunta a la VPC"
  ATT="$(aws lambda list-functions --region "$REGION" \
          --query "Functions[?starts_with(FunctionName, '${LAMBDA_PREFIX}') && VpcConfig.VpcId!=null && VpcConfig.VpcId!=''].FunctionName" --output text 2>/dev/null || true)"
  if [[ -n "$ATT" ]]; then
    echo "ABORTADO: siguen adjuntas a la VPC estas Lambdas: $ATT"
    echo "          En el stack base quita el vpc_config de TODAS (lambda_subnet_ids/security_group_ids = []),"
    echo "          haz 'terraform apply' allí y espera ~10-30 min a que se liberen las ENI (o usa --skip-relay-check)."
    exit 3
  fi
fi

# 1-2. Kubernetes
if kubectl --request-timeout=15s get ns "$KAFKA_NS" >/dev/null 2>&1; then
  log "1. Borrando carga de trabajo y recursos de Strimzi"
  kubectl -n "$APP_NS" delete scaledobject,deployment --all --wait=true --timeout=120s 2>&1 || true
  kubectl -n "$KAFKA_NS" delete kafkamirrormaker2,kafkatopic --all --wait=true --timeout=180s 2>&1 || true
  kubectl -n "$KAFKA_NS" delete kafka,kafkanodepool --all --wait=true --timeout=300s 2>&1 || true
  kubectl -n "$KAFKA_NS" delete deployment apicurio-registry --ignore-not-found --wait=true --timeout=60s 2>&1 || true
  log "   Borrando PVC restantes (el StorageClass tiene reclaimPolicy Delete -> el EBS se elimina)"
  kubectl -n "$KAFKA_NS" delete pvc --all --wait=true --timeout=300s 2>&1 || true
  log "2. Esperando que desaparezcan los Services tipo LoadBalancer"
  for i in $(seq 1 30); do
    n="$(kubectl get svc -A -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.name}{"\n"}{end}' 2>/dev/null | grep -c . || true)"
    [[ "$n" == "0" ]] && break; echo "   quedan $n servicios LoadBalancer..."; sleep 10
  done
  for i in $(seq 1 30); do
    n="$(aws elbv2 describe-load-balancers --region "$REGION" --query 'length(LoadBalancers)' --output text 2>/dev/null || echo 0)"
    arns="$(aws elbv2 describe-load-balancers --region "$REGION" --query 'LoadBalancers[].LoadBalancerArn' --output text 2>/dev/null)"
    mine=0
    if [[ -n "$arns" ]]; then
      mine="$(aws elbv2 describe-tags --region "$REGION" --resource-arns $arns \
        --query "length(TagDescriptions[?Tags[?Key=='kubernetes.io/cluster/$CLUSTER']])" --output text 2>/dev/null || echo 0)"
    fi
    [[ "$mine" == "0" ]] && break; echo "   quedan $mine NLB del clúster..."; sleep 10
  done
else
  echo "Clúster no accesible o ya borrado: se omiten los pasos de Kubernetes."
fi

# 3. Terraform
AUTO=(); [[ $YES -eq 1 ]] && AUTO=(-auto-approve)
log "3a. terraform destroy (platform)"
terraform -chdir="$EPH/platform" destroy -input=false "${AUTO[@]}" || echo "AVISO: destroy de platform falló o el clúster ya no existe; continúo."
log "3b. terraform destroy (cluster)"
terraform -chdir="$EPH/cluster" destroy -input=false "${AUTO[@]}"
RC=$?

# 4. Huérfanos (solo lectura)
log "4. Verificación de huérfanos (solo listado; nada se borra aquí)"
LEFT=0; TMPF="$(mktemp)"; trap 'rm -f "$TMPF"' EXIT
echo "-- Volúmenes EBS con tag $TAG_KEY=$TAG_VAL o del clúster:"
V1="$(aws ec2 describe-volumes --region "$REGION" --filters "Name=tag:$TAG_KEY,Values=$TAG_VAL" \
   --query 'Volumes[].[VolumeId,State,Size,Tags[?Key==`stack`]|[0].Value]' --output text)"
V2="$(aws ec2 describe-volumes --region "$REGION" --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER" \
   --query 'Volumes[].[VolumeId,State,Size]' --output text)"
echo "${V1:-  (ninguno)}"; echo "${V2:-}"; [[ -n "$V1$V2" ]] && LEFT=1
echo "-- Load balancers (v2) con tag del proyecto o del clúster:"
ARNS="$(aws elbv2 describe-load-balancers --region "$REGION" --query 'LoadBalancers[].LoadBalancerArn' --output text 2>/dev/null)"
if [[ -n "$ARNS" ]]; then
  aws elbv2 describe-tags --region "$REGION" --resource-arns $ARNS \
    --query "TagDescriptions[?Tags[?Key=='$TAG_KEY' && Value=='$TAG_VAL'] || Tags[?Key=='kubernetes.io/cluster/$CLUSTER']].ResourceArn" --output text >"$TMPF"
  cat "$TMPF"; [[ -s "$TMPF" ]] && LEFT=1
else echo "  (ninguno)"; fi
echo "-- Load balancers clásicos del clúster:"
aws elb describe-load-balancers --region "$REGION" --query 'LoadBalancerDescriptions[].LoadBalancerName' --output text 2>/dev/null || true
echo "-- ENI en VPCs con tag del proyecto (relay/NLB residuales):"
aws ec2 describe-network-interfaces --region "$REGION" --filters "Name=tag:$TAG_KEY,Values=$TAG_VAL" \
  --query 'NetworkInterfaces[].[NetworkInterfaceId,Status,Description]' --output text
[[ -n "$RELAY_SG" ]] && aws ec2 describe-network-interfaces --region "$REGION" --filters "Name=group-id,Values=$RELAY_SG" \
  --query 'NetworkInterfaces[].NetworkInterfaceId' --output text 2>/dev/null
echo "-- Clústeres EKS restantes:"; aws eks list-clusters --region "$REGION" --output text
echo "-- Log groups de Container Insights del clúster:"
aws logs describe-log-groups --region "$REGION" --log-group-name-prefix "/aws/containerinsights/$CLUSTER" --query 'logGroups[].logGroupName' --output text

if [[ $LEFT -eq 1 || $RC -ne 0 ]]; then
  echo; echo "ATENCIÓN: pueden quedar recursos con costo. Revisa el listado y bórralos manualmente"
  echo "  (p. ej. aws ec2 delete-volume --volume-id vol-xxxx, aws elbv2 delete-load-balancer --load-balancer-arn ...)."
  exit 1
fi
echo; echo "Stack efímero destruido y sin huérfanos detectados."
