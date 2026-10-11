#!/usr/bin/env bash
# Empaqueta las Lambdas en services/_dist/<nombre>/ (handler.py + voltera_common + pydantic + confluent-kafka arm64).
# Powertools NO se vendoriza: viene del layer (variable powertools_layer_arn de Terraform base).
# Uso:  services/build.sh [servicio ...]      luego:  terraform plan -var services_dir=$PWD/services/_dist
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../libs/voltera_common/voltera_common"
DIST="$HERE/_dist"
ALL=(ms-orchestrator-billing outbox-relay ms-tarifas ms-calculo-consumo-neto ms-facturacion ms-comprobante-factura)
TARGETS=("${@:-${ALL[@]}}")
PIP_ARGS=(--quiet --only-binary=:all: --platform manylinux_2_28_aarch64 --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 --abi cp312)
for s in "${TARGETS[@]}"; do
  out="$DIST/$s"; rm -rf "$out"; mkdir -p "$out"
  cp "$HERE/$s/handler.py" "$out/"
  cp -R "$LIB" "$out/voltera_common"; find "$out" -name __pycache__ -prune -exec rm -rf {} +
  pkgs=("pydantic>=2.6")
  case "$s" in ms-orchestrator-billing) ;; *) pkgs+=("confluent-kafka>=2.4");; esac
  python3 -m pip install "${PIP_ARGS[@]}" --target "$out" "${pkgs[@]}"
  echo "listo: $out ($(du -sh "$out" | cut -f1))"
done
