"""CloudEvents 1.0 (modo estructurado JSON) y modelos de datos de los eventos del plan.

Contrato: mesh/asyncapi.yaml. type = com.voltera.facturacion.<kebab>.v1, source = /voltera/<servicio>,
subject = facturaId, extensiones cicloid/facturaid. Eventos de nivel ciclo usan facturaId = "CICLO".
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .correlation import new_event_id

TYPE_PREFIX = "com.voltera.facturacion."
TYPE_SUFFIX = ".v1"
CONTENT_TYPE = "application/cloudevents+json; charset=UTF-8"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _kebab(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


# ---------------------------------------------------------------- datos de cada evento
class _Data(BaseModel):
    model_config = ConfigDict(extra="allow")
    cicloId: str
    facturaId: str


class CicloDeFacturacionIniciadoData(_Data):
    totalUnidades: int
    iniciadoEn: str | None = None


class ConsumoFacturablePreparadoData(_Data):
    ordinal: int | None = None
    totalUnidades: int | None = None
    # Referencias ligeras para armar la transaccion (los datos pesados siguen en DynamoDB).
    clienteId: str | None = None
    tipoTarifa: str | None = None
    periodo: str | None = None
    retardoSegundos: float | None = None  # retardo simulado por mensaje (Exp. 1)


class TarifaValidadaData(_Data):
    tipoTarifa: str | None = None
    valorKwh: float | None = None


class TarifaRechazadaData(_Data):
    motivo: str


class CargoEnergeticoCalculadoData(_Data):
    valorCargo: float
    moneda: str = "COP"
    consumoNetoKwh: float | None = None


class CalculoDeCargoRechazadoData(_Data):
    motivo: str


class FacturaEmitidaData(_Data):
    numeroFactura: str
    valorTotal: float | None = None


class EmisionDeFacturaRechazadaData(_Data):
    motivo: str


class NotificacionRegistradaData(_Data):
    pass


class FacturaNotificadaData(_Data):
    pass


class NotificacionFallidaData(_Data):
    motivo: str
    intento: int = 1
    definitivo: bool = False  # True cuando ya no habra mas reintentos desde SQS


class ProcesoDeFacturacionCompletadoData(_Data):
    emitidas: int
    rechazadas: int = 0
    fallidas: int = 0
    totalUnidades: int | None = None


class ProcesoDeFacturacionFallidoData(_Data):
    motivo: str
    emitidas: int = 0
    rechazadas: int = 0
    fallidas: int = 0
    totalUnidades: int | None = None


EVENT_DATA_MODELS: dict[str, type[_Data]] = {
    "CicloDeFacturacionIniciado": CicloDeFacturacionIniciadoData,
    "ConsumoFacturablePreparado": ConsumoFacturablePreparadoData,
    "TarifaValidada": TarifaValidadaData,
    "TarifaRechazada": TarifaRechazadaData,
    "CargoEnergeticoCalculado": CargoEnergeticoCalculadoData,
    "CalculoDeCargoRechazado": CalculoDeCargoRechazadoData,  # el plan lo escribe "CálculoDeCargoRechazado"
    "FacturaEmitida": FacturaEmitidaData,
    "EmisionDeFacturaRechazada": EmisionDeFacturaRechazadaData,
    "NotificacionRegistrada": NotificacionRegistradaData,
    "FacturaNotificada": FacturaNotificadaData,
    "NotificacionFallida": NotificacionFallidaData,
    "ProcesoDeFacturacionCompletado": ProcesoDeFacturacionCompletadoData,
    "ProcesoDeFacturacionFallido": ProcesoDeFacturacionFallidoData,
}

EVENT_TYPES: dict[str, str] = {n: f"{TYPE_PREFIX}{_kebab(n)}{TYPE_SUFFIX}" for n in EVENT_DATA_MODELS}
_NAME_BY_TYPE = {v: k for k, v in EVENT_TYPES.items()}


def event_name_from_type(ce_type: str) -> str | None:
    return _NAME_BY_TYPE.get(ce_type)


# ---------------------------------------------------------------- sobre CloudEvents
class CloudEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    specversion: str = "1.0"
    id: str = Field(default_factory=new_event_id)
    source: str
    type: str
    subject: str
    time: str = Field(default_factory=utcnow_iso)
    datacontenttype: str = "application/json"
    cicloid: str
    facturaid: str
    traceparent: str | None = None
    data: dict[str, Any]

    @property
    def name(self) -> str | None:
        return event_name_from_type(self.type)

    @property
    def cicloId(self) -> str:
        return self.cicloid

    @property
    def facturaId(self) -> str:
        return self.facturaid

    def headers(self) -> dict[str, str]:
        return {"cicloId": self.cicloid, "facturaId": self.facturaid, "content-type": CONTENT_TYPE}

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)

    def to_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")


def make_event(
    name: str,
    source: str,
    cicloId: str,
    facturaId: str,
    *,
    event_id: str | None = None,
    traceparent: str | None = None,
    **data: Any,
) -> CloudEvent:
    """Crea y valida un evento por su nombre. `source` es el nombre del servicio (se normaliza a /voltera/<servicio>)."""
    model = EVENT_DATA_MODELS.get(name)
    if model is None:
        raise ValueError(f"evento desconocido: {name}")
    validated = model(cicloId=cicloId, facturaId=facturaId, **data)
    kwargs: dict[str, Any] = {}
    if event_id:
        kwargs["id"] = event_id
    return CloudEvent(
        source=source if source.startswith("/") else f"/voltera/{source}",
        type=EVENT_TYPES[name],
        subject=facturaId,
        cicloid=cicloId,
        facturaid=facturaId,
        traceparent=traceparent,
        data=validated.model_dump(exclude_none=True),
        **kwargs,
    )


def parse_cloudevent(raw: bytes | str | dict) -> CloudEvent:
    """Parsea y valida un CloudEvent estructurado JSON. Lanza ValueError si es invalido."""
    try:
        obj = raw if isinstance(raw, dict) else json.loads(raw)
        ev = CloudEvent.model_validate(obj)
    except Exception as exc:  # pydantic.ValidationError, JSONDecodeError
        raise ValueError(f"CloudEvent invalido: {exc}") from exc
    if ev.specversion != "1.0":
        raise ValueError("specversion no soportada")
    name = ev.name
    if name is not None:
        EVENT_DATA_MODELS[name].model_validate(ev.data)
    return ev
