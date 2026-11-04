"""Configuracion de ms_oraculo por variables de entorno (R5.1, R2.2).

El servicio valida lecturas de medidor de forma real y determinista y, cuando acepta,
publica `GeneracionValidada` mediante una llamada HTTP a `ms_energia` (`POST /emisiones`).
Las integraciones accesorias (medidor, clima/temporada) son stubs con respuestas
predefinidas (R5.8); su referencia alimenta la deteccion de "valor alterado".
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    service: str = "ms-oraculo"
    health_port: int = 8080
    # URL base de ms_energia; la publicacion de GeneracionValidada se hace a {ms_energia_url}/emisiones.
    ms_energia_url: str = "http://localhost:8081"
    # Timeout (s) de la llamada HTTP a ms_energia al publicar GeneracionValidada.
    emision_timeout_seconds: float = 30.0
    # Tolerancia relativa permitida entre el valor reportado y la referencia del stub (deteccion de "valor alterado").
    tolerancia_relativa: float = 0.10

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        return cls(
            health_port=int(e.get("HEALTH_PORT", str(cls.health_port))),
            ms_energia_url=e.get("MS_ENERGIA_URL", cls.ms_energia_url).rstrip("/"),
            emision_timeout_seconds=float(e.get("EMISION_TIMEOUT_SECONDS", str(cls.emision_timeout_seconds))),
            tolerancia_relativa=float(e.get("ORACULO_TOLERANCIA_RELATIVA", str(cls.tolerancia_relativa))),
        )
