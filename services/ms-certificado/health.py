"""Health check de ms_certificado (patron `health.py` del repo).

Expone la logica de `GET /healthz`, separada del enrutado HTTP para poder reutilizarla y
probarla sin levantar el servidor. El servicio esta sano si puede resolver su configuracion;
el estado de Pinata se reporta como informativo (su ausencia no lo vuelve no-sano, porque el
fallback local cubre el guardado/recuperacion, R3.3).
"""
from __future__ import annotations

from typing import Any

from config import Config


def estado_salud(config: Config) -> dict[str, Any]:
    """Construye la carga de `GET /healthz` para ms_certificado.

    Nunca incluye credenciales (R3.4): solo se informa si Pinata esta habilitado, no el JWT.
    """
    return {
        "status": "ok",
        "service": "ms_certificado",
        "pinata": "habilitado" if config.pinata_habilitado else "fallback-local",
    }
