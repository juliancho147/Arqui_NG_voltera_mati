"""ms-comprobante-factura: notifica la factura al tercero (simulado). Lambda desde SQS (ReportBatchItemFailures).

Body SQS: {"evento": "FacturaEmitida", "cicloId", "facturaId"}.
- Idempotente por facturaId (Powertools idempotent_function sobre TABLE_IDEMPOTENCIA).
- El tercero se simula con FAIL_RATE/FORCE_FAIL: el fallo es POR REGISTRO -> batchItemFailures; SQS reentrega
  y tras maxReceiveCount el mensaje cae a la DLQ de comprobantes.
- Eventos: NotificacionRegistrada (1er intento), FacturaNotificada | NotificacionFallida(intento, definitivo).
"""
import json
import os

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.idempotency import idempotent_function
from aws_lambda_powertools.utilities.typing import LambdaContext

from voltera_common import correlation_from, maybe_fail, publisher_from_env
from voltera_common.idempotency import idempotency_config, persistence_layer

SERVICE = "ms-comprobante-factura"
logger = Logger(service=SERVICE)
tracer = Tracer(service=SERVICE)
metrics = Metrics(namespace=os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "Voltera/Exp2"), service=SERVICE)
processor = BatchProcessor(event_type=EventType.SQS, raise_on_entire_batch_failure=False)

_publisher = None
_store = None
ejecutado = {"si": False}


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


def _max_receive() -> int:
    return int(os.environ.get("MAX_RECEIVE_COUNT", "3"))


def _config():
    return idempotency_config("facturaId", expires_after_seconds=int(os.environ.get("IDEMPOTENCY_EXPIRES_SECONDS", "86400")))


def enviar_al_tercero(payload: dict, intento: int) -> dict:
    """Simula el envio al tercero. Si falla lanza (el registro vuelve a SQS)."""
    pub = get_publisher()
    corr = correlation_from(payload)
    if intento == 1:
        pub.publish("NotificacionRegistrada", corr.cicloId, corr.facturaId)
    try:
        maybe_fail(label="tercero")
    except Exception as exc:
        definitivo = intento >= _max_receive()
        pub.publish("NotificacionFallida", corr.cicloId, corr.facturaId, motivo=str(exc), intento=intento, definitivo=definitivo)
        metrics.add_metric(name="NotificacionesFallidas", unit=MetricUnit.Count, value=1)
        raise
    pub.publish("FacturaNotificada", corr.cicloId, corr.facturaId)
    metrics.add_metric(name="FacturasNotificadas", unit=MetricUnit.Count, value=1)
    return {"facturaId": corr.facturaId, "estado": "NOTIFICADA"}


def _notificar(payload: dict, intento: int) -> dict:
    # La idempotencia se arma por llamada porque la tabla viene de variables de entorno.
    @idempotent_function(data_keyword_argument="data", config=_config(), persistence_store=get_store())
    def _run(data: dict, intento: int) -> dict:
        ejecutado["si"] = True
        return enviar_al_tercero(data, intento)

    ejecutado["si"] = False
    res = _run(data=payload, intento=intento)
    if not ejecutado["si"]:
        metrics.add_metric(name="IdempotenciaReplays", unit=MetricUnit.Count, value=1)
        logger.info("replay idempotente", extra={"intento": intento})
    return res


def record_handler(record):
    payload = json.loads(record.body)
    corr = correlation_from(payload)
    logger.append_keys(**corr.log_keys())
    intento = int(record.attributes.approximate_receive_count or 1)
    tracer.put_annotation(key="cicloId", value=corr.cicloId)
    tracer.put_annotation(key="facturaId", value=corr.facturaId)
    logger.info("comprobante recibido", extra={"intento": intento})
    try:
        res = _notificar(payload, intento)
    except Exception as exc:
        logger.error("notificacion fallida", extra={"intento": intento, "error": str(exc)})
        raise
    logger.info("comprobante procesado", extra={"estado": res.get("estado"), "intento": intento})
    return res


@metrics.log_metrics
@tracer.capture_lambda_handler
def handler(event, context: LambdaContext):
    return process_partial_response(event=event, record_handler=record_handler, processor=processor, context=context)
