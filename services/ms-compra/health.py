"""Endpoint de salud de ms_compra (patron `health.py` del repo).

Expone la logica de `GET /healthz` que el orquestador del Entorno_Experimental consulta
para confirmar la readiness del servicio antes de inyectar casos (diseno: cada
microservicio mantiene su `GET /healthz`).
"""
from __future__ import annotations

SERVICE_NAME = "ms_compra"


def health_payload() -> dict[str, str]:
    """Cuerpo JSON de la respuesta de `GET /healthz`."""
    return {"status": "ok", "service": SERVICE_NAME}
