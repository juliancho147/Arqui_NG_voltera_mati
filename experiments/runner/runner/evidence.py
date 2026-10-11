"""Recoleccion de evidencia (solo lectura): DynamoDB, SQS y Step Functions."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from boto3.dynamodb.conditions import Key

from .context import Context

COUNTER_KEY = "__CONSECUTIVO__"


def ciclo_of(factura_id: str) -> str:
    """facturaId = <cicloId>-F0001 (ver experiments/seed)."""
    return factura_id.rsplit("-F", 1)[0]


def _num(v: Any) -> int:
    return int(v) if v is not None else 0


# ----------------------------------------------------------------------------- SQS
def queue_state(ctx: Context, url: str) -> dict:
    a = ctx.client("sqs").get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
    return {"visibles": _num(a.get("ApproximateNumberOfMessages")), "enVuelo": _num(a.get("ApproximateNumberOfMessagesNotVisible")),
            "demorados": _num(a.get("ApproximateNumberOfMessagesDelayed")), "visibilityTimeout": _num(a.get("VisibilityTimeout"))}


def queue_total(st: dict) -> int:
    return st["visibles"] + st["enVuelo"] + st["demorados"]


def peek_queue(ctx: Context, url: str, max_messages: int = 200, rounds: int | None = None, patience: int = 6) -> list[dict]:
    """Lee mensajes visibles SIN consumirlos (VisibilityTimeout=0), deduplicando por MessageId.

    SQS devuelve una muestra aleatoria: se sigue leyendo hasta `patience` rondas seguidas sin mensajes nuevos
    (o `rounds`, por defecto proporcional a max_messages) para cubrir colas grandes (N de 500+)."""
    sqs = ctx.client("sqs")
    seen: dict[str, dict] = {}
    rounds = rounds or max(6, -(-max_messages // 10) * 4)
    idle = 0
    for _ in range(rounds):
        r = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, VisibilityTimeout=0, WaitTimeSeconds=0,
                                MessageAttributeNames=["All"])
        new = [m for m in r.get("Messages", []) if m["MessageId"] not in seen]
        for m in new:
            seen[m["MessageId"]] = m
        idle = 0 if new else idle + 1
        if idle >= patience or len(seen) >= max_messages:
            break
    out = []
    for m in seen.values():
        try:
            body = json.loads(m["Body"])
        except (ValueError, TypeError):
            body = {"_raw": m["Body"]}
        out.append({"messageId": m["MessageId"], "body": body, "attrs": m.get("MessageAttributes", {})})
    return out


def dlq_factura_ids(ctx: Context, queue_key: str, ciclo: str, expected: int = 0) -> tuple[set[str], int, list[dict]]:
    """(facturaIds de este ciclo en la DLQ, total aproximado de mensajes en la DLQ, muestra de mensajes).
    `expected` = N esperado: ajusta cuantos mensajes se intentan leer."""
    q = ctx.cfg.queue(queue_key)
    msgs = peek_queue(ctx, q["dlq_url"], max_messages=max(200, expected + 50))
    ids = {m["body"].get("facturaId") for m in msgs if m["body"].get("cicloId") == ciclo and m["body"].get("facturaId")}
    return ids, queue_total(queue_state(ctx, q["dlq_url"])), msgs[:5]


def dlq_covers(ids, dlq_ids: set[str], aprox: int, tolerance: float = 0.95) -> bool:
    """True si todos los `ids` estan en la DLQ. Con N grande (>100) la lectura es una muestra: se acepta >= 95 % visto y
    conteo aproximado de la DLQ >= N."""
    ids = set(ids)
    if ids <= dlq_ids:
        return True
    return len(ids) > 100 and aprox >= len(ids) and len(ids & dlq_ids) >= tolerance * len(ids)


# ----------------------------------------------------------------------------- DynamoDB
def _query_all(table, **kw) -> list[dict]:
    items, kwargs = [], dict(kw)
    while True:
        r = table.query(**kwargs)
        items += r.get("Items", [])
        if "LastEvaluatedKey" not in r:
            return items
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def _scan_all(table, **kw) -> list[dict]:
    items, kwargs = [], dict(kw)
    while True:
        r = table.scan(**kwargs)
        items += r.get("Items", [])
        if "LastEvaluatedKey" not in r:
            return items
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def injected_ids(ctx: Context, ciclo: str) -> list[str]:
    return sorted(i["facturaId"] for i in _query_all(ctx.table("transacciones"), KeyConditionExpression=Key("cicloId").eq(ciclo)))


def ciclo_meta(ctx: Context, ciclo: str) -> dict:
    it = ctx.table("process-billing").get_item(Key={"cicloId": ciclo, "sk": "META"}, ConsistentRead=True).get("Item") or {}
    return {k: (int(v) if hasattr(v, "as_integer_ratio") and k != "estado" else v) for k, v in it.items() if k != "sk"}


def prefixed_items(ctx: Context, ciclo: str, prefix: str) -> list[dict]:
    return _query_all(ctx.table("process-billing"), KeyConditionExpression=Key("cicloId").eq(ciclo) & Key("sk").begins_with(prefix),
                      ConsistentRead=True)


def fact_states(ctx: Context, ciclo: str) -> dict[str, str]:
    return {i["sk"][len("FACT#"):]: i.get("estado") for i in prefixed_items(ctx, ciclo, "FACT#")}


def dedup_states(ctx: Context, ciclo: str) -> dict[str, str]:
    return {i["sk"][len("DEDUP#"):]: i.get("estado") for i in prefixed_items(ctx, ciclo, "DEDUP#")}


def _idem_records(ctx: Context, table_key: str) -> list[dict]:
    """Registros de idempotencia de Powertools. OJO: la PK `facturaId` guarda '<funcion>#<hash>', no el facturaId plano;
    el facturaId real esta dentro del JSON de `data` (la respuesta guardada)."""
    out = []
    for it in _scan_all(ctx.table(table_key)):
        if it.get("facturaId") == COUNTER_KEY:
            continue
        data = it.get("data")
        try:
            parsed = json.loads(data) if isinstance(data, str) else (data or {})
        except ValueError:
            parsed = {}
        out.append({"key": it.get("facturaId"), "status": it.get("status"), "data": parsed})
    return out


def facturas_emitidas(ctx: Context, ciclo: str) -> list[dict]:
    """Facturas aprobadas (COMPLETED) del ciclo segun la idempotencia de ms-facturacion."""
    res = []
    for r in _idem_records(ctx, "idem-facturacion"):
        d = r["data"]
        fid = d.get("facturaId")
        if r["status"] == "COMPLETED" and d.get("aprobado") and fid and (d.get("cicloId") == ciclo or ciclo_of(fid) == ciclo):
            res.append({"facturaId": fid, "numeroFactura": d.get("numeroFactura"), "key": r["key"]})
    return res


def comprobantes_notificados(ctx: Context, ciclo: str) -> list[str]:
    return [r["data"]["facturaId"] for r in _idem_records(ctx, "idem-comprobante")
            if r["status"] == "COMPLETED" and r["data"].get("facturaId") and ciclo_of(r["data"]["facturaId"]) == ciclo]


def consecutivo(ctx: Context) -> int | None:
    it = ctx.table("idem-facturacion").get_item(Key={"facturaId": COUNTER_KEY}, ConsistentRead=True).get("Item")
    return int(it["consecutivo"]) if it and "consecutivo" in it else None


# ----------------------------------------------------------------------------- Step Functions
def sfn_failed_attempts(ctx: Context, since: float, limit: int = 3) -> dict:
    """Intentos fallidos por ejecucion FALLIDA reciente (evidencia de reintentos). Devuelve {} si no es accesible."""
    from datetime import datetime, timezone
    sfn = ctx.client("stepfunctions")
    arn = ctx.cfg.sfn_arn
    out: dict = {"ejecuciones": []}
    execs = sfn.list_executions(stateMachineArn=arn, statusFilter="FAILED", maxResults=50).get("executions", [])
    cutoff = datetime.fromtimestamp(since, tz=timezone.utc)
    for e in [x for x in execs if x["startDate"] >= cutoff][:limit]:
        hist = sfn.get_execution_history(executionArn=e["executionArn"], maxResults=200, reverseOrder=False)["events"]
        fails = [h for h in hist if h["type"] in ("TaskFailed", "LambdaFunctionFailed")]
        out["ejecuciones"].append({"arn": e["executionArn"], "intentosFallidos": len(fails)})
    return out


# ----------------------------------------------------------------------------- contabilidad
@dataclass
class Accounting:
    ciclo: str
    inyectadas: list[str]
    emitidas: dict[str, str] = field(default_factory=dict)      # facturaId -> numeroFactura
    emitidas_duplicadas: list[str] = field(default_factory=list)
    rechazadas: set[str] = field(default_factory=set)
    fallidas: set[str] = field(default_factory=set)
    dlq: set[str] = field(default_factory=set)
    dlq_aprox: int = 0
    dlq_comprobantes: set[str] = field(default_factory=set)
    dlq_comprobantes_aprox: int = 0
    notificadas: set[str] = field(default_factory=set)
    colas: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.inyectadas)

    @property
    def contabilizadas(self) -> set[str]:
        return set(self.emitidas) | self.rechazadas | self.dlq

    @property
    def faltantes(self) -> list[str]:
        return sorted(set(self.inyectadas) - self.contabilizadas)

    @property
    def ajenas(self) -> list[str]:
        return sorted(self.contabilizadas - set(self.inyectadas))

    @property
    def solapadas(self) -> list[str]:
        """Emitida y ademas en DLQ de transacciones (reintento posterior al envio a la DLQ): se cuenta una sola vez."""
        return sorted(set(self.emitidas) & self.dlq)

    @property
    def ecuacion(self) -> str:
        solo_dlq = len(self.dlq - set(self.emitidas) - self.rechazadas)
        return (f"inyectadas({self.n}) = emitidas({len(self.emitidas)}) + rechazadas_negocio({len(self.rechazadas)}) "
                f"+ DLQ({solo_dlq}) -> suma {len(self.emitidas) + len(self.rechazadas) + solo_dlq}")

    @property
    def ecuacion_ok(self) -> bool:
        return not self.faltantes and not self.ajenas

    def resumen(self) -> dict:
        return {"inyectadas": self.n, "emitidas": len(self.emitidas), "rechazadasNegocio": len(self.rechazadas),
                "fallidas": len(self.fallidas), "dlqTransacciones": len(self.dlq), "dlqTransaccionesAprox": self.dlq_aprox,
                "dlqComprobantes": len(self.dlq_comprobantes), "dlqComprobantesAprox": self.dlq_comprobantes_aprox,
                "notificadas": len(self.notificadas), "faltantes": self.faltantes, "ajenas": self.ajenas,
                "emitidasYenDlq": self.solapadas, "emitidasDuplicadas": self.emitidas_duplicadas, "colas": self.colas}


def account(ctx: Context, ciclo: str, inyectadas: list[str] | None = None) -> Accounting:
    acc = Accounting(ciclo, inyectadas if inyectadas is not None else injected_ids(ctx, ciclo))
    seen: dict[str, str] = {}
    for f in facturas_emitidas(ctx, ciclo):
        if f["facturaId"] in seen:
            acc.emitidas_duplicadas.append(f["facturaId"])
        seen[f["facturaId"]] = f["numeroFactura"]
    acc.emitidas = seen
    facts = fact_states(ctx, ciclo)
    acc.rechazadas = {f for f, e in facts.items() if e == "RECHAZADA"}
    acc.fallidas = {f for f, e in facts.items() if e == "FALLIDA"}
    acc.dlq, acc.dlq_aprox, _ = dlq_factura_ids(ctx, "transacciones", ciclo, len(acc.inyectadas))
    acc.dlq_comprobantes, acc.dlq_comprobantes_aprox, _ = dlq_factura_ids(ctx, "comprobantes", ciclo, len(acc.inyectadas))
    acc.notificadas = set(comprobantes_notificados(ctx, ciclo))
    qt, qc = ctx.cfg.queue("transacciones"), ctx.cfg.queue("comprobantes")
    acc.colas = {"transacciones": queue_state(ctx, qt["url"]), "comprobantes": queue_state(ctx, qc["url"])}
    return acc
