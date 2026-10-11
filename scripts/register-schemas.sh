#!/usr/bin/env bash
# Registra en Apicurio Registry (grupo "voltera") un esquema JSON por cada mensaje de mesh/asyncapi.yaml
# (13 eventos; artifactId = nombre del mensaje; payload con $ref resueltos). Idempotente: usa
# ifExists=FIND_OR_CREATE_VERSION (mismo contenido => no crea versión nueva). El registro es en memoria:
# vuelve a ejecutarlo si el pod de Apicurio se reinicia.
#
# Uso: scripts/register-schemas.sh [--mode port-forward|pod] [--dry-run]
#   port-forward (defecto): kubectl port-forward svc/apicurio-registry y curl LOCAL.
#   pod: un pod efímero curlimages/curl dentro del clúster (no asume curl en imágenes de Kafka).
#   --dry-run: solo imprime el script de curls generado.
# Requiere ruby (viene con macOS) y kubectl con contexto al clúster (salvo --dry-run).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC="${ASYNCAPI_FILE:-$ROOT/mesh/asyncapi.yaml}"
NS="${KAFKA_NAMESPACE:-kafka}"
GROUP="${REGISTRY_GROUP:-voltera}"
MODE="port-forward"; DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2;;
    --dry-run) DRY=1; shift;;
    *) echo "Opción desconocida: $1" >&2; exit 2;;
  esac
done

# Genera un script sh con un curl por esquema. Usa $BASE (URL base de la API v3) definida por quien lo ejecuta.
gen() {
  ruby -ryaml -rjson - "$SPEC" "$GROUP" <<'RUBY'
spec = YAML.load_file(ARGV[0]); group = ARGV[1]
schemas = spec["components"]["schemas"]
resolve = lambda do |n, seen = []|
  if n.is_a?(Hash)
    if n["$ref"]
      name = n["$ref"].split("/").last
      raise "ref circular #{name}" if seen.include?(name)
      resolve.call(schemas.fetch(name), seen + [name])
    else
      n.each_with_object({}) { |(k, v), h| h[k] = resolve.call(v, seen) }
    end
  elsif n.is_a?(Array) then n.map { |x| resolve.call(x, seen) }
  else n end
end
sq = "'"
quote = lambda { |t| sq + t.gsub(sq, sq + "\\" + sq + sq) + sq }
puts "set -u"
puts "fail=0"
puts 'curl -sS -o /dev/null -w "grupo ' + group + ': HTTP %{http_code}\n" -X POST "$BASE/groups" -H "Content-Type: application/json" --data-binary ' + quote.call({ groupId: group }.to_json) + ' || true'
spec["components"]["messages"].each do |name, msg|
  payload = { "$schema" => "http://json-schema.org/draft-07/schema#", "title" => name }.merge(resolve.call(msg["payload"]))
  body = { artifactId: name, artifactType: "JSON",
           firstVersion: { content: { content: JSON.generate(payload), contentType: "application/json" } } }
  puts 'code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$BASE/groups/' + group + '/artifacts?ifExists=FIND_OR_CREATE_VERSION" -H "Content-Type: application/json" --data-binary ' + quote.call(body.to_json) + ') || code=000'
  puts 'echo "' + name + ': HTTP $code"; case "$code" in 200|201|204) ;; *) fail=1;; esac'
end
puts "exit $fail"
RUBY
}

SCRIPT="$(gen)"
if [[ $DRY -eq 1 ]]; then
  echo "BASE=<url>/apis/registry/v3"; echo "$SCRIPT"; exit 0
fi

case "$MODE" in
  port-forward)
    PORT="${LOCAL_PORT:-18080}"
    kubectl -n "$NS" port-forward svc/apicurio-registry "$PORT:8080" >/dev/null 2>&1 &
    PF=$!; trap 'kill $PF 2>/dev/null || true' EXIT
    for _ in $(seq 1 20); do curl -fsS "http://localhost:$PORT/apis/registry/v3/system/info" >/dev/null 2>&1 && break; sleep 1; done
    BASE="http://localhost:$PORT/apis/registry/v3" bash -c "$SCRIPT"
    ;;
  pod)
    printf 'BASE=%s\n%s\n' "http://apicurio-registry.$NS.svc:8080/apis/registry/v3" "$SCRIPT" |
      kubectl -n "$NS" run "register-schemas-$$" --rm -i --restart=Never --quiet \
        --image=curlimages/curl:8.10.1 --command -- sh -s
    ;;
  *) echo "--mode debe ser port-forward o pod" >&2; exit 2;;
esac
