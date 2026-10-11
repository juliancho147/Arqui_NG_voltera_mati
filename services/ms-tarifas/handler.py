"""ms-tarifas: valida la tarifa (paso de Step Functions).

Entrada (tx del SQS): {cicloId, facturaId, clienteId, tipoTarifa, periodo, ...}
Salida:  {"aprobado": bool, "valorKwh", "tipoTarifa", "moneda", "motivo"?}
- Rechazo de NEGOCIO (tarifa inexistente/invalida): aprobado=false + evento TarifaRechazada, sin lanzar error.
- Error TECNICO (fallo inyectado, payload sin ids): lanza excepcion -> Retry de Step Functions.
"""
import json
import os
from decimal import Decimal

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit

from voltera_common import correlation_from, maybe_fail, publisher_from_env

SERVICE = "ms-tarifas"
logger = Logger(service=SERVICE)
tracer = Tracer(service=SERVICE)
metrics = Metrics(namespace=os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "Voltera/Exp2"), service=SERVICE)

# Tabla de tarifas (COP/kWh) determinista; se puede sobreescribir con TARIFAS_JSON='{"RESIDENCIAL": 700}'.
DEFAULT_TARIFAS = {"RESIDENCIAL": 650.0, "COMERCIAL": 720.0, "INDUSTRIAL": 580.0, "OFICIAL": 610.0}

_publisher = None


def get_publisher():
    global _publisher
    if _publisher is None:
        _publisher = publisher_from_env(SERVICE)
    return _publisher


def tarifas() -> dict[str, float]:
    raw = os.environ.get("TARIFAS_JSON")
    return {k.upper(): float(v) for k, v in json.loads(raw).items()} if raw else DEFAULT_TARIFAS


def validar(tx: dict) -> dict:
    tipo = str(tx.get("tipoTarifa") or "").upper()
    tabla = tarifas()
    if tipo not in tabla:
        return {"aprobado": False, "motivo": f"TARIFA_NO_DEFINIDA:{tipo or 'VACIA'}", "tipoTarifa": tipo}
    valor = tabla[tipo]
    if Decimal(str(valor)) <= 0:
        return {"aprobado": False, "motivo": "TARIFA_NO_POSITIVA", "tipoTarifa": tipo}
    return {"aprobado": True, "valorKwh": valor, "tipoTarifa": tipo, "moneda": "COP"}


@metrics.log_metrics
@tracer.capture_lambda_handler
def handler(event, context):
    maybe_fail(label=SERVICE)
    corr = correlation_from(event)  # ValueError = error tecnico de contrato
    logger.append_keys(**corr.log_keys())
    tracer.put_annotation(key="cicloId", value=corr.cicloId)
    tracer.put_annotation(key="facturaId", value=corr.facturaId)
    res = validar(event)
    pub = get_publisher()
    if res["aprobado"]:
        pub.publish("TarifaValidada", corr.cicloId, corr.facturaId, tipoTarifa=res["tipoTarifa"], valorKwh=res["valorKwh"])
        metrics.add_metric(name="TarifasValidadas", unit=MetricUnit.Count, value=1)
    else:
        pub.publish("TarifaRechazada", corr.cicloId, corr.facturaId, motivo=res["motivo"])
        metrics.add_metric(name="TarifasRechazadas", unit=MetricUnit.Count, value=1)
    logger.info("tarifa procesada", extra={"aprobado": res["aprobado"]})
    return res
