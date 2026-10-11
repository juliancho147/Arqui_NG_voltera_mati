"""ms-calculo-consumo-neto: calcula el cargo energetico (paso de Step Functions).

Entrada: {"tx": {...}, "tarifa": {"aprobado", "valorKwh", ...}}
Lee consumoKwh y excedentesKwh de la tabla transacciones (TABLE_TRANSACCIONES, PK cicloId, SK facturaId).
consumo neto = consumo - excedentes; cargo = neto * valorKwh.
Salida: {"aprobado": bool, "consumoNetoKwh", "valorCargo", "moneda", "motivo"?}
"""
import os
from decimal import ROUND_HALF_UP, Decimal

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit

from voltera_common import correlation_from, maybe_fail, publisher_from_env

SERVICE = "ms-calculo-consumo-neto"
logger = Logger(service=SERVICE)
tracer = Tracer(service=SERVICE)
metrics = Metrics(namespace=os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "Voltera/Exp2"), service=SERVICE)

_publisher = None
_table = None


def get_publisher():
    global _publisher
    if _publisher is None:
        _publisher = publisher_from_env(SERVICE)
    return _publisher


def get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_TRANSACCIONES"])
    return _table


def calcular(consumo: Decimal, excedentes: Decimal, valor_kwh: Decimal) -> dict:
    if consumo < 0 or excedentes < 0:
        return {"aprobado": False, "motivo": "CONSUMO_O_EXCEDENTE_NEGATIVO"}
    neto = consumo - excedentes
    if neto < 0:
        return {"aprobado": False, "motivo": "EXCEDENTES_SUPERAN_CONSUMO"}
    cargo = (neto * valor_kwh).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"aprobado": True, "consumoNetoKwh": float(neto), "valorCargo": float(cargo), "moneda": "COP"}


@metrics.log_metrics
@tracer.capture_lambda_handler
def handler(event, context):
    maybe_fail(label=SERVICE)
    tx = event["tx"]
    tarifa = event["tarifa"]
    corr = correlation_from(tx)
    logger.append_keys(**corr.log_keys())
    tracer.put_annotation(key="cicloId", value=corr.cicloId)
    tracer.put_annotation(key="facturaId", value=corr.facturaId)
    pub = get_publisher()

    item = get_table().get_item(Key={"cicloId": corr.cicloId, "facturaId": corr.facturaId}).get("Item")
    if item is None:
        res = {"aprobado": False, "motivo": "TRANSACCION_NO_ENCONTRADA"}
    else:
        res = calcular(
            Decimal(str(item.get("consumoKwh", 0))),
            Decimal(str(item.get("excedentesKwh", 0))),
            Decimal(str(tarifa["valorKwh"])),
        )

    if res["aprobado"]:
        pub.publish("CargoEnergeticoCalculado", corr.cicloId, corr.facturaId,
                    valorCargo=res["valorCargo"], moneda=res["moneda"], consumoNetoKwh=res["consumoNetoKwh"])
        metrics.add_metric(name="CargosCalculados", unit=MetricUnit.Count, value=1)
    else:
        pub.publish("CalculoDeCargoRechazado", corr.cicloId, corr.facturaId, motivo=res["motivo"])
        metrics.add_metric(name="CalculosRechazados", unit=MetricUnit.Count, value=1)
    logger.info("calculo procesado", extra={"aprobado": res["aprobado"]})
    return res
