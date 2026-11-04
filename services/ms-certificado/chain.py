"""Puente al `chain_client` comun del runner blockchain para ms_certificado.

Los microservicios y el runner comparten un unico cliente de cadena
(`experiments/runner-blockchain/runner_blockchain/chain/`) que resuelve el ABI de Foundry,
firma con la llave custodial de la plataforma y lee `deployment.json`. Para no duplicar esa
logica, este modulo agrega ese paquete al `sys.path` y expone una fabrica que construye un
`ChainClient` ya apuntando a las direcciones del despliegue.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# services/ms-certificado/chain.py -> repo root
ROOT = Path(__file__).resolve().parents[2]
RUNNER_BLOCKCHAIN = ROOT / "experiments" / "runner-blockchain"

if str(RUNNER_BLOCKCHAIN) not in sys.path:
    sys.path.insert(0, str(RUNNER_BLOCKCHAIN))

from runner_blockchain.chain.chain_client import ChainClient  # noqa: E402
from runner_blockchain.chain.deployment import load_deployment  # noqa: E402


def construir_chain_client(rpc_url: str, deployment_path: Path | str) -> ChainClient:
    """Construye un `ChainClient` con las direcciones resueltas de `deployment.json`.

    Lee la llave custodial de `PLATAFORMA_PRIVATE_KEY` (dentro del `ChainClient`) y registra
    las direcciones de EnergyToken/MarketEscrow del despliegue para poder anclar/verificar.
    """
    despliegue = load_deployment(deployment_path)
    return ChainClient(rpc_url, contratos=despliegue.contratos)
