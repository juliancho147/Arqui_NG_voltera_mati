"""Configuracion de ms_compra (R5.4, R5.9, R5.10).

ms_compra ejecuta la compra de una oferta llamando a `MarketEscrow.comprar(ofertaId,
comprador)` con firma custodial (la plataforma firma; el comprador viaja como parametro,
no como `msg.sender`). Este modulo resuelve la configuracion de ejecucion desde el entorno
y/o `deployment.json`, sin hardcodear llaves ni direcciones en el repo:

  * `MS_COMPRA_HOST` / `MS_COMPRA_PORT`  -> interfaz y puerto del servidor HTTP.
  * `DEPLOYMENT_PATH`                     -> ruta del `deployment.json` (por defecto, el
     canonico que escribe el orquestador en la raiz del repo).
  * `RPC_URL`                             -> endpoint JSON-RPC de la Cadena_Local; si no se
     indica, se toma de `deployment.json`.
  * `PLATAFORMA_PRIVATE_KEY`              -> llave custodial (la lee el `chain_client`).

El paquete comun `runner_blockchain` (que contiene `chain_client` y el cargador de
`deployment.json`) vive en `experiments/runner-blockchain/`. Como ms_compra es un servicio
en `services/ms-compra/`, se anade esa carpeta al `sys.path` para poder importar
`runner_blockchain.*` sin instalar el paquete.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# services/ms-compra/config.py -> repo root
ROOT = Path(__file__).resolve().parents[2]
# Paquete comun con chain_client y el cargador de deployment.json.
RUNNER_PKG_DIR = ROOT / "experiments" / "runner-blockchain"


def _ensure_runner_on_path() -> None:
    """Hace importable `runner_blockchain.*` sin instalar el paquete."""
    ruta = str(RUNNER_PKG_DIR)
    if RUNNER_PKG_DIR.is_dir() and ruta not in sys.path:
        sys.path.insert(0, ruta)


_ensure_runner_on_path()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8084
DEFAULT_DEPLOYMENT_PATH = ROOT / "deployment.json"


@dataclass(frozen=True)
class Config:
    """Configuracion resuelta de ms_compra."""

    host: str
    port: int
    deployment_path: Path
    rpc_url: str | None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        """Construye la configuracion desde variables de entorno (o un dict inyectado)."""
        src = os.environ if env is None else env
        host = src.get("MS_COMPRA_HOST", DEFAULT_HOST)
        port = _parse_port(src.get("MS_COMPRA_PORT"), DEFAULT_PORT)
        deployment_path = Path(src.get("DEPLOYMENT_PATH", str(DEFAULT_DEPLOYMENT_PATH)))
        rpc_url = src.get("RPC_URL") or None
        return cls(host=host, port=port, deployment_path=deployment_path, rpc_url=rpc_url)


def _parse_port(raw: str | None, default: int) -> int:
    """Parsea el puerto del entorno; cae al default si falta o es invalido."""
    if raw is None or not str(raw).strip():
        return default
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return default
    if not (0 < port < 65536):
        return default
    return port
