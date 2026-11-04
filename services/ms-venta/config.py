"""Configuracion de ms_venta por variables de entorno (patron del repo).

ms_venta es uno de los cinco microservicios que tocan la Cadena_Local (R5). Publica y
cancela ofertas en `MarketEscrow` firmando de forma custodial con la llave de la plataforma
(cuenta 0 de Anvil, modelo `soloPlataforma`): el vendedor viaja como PARAMETRO de
`publicar(vendedor, id, kwh)`, nunca como `msg.sender` (R5.3, R5.7).

Este modulo:
  * resuelve la raiz del repo y agrega `experiments/runner-blockchain/` al `sys.path` para
    reutilizar el `chain_client` comun y el cargador de `deployment.json` (no se duplica la
    logica de cadena ni el ABI, que se lee de `blockchain/out/`),
  * lee la configuracion del servicio del entorno: puerto HTTP, ruta opcional de
    `deployment.json`, RPC y direccion de `MarketEscrow` de respaldo, y el tope de
    confirmacion on-chain (30 s por defecto, R5.9).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# services/ms-venta/config.py -> repo root (../../)
ROOT = Path(__file__).resolve().parents[2]
# Paquete del runner blockchain que aloja `chain_client` y `deployment` comunes.
RUNNER_BLOCKCHAIN = ROOT / "experiments" / "runner-blockchain"


def _ensure_runner_on_path() -> None:
    """Agrega `experiments/runner-blockchain/` al `sys.path` para importar `runner_blockchain`.

    Los microservicios viven en `services/` y reutilizan el cliente de cadena comun del
    paquete `runner_blockchain` sin empaquetarlo ni duplicarlo. Es idempotente.
    """
    ruta = str(RUNNER_BLOCKCHAIN)
    if ruta not in sys.path:
        sys.path.insert(0, ruta)


_ensure_runner_on_path()

# Tope duro de confirmacion on-chain exigido por R5.9 (sin reintento, R5.10).
DEFAULT_CONFIRM_TIMEOUT_S = 30
DEFAULT_RPC_URL = "http://localhost:8545"


@dataclass
class Settings:
    """Configuracion efectiva de ms_venta resuelta del entorno."""

    service: str = "ms-venta"
    health_port: int = 8083
    # Ruta a deployment.json; vacio = usar la ruta canonica del cargador (ROOT/deployment.json).
    deployment_path: str = ""
    # RPC y direccion de respaldo si no hay deployment.json (util en pruebas/arranque manual).
    rpc_url: str = DEFAULT_RPC_URL
    market_escrow: str = ""
    confirm_timeout_s: int = DEFAULT_CONFIRM_TIMEOUT_S

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        return cls(
            health_port=int(e.get("HEALTH_PORT", str(cls.health_port)) or cls.health_port),
            deployment_path=e.get("DEPLOYMENT_PATH", ""),
            rpc_url=e.get("RPC_URL", cls.rpc_url) or cls.rpc_url,
            market_escrow=e.get("MARKET_ESCROW_ADDRESS", ""),
            confirm_timeout_s=int(
                e.get("CONFIRM_TIMEOUT_S", str(cls.confirm_timeout_s)) or cls.confirm_timeout_s
            ),
        )
