"""outbox-relay: publica los eventos del outbox a Kafka (trigger DynamoDB Streams, INSERT).

Item del outbox: eventId, destino (INGRESO|EVENTOS), key, headers, payload (CloudEvent JSON).
INGRESO -> KAFKA_TOPIC (voltera.consumo-facturable-preparado); EVENTOS -> KAFKA_TOPIC_EVENTOS (voltera.eventos).
Clave del registro = facturaId, headers cicloId/facturaId. Si algo falla se lanza excepcion: el mapping reintenta
el lote (at-least-once; el consumidor deduplica). Tras publicar marca el item como PUBLICADO (best effort).
"""
import os
import time

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from boto3.dynamodb.types import TypeDeserializer

from voltera_common import maybe_fail
from voltera_common.publisher import DEFAULT_TOPIC_EVENTOS, MeshBackend, backend_from_env

SERVICE = "outbox-relay"
logger = Logger(service=SERVICE)
tracer = Tracer(service=SERVICE)
metrics = Metrics(namespace=os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "Voltera/Exp2"), service=SERVICE)
_deser = TypeDeserializer()

_backend: MeshBackend | None = None
_ddb = None


def get_backend() -> MeshBackend:
    global _backend
    if _backend is None:
        _backend = backend_from_env(client_id=SERVICE)
    return _backend


def ddb():
    global _ddb
    if _ddb is None:
        _ddb = boto3.client("dynamodb")
    return _ddb


def topic_for(destino: str) -> str:
    if destino == "INGRESO":
        return os.environ.get("KAFKA_TOPIC", "voltera.consumo-facturable-preparado")
    return os.environ.get("KAFKA_TOPIC_EVENTOS", DEFAULT_TOPIC_EVENTOS)


def _marcar_publicado(item: dict) -> None:
    table = os.environ.get("TABLE_OUTBOX")
    if not table:
        return
    try:
        ddb().update_item(
            TableName=table, Key={"eventId": {"S": item["eventId"]}},
            UpdateExpression="SET estado = :p, publicadoEn = :t",
            ExpressionAttributeValues={":p": {"S": "PUBLICADO"}, ":t": {"N": str(int(time.time()))}},
        )
    except Exception as exc:  # no es critico: el evento ya esta en Kafka
        logger.warning("no se pudo marcar PUBLICADO", extra={"eventId": item.get("eventId"), "error": str(exc)})


@metrics.log_metrics
@tracer.capture_lambda_handler
def handler(event, context):
    maybe_fail(label=SERVICE)
    backend = get_backend()
    items = []
    for rec in event.get("Records", []):
        if rec.get("eventName") != "INSERT":
            continue
        image = rec["dynamodb"].get("NewImage")
        if not image:
            continue
        items.append({k: _deser.deserialize(v) for k, v in image.items()})

    for it in items:
        headers = {k: str(v) for k, v in dict(it.get("headers") or {}).items()}
        backend.send(topic_for(it.get("destino", "EVENTOS")), str(it["key"]), it["payload"].encode("utf-8"), headers)
    backend.flush(float(os.environ.get("KAFKA_FLUSH_TIMEOUT", "10")))  # lanza PublishError -> el lote se reintenta
    for it in items:
        _marcar_publicado(it)
    metrics.add_metric(name="EventosPublicadosOutbox", unit=MetricUnit.Count, value=len(items))
    logger.info("outbox publicado", extra={"eventos": len(items)})
    return {"publicados": len(items)}
