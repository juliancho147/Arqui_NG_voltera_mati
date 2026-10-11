"""ms-facturacion: emite la factura (paso de Step Functions), idempotente por facturaId.

Entrada: {"tx": {...}, "tarifa": {...}, "calculo": {"aprobado", "valorCargo", ...}}
- Idempotencia Powertools sobre TABLE_IDEMPOTENCIA (PK facturaId, TTL IDEMPOTENCY_TTL_ATTR): los reintentos de
  Step Functions devuelven la misma factura (mismo consecutivo) sin re-emitir ni re-publicar el evento.
- Consecutivo: contador atomico (UpdateItem ADD) en el item `__CONSECUTIVO__` de la misma tabla.
- Rechazo de negocio: aprobado=false + EmisionDeFacturaRechazada. Error tecnico: excepcion (Retry de SFN).
"""
import os
from decimal import Decimal

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.idempotency import idempotent

from voltera_common import correlation_from, maybe_fail, publisher_from_env
from voltera_common.idempotency import idempotency_config, persistence_layer

SERVICE = "ms-facturacion"
COUNTER_KEY = "__CONSECUTIVO__"
logger = Logger(service=SERVICE)
tracer = Tracer(service=SERVICE)
metrics = Metrics(namespace=os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "Voltera/Exp2"), service=SERVICE)

_publisher = None
_store = None
_ddb = None


def get_publisher():
    global _publisher
    if _publisher is None:
        _publisher = publisher_from_env(SERVICE)
    return _publisher


def get_store():
    global _store
    if _store is None:
        _store = persistence_layer()
    return _store


def get_ddb():
    global _ddb
    if _ddb is None:
        _ddb = boto3.client("dynamodb")
    return _ddb


def siguiente_consecutivo() -> int:
    out = get_ddb().update_item(
        TableName=os.environ["TABLE_IDEMPOTENCIA"],
        Key={"facturaId": {"S": COUNTER_KEY}},
        UpdateExpression="ADD consecutivo :uno",
        ExpressionAttributeValues={":uno": {"N": "1"}},
        ReturnValues="UPDATED_NEW",
    )
    return int(out["Attributes"]["consecutivo"]["N"])


def _emitir(event: dict) -> dict:
    maybe_fail(label=SERVICE)  # dentro del bloque idempotente: si falla, Powertools libera el registro
    tx = event["tx"]
    calculo = event["calculo"]
    corr = correlation_from(tx)
    pub = get_publisher()

    valor = Decimal(str(calculo.get("valorCargo", 0)))
    if not calculo.get("aprobado", False) or valor <= 0:
        motivo = "CALCULO_NO_APROBADO" if not calculo.get("aprobado", False) else "VALOR_CARGO_NO_POSITIVO"
        pub.publish("EmisionDeFacturaRechazada", corr.cicloId, corr.facturaId, motivo=motivo)
        metrics.add_metric(name="EmisionesRechazadas", unit=MetricUnit.Count, value=1)
        return {"aprobado": False, "motivo": motivo, "facturaId": corr.facturaId, "cicloId": corr.cicloId}

    numero = f"FV-{siguiente_consecutivo():06d}"
    pub.publish("FacturaEmitida", corr.cicloId, corr.facturaId, numeroFactura=numero, valorTotal=float(valor))
    metrics.add_metric(name="FacturasEmitidas", unit=MetricUnit.Count, value=1)
    return {
        "aprobado": True, "estado": "EMITIDA", "facturaId": corr.facturaId, "cicloId": corr.cicloId,
        "numeroFactura": numero, "valorTotal": float(valor),
    }


@metrics.log_metrics
@tracer.capture_lambda_handler
def handler(event, context):
    corr = correlation_from(event["tx"])  # valida contrato antes de tocar la tabla
    logger.append_keys(**corr.log_keys())
    tracer.put_annotation(key="cicloId", value=corr.cicloId)
    tracer.put_annotation(key="facturaId", value=corr.facturaId)
    config = idempotency_config("tx.facturaId", expires_after_seconds=int(os.environ.get("IDEMPOTENCY_EXPIRES_SECONDS", "86400")))
    config.register_lambda_context(context)

    ejecutado = {"si": False}

    @idempotent(config=config, persistence_store=get_store())
    def run(ev, ctx):
        ejecutado["si"] = True
        return _emitir(ev)

    res = run(event, context)
    if not ejecutado["si"]:  # el cuerpo no corrio: Powertools devolvio el resultado guardado (replay)
        metrics.add_metric(name="IdempotenciaReplays", unit=MetricUnit.Count, value=1)
        logger.info("replay idempotente", extra={"numero": res.get("numeroFactura")})
    logger.info("factura procesada", extra={"aprobado": res.get("aprobado"), "numero": res.get("numeroFactura")})
    return res
