"""Punto de entrada de ms_energia.

Resuelve el despliegue (`deployment.json`), construye el `chain_client` comun con la llave
custodial de la plataforma (`PLATAFORMA_PRIVATE_KEY`) apuntando a `EnergyToken`, y levanta el
servidor HTTP con `POST /emisiones` y `GET /healthz`. La emision es idempotente por
`lecturaId` y espera confirmacion <=30 s sin reintento (R5.2, R5.9, R5.10).
"""
from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path

# El cliente de cadena comun vive en el paquete runner_blockchain; lo agregamos al path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNNER_BC = _REPO_ROOT / "experiments" / "runner-blockchain"
if str(_RUNNER_BC) not in sys.path:
    sys.path.insert(0, str(_RUNNER_BC))

from runner_blockchain.chain.chain_client import build_chain_client  # noqa: E402
from runner_blockchain.chain.deployment import load_deployment  # noqa: E402

from config import Settings  # noqa: E402
from emitter import EmisionService  # noqa: E402
from server import make_server, serve_in_thread  # noqa: E402


def build_service(settings: Settings) -> EmisionService:
    """Construye el `EmisionService` con el chain_client apuntando a EnergyToken."""
    despliegue = load_deployment(settings.deployment_path or None)
    chain = build_chain_client(
        settings.rpc_url or despliegue.rpc_url,
        contratos={"EnergyToken": despliegue.energy_token},
    )
    return EmisionService(chain=chain, confirm_timeout_s=settings.confirm_timeout_s)


def main() -> None:
    settings = Settings.from_env()
    service = build_service(settings)
    stop = threading.Event()

    def check() -> dict:
        return {"ok": not stop.is_set(), "service": settings.service, "emisiones": len(service._vistos)}

    server = make_server(settings.health_port, service, check)
    serve_in_thread(server)

    def on_term(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    print(f"[{settings.service}] escuchando en :{settings.health_port} (pid={os.getpid()})", flush=True)
    stop.wait()
    server.shutdown()


if __name__ == "__main__":
    main()
