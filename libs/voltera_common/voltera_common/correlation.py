"""Correlacion: todo evento lleva cicloId + facturaId."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

# Valor centinela de facturaId para eventos de nivel ciclo (ver mesh/asyncapi.yaml).
CICLO_SENTINEL = "CICLO"


@dataclass(frozen=True)
class Correlation:
    cicloId: str
    facturaId: str

    def headers(self) -> dict[str, str]:
        return {"cicloId": self.cicloId, "facturaId": self.facturaId}

    def log_keys(self) -> dict[str, str]:
        return {"cicloId": self.cicloId, "facturaId": self.facturaId}


def correlation_from(obj: Mapping[str, Any]) -> Correlation:
    """Extrae la correlacion de un dict (tx, data de evento o mensaje). Lanza ValueError si falta."""
    ciclo = obj.get("cicloId") or obj.get("cicloid")
    factura = obj.get("facturaId") or obj.get("facturaid")
    if not ciclo or not factura:
        raise ValueError("falta cicloId/facturaId en el mensaje")
    return Correlation(str(ciclo), str(factura))


def new_event_id() -> str:
    return str(uuid.uuid4())
