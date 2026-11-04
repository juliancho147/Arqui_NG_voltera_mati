"""Configuracion por variables de entorno de ms_energia (patron del repo).

ms_energia emite tokens a partir de una generacion validada llamando a
`EnergyToken.emitir(a, id, kwh, precio, lecturaId)` exactamente una vez por `lecturaId`
(idempotencia por lectura, R5.2). Firma con la llave custodial de la plataforma y espera
la confirmacion on-chain con tope de 30 s, sin reintento (R5.9, R5.10).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    service: str = "ms-energia"
    health_port: int = 8080
    rpc_url: str = "http://localhost:8545"
    deployment_path: str = ""   # vacio => ROOT/deployment.json (default de load_deployment)
    confirm_timeout_s: int = 30  # tope duro R5.9 (sin reintento R5.10)

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        return cls(
            service=e.get("SERVICE_NAME", cls.service),
            health_port=int(e.get("HEALTH_PORT", "8080") or 8080),
            rpc_url=e.get("RPC_URL", cls.rpc_url),
            deployment_path=e.get("DEPLOYMENT_PATH", ""),
            confirm_timeout_s=int(e.get("CONFIRM_TIMEOUT_SECONDS", "30") or 30),
        )
