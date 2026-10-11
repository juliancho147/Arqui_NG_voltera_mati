"""Event Mesh: lectura de Kafka via `kubectl exec` (consola de Kafka) y validacion contra mesh/asyncapi.yaml."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import ASYNCAPI_PATH
from .context import Context
from .kube import KubeError

KAFKA_BIN = "/opt/kafka/bin"
BOOTSTRAP_LOCAL = "localhost:9092"

HAPPY_PATH = ["TarifaValidada", "CargoEnergeticoCalculado", "FacturaEmitida", "NotificacionRegistrada", "FacturaNotificada"]
REJECTION_PATHS = {
    "TarifaRechazada": ["TarifaRechazada"],
    "CalculoDeCargoRechazado": ["TarifaValidada", "CalculoDeCargoRechazado"],
    "EmisionDeFacturaRechazada": ["TarifaValidada", "CargoEnergeticoCalculado", "EmisionDeFacturaRechazada"],
}
CANONICAL_ORDER = ["TarifaValidada", "TarifaRechazada", "CargoEnergeticoCalculado", "CalculoDeCargoRechazado", "FacturaEmitida",
                   "EmisionDeFacturaRechazada", "NotificacionRegistrada", "NotificacionFallida", "FacturaNotificada"]


@dataclass
class Record:
    partition: int | None
    offset: int | None
    key: str | None
    headers: dict[str, str]
    value: dict | None
    raw: str

    @property
    def id(self) -> str | None:
        return (self.value or {}).get("id")


def type_to_name(ce_type: str) -> str:
    """com.voltera.facturacion.tarifa-validada.v1 -> TarifaValidada"""
    m = re.match(r"^com\.voltera\.facturacion\.(.+)\.v\d+$", ce_type or "")
    return "".join(p.capitalize() for p in m.group(1).split("-")) if m else ce_type


def parse_console_line(line: str) -> Record | None:
    """Linea de kafka-console-consumer con print.partition/offset/headers/key: 'Partition:0\\tOffset:3\\th:v,h2:v2\\tkey\\t{json}'."""
    line = line.rstrip("\n")
    if not line.strip() or "{" not in line:
        return None
    parts = line.split("\t")
    raw = parts[-1]
    try:
        value = json.loads(raw)
    except ValueError:
        value = None
    part = off = None
    key = None
    headers: dict[str, str] = {}
    for p in parts[:-1]:
        if p.startswith("Partition:"):
            part = int(p.split(":", 1)[1])
        elif p.startswith("Offset:"):
            off = int(p.split(":", 1)[1])
        elif re.match(r"^[A-Za-z0-9_-]+:[^\t]*(,[A-Za-z0-9_-]+:[^\t]*)*$", p) and ":" in p and not p.startswith("CreateTime"):
            for kv in p.split(","):
                k, _, v = kv.partition(":")
                headers[k] = v
    if len(parts) >= 2 and parts[-2] and ":" not in parts[-2]:
        key = parts[-2]
    return Record(part, off, key, headers, value, raw)


def kafka_pod(ctx: Context, cluster: str) -> str:
    res = ctx.kube.run(["get", "pods", "-n", ctx.cfg.kafka_namespace, "-l", f"strimzi.io/cluster={cluster},strimzi.io/kind=Kafka",
                        "-o", "jsonpath={.items[0].metadata.name}"])
    name = res.stdout.strip()
    if not name:
        raise KubeError(f"no hay pod de Kafka para el cluster '{cluster}' en {ctx.cfg.kafka_namespace}")
    return name


def consume(ctx: Context, cluster: str, topic: str, *, partition: int | None = None, offset: int | None = None,
            max_messages: int | None = None, timeout_ms: int = 20000) -> list[Record]:
    """Lee un topico sin grupo de consumo propio (no afecta a los consumidores reales). Por defecto desde el inicio."""
    pod = kafka_pod(ctx, cluster)
    cmd = [f"{KAFKA_BIN}/kafka-console-consumer.sh", "--bootstrap-server", BOOTSTRAP_LOCAL, "--topic", topic,
           "--property", "print.partition=true", "--property", "print.offset=true", "--property", "print.headers=true",
           "--property", "print.key=true", "--timeout-ms", str(timeout_ms)]
    if partition is not None:
        cmd += ["--partition", str(partition), "--offset", str(offset or 0)]
    else:
        cmd += ["--from-beginning"]
    if max_messages:
        cmd += ["--max-messages", str(max_messages)]
    res = ctx.kube.exec(ctx.cfg.kafka_namespace, pod, cmd, timeout=timeout_ms / 1000 + 60, check=False)
    recs = [r for r in (parse_console_line(l) for l in res.stdout.splitlines()) if r]
    if res.returncode != 0 and not recs and "TimeoutException" not in res.stderr:
        raise KubeError(f"kafka-console-consumer fallo: {res.stderr.strip()[:300]}")
    return recs


def produce(ctx: Context, cluster: str, topic: str, records: list[Record], *, chunk: int = 100) -> dict:
    """Reenvia registros YA EXISTENTES (misma clave, mismo valor, mismo CloudEvent id) a un topico con kafka-console-producer
    dentro del broker (`kubectl exec`). Las lineas viajan en base64 por stdin para no depender de quoting.
    Intenta conservar las cabeceras (parse.headers, Kafka >= 3.2); si el producer las rechaza, reintenta sin ellas.
    Devuelve {"enviados": n, "conCabeceras": bool, "pod": ...}. Lanza KubeError si ambos intentos fallan."""
    import base64
    pod = kafka_pod(ctx, cluster)
    sent, with_headers = 0, True
    for i in range(0, len(records), chunk):
        part = records[i:i + chunk]
        for headers in (True, False):
            lines = []
            for r in part:
                key = r.key or (r.value or {}).get("facturaid") or ""
                hdr = ",".join(f"{k}:{v}" for k, v in (r.headers or {}).items()) or "origen:runner"
                lines.append(("\t".join([hdr, key, r.raw]) if headers else "\t".join([key, r.raw])))
            b64 = base64.b64encode(("\n".join(lines) + "\n").encode()).decode()
            props = "--property parse.key=true" + (" --property parse.headers=true" if headers else "")
            script = (f"echo {b64} | base64 -d | {KAFKA_BIN}/kafka-console-producer.sh --bootstrap-server {BOOTSTRAP_LOCAL} "
                      f"--topic {topic} {props}")
            res = ctx.kube.exec(ctx.cfg.kafka_namespace, pod, ["sh", "-c", script], timeout=120, check=False)
            if res.returncode == 0:
                with_headers = with_headers and headers
                sent += len(part)
                break
            if not headers:
                raise KubeError(f"kafka-console-producer fallo: {res.stderr.strip()[:300]}")
    return {"enviados": sent, "conCabeceras": with_headers, "pod": pod, "topic": topic}


def consumer_lag(ctx: Context, cluster: str, group: str) -> int | None:
    """Lag total del grupo (suma de la columna LAG) o None si no se puede leer."""
    try:
        pod = kafka_pod(ctx, cluster)
        res = ctx.kube.exec(ctx.cfg.kafka_namespace, pod, [f"{KAFKA_BIN}/kafka-consumer-groups.sh", "--bootstrap-server", BOOTSTRAP_LOCAL,
                                                             "--describe", "--group", group], timeout=60, check=False)
    except KubeError:
        return None
    lines = [l.split() for l in res.stdout.splitlines() if l.strip()]
    header = next((l for l in lines if "LAG" in l), None)
    if not header:
        return None
    idx = header.index("LAG")
    total, seen = 0, False
    for l in lines:
        if len(l) > idx and l is not header and l[idx].isdigit():
            total += int(l[idx])
            seen = True
    return total if seen else None


def expected_types(state: str | None, observed: set[str]) -> list[str]:
    """Eventos esperados por factura segun su estado terminal en DynamoDB (FACT#)."""
    if state == "OK":
        return list(HAPPY_PATH)
    if state == "RECHAZADA":
        for rej, path in REJECTION_PATHS.items():
            if rej in observed:
                return list(path)
        return ["<evento de rechazo>"]
    if state == "FALLIDA":
        return HAPPY_PATH[:4] + ["NotificacionFallida"]
    return list(HAPPY_PATH)


# ----------------------------------------------------------------------------- catalogo AsyncAPI
@dataclass
class Catalog:
    schemas: dict = field(default_factory=dict)
    by_type: dict[str, dict] = field(default_factory=dict)  # ce type -> schema ya sin $ref

    def validate(self, event: dict) -> list[str]:
        from jsonschema import Draft7Validator
        schema = self.by_type.get(event.get("type", ""))
        if schema is None:
            return [f"tipo no descrito en el catalogo: {event.get('type')}"]
        return sorted(f"{'/'.join(map(str, e.absolute_path)) or '<raiz>'}: {e.message}" for e in Draft7Validator(schema).iter_errors(event))


def _inline(node, schemas: dict, depth: int = 0):
    if depth > 20:
        raise ValueError("referencias circulares en el catalogo")
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"]
            m = re.match(r"^#/components/(schemas|messages)/(.+)$", ref)
            if not m:
                raise ValueError(f"$ref no soportado: {ref}")
            return _inline(copy.deepcopy(schemas[m.group(2)] if m.group(1) == "schemas" else schemas["__messages__"][m.group(2)]),
                           schemas, depth + 1)
        return {k: _inline(v, schemas, depth + 1) for k, v in node.items() if k != "format"}
    if isinstance(node, list):
        return [_inline(v, schemas, depth + 1) for v in node]
    return node


def load_catalog(path: Path | str = ASYNCAPI_PATH) -> Catalog:
    import yaml
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    comps = doc.get("components", {})
    schemas = dict(comps.get("schemas", {}))
    schemas["__messages__"] = comps.get("messages", {})
    cat = Catalog(schemas={k: v for k, v in schemas.items() if k != "__messages__"})
    for name, msg in comps.get("messages", {}).items():
        payload = _inline(msg["payload"], schemas)
        const = None
        for part in payload.get("allOf", []):
            const = (part.get("properties", {}).get("type") or {}).get("const") or const
        if const:
            cat.by_type[const] = payload
    return cat


def fetch_registry_artifacts(ctx: Context) -> list[str] | None:
    """Intenta listar artefactos de Apicurio desde un pod de Kafka (curl). None = no accesible (paso manual)."""
    try:
        pod = kafka_pod(ctx, ctx.cfg.kafka_cluster_billing)
        url = ctx.cfg.schema_registry_url.rstrip("/") + "/search/artifacts"
        res = ctx.kube.exec(ctx.cfg.kafka_namespace, pod, ["curl", "-s", "-m", "10", url], timeout=30, check=False)
        if res.returncode != 0 or not res.stdout.strip().startswith("{"):
            return None
        return [a.get("artifactId", "?") for a in json.loads(res.stdout).get("artifacts", [])]
    except (KubeError, ValueError):
        return None
