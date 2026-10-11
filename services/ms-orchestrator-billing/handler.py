"""ms-orchestrator-billing: inicia el cierre de mes y hace el fan-out (Transactional Outbox).

Disparo: EventBridge (CierreDeMes; detail opcional {cicloId, nSolicitudes}) o invocacion directa {cicloId, nSolicitudes}.
1. Lee las transacciones preprocesadas del ciclo (tabla transacciones, PK cicloId) y toma las primeras N.
2. Escribe en la tabla outbox: CicloDeFacturacionIniciado (con total, destino EVENTOS) y un
   ConsumoFacturablePreparado por unidad (destino INGRESO). El outbox-relay los publica a Kafka via DynamoDB Streams.
Los eventId son deterministas (uuid5): un re-disparo del mismo ciclo no duplica el outbox (escritura condicional).
"""
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit

from voltera_common import CICLO_SENTINEL, make_event, maybe_fail

SERVICE = "ms-orchestrator-billing"
logger = Logger(service=SERVICE)
tracer = Tracer(service=SERVICE)
metrics = Metrics(namespace=os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "Voltera/Exp2"), service=SERVICE)

_ddb = None
NAMESPACE = uuid.UUID("6f1c2b0e-3c1d-4a55-9d0b-1f2e3d4c5b6a")
OUTBOX_TTL_SECONDS = 3 * 24 * 3600


def ddb():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb")
    return _ddb


def resolver_parametros(event: dict) -> tuple[str, int]:
    detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
    ciclo = detail.get("cicloId") or event.get("cicloId") or datetime.now(timezone.utc).strftime("CICLO-%Y%m")
    n = detail.get("nSolicitudes") or event.get("nSolicitudes") or os.environ.get("N_SOLICITUDES", "10")
    return str(ciclo), int(n)


def leer_transacciones(ciclo: str, n: int) -> list[dict]:
    table = ddb().Table(os.environ["TABLE_TRANSACCIONES"])
    items: list[dict] = []
    kwargs = {"KeyConditionExpression": Key("cicloId").eq(ciclo)}
    while len(items) < n:
        page = table.query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return items[:n]


def _outbox_item(ev, destino: str) -> dict:
    return {
        "eventId": ev.id, "destino": destino, "tipo": ev.type, "key": ev.facturaid,
        "headers": {"cicloId": ev.cicloid, "facturaId": ev.facturaid},
        "payload": ev.to_json(), "cicloId": ev.cicloid, "facturaId": ev.facturaid,
        "estado": "PENDIENTE", "creadoEn": ev.time,
        os.environ.get("IDEMPOTENCY_TTL_ATTR", "expiresAt"): int(time.time()) + OUTBOX_TTL_SECONDS,
    }


def _put_once(table, item: dict) -> bool:
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(eventId)")
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


@metrics.log_metrics
@tracer.capture_lambda_handler
def handler(event, context):
    maybe_fail(label=SERVICE)
    ciclo, n = resolver_parametros(event or {})
    logger.append_keys(cicloId=ciclo)
    tracer.put_annotation(key="cicloId", value=ciclo)
    txs = leer_transacciones(ciclo, n)
    total = len(txs)
    if total < n:
        logger.warning("hay menos transacciones que N_SOLICITUDES", extra={"disponibles": total, "solicitadas": n})
    outbox = ddb().Table(os.environ["TABLE_OUTBOX"])

    def det_id(tipo: str, factura: str) -> str:
        return str(uuid.uuid5(NAMESPACE, f"{ciclo}|{tipo}|{factura}"))

    inicio = make_event(
        "CicloDeFacturacionIniciado", SERVICE, ciclo, CICLO_SENTINEL,
        event_id=det_id("ciclo", CICLO_SENTINEL), totalUnidades=total,
        iniciadoEn=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    nuevos = int(_put_once(outbox, _outbox_item(inicio, "EVENTOS")))
    for i, tx in enumerate(sorted(txs, key=lambda t: t["facturaId"]), start=1):
        extra = {k: tx[k] for k in ("clienteId", "tipoTarifa", "periodo") if tx.get(k) is not None}
        if tx.get("retardoSegundos") is not None:
            extra["retardoSegundos"] = float(tx["retardoSegundos"])
        ev = make_event(
            "ConsumoFacturablePreparado", SERVICE, ciclo, tx["facturaId"],
            event_id=det_id("consumo", tx["facturaId"]), ordinal=i, totalUnidades=total, **extra,
        )
        nuevos += int(_put_once(outbox, _outbox_item(ev, "INGRESO")))

    metrics.add_metric(name="UnidadesEnOutbox", unit=MetricUnit.Count, value=total)
    logger.info("ciclo iniciado", extra={"total": total, "itemsNuevosOutbox": nuevos})
    return {"ok": True, "cicloId": ciclo, "total": total, "outboxNuevos": nuevos}
