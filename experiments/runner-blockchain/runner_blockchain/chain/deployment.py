"""Cargador de `deployment.json` para el Runner_Experimentos (R1.3).

El orquestador del Entorno_Experimental (`orquestador/entorno.py`) publica
`deployment.json` tras arrancar Anvil y desplegar los contratos. Este modulo lo lee,
valida su estructura y expone de forma resuelta la URL del RPC, el chain-id y las
direcciones de `EnergyToken` y `MarketEscrow`, para que el runner, los microservicios y
el Lector_Eventos no tengan que reparsear el archivo ni conocer su esquema.

Esquema esperado (tal cual lo escribe `escribir_deployment`):

    {
      "chainId": 11155111,
      "rpcUrl": "http://localhost:8545",
      "plataforma": "0x...",
      "contratos": {"EnergyToken": "0x...", "MarketEscrow": "0x..."},
      "herramientas": {"foundry": "1.9.0"},
      "desplegadoEn": "2024-01-01T00:00:00Z"
    }

Las direcciones se devuelven en formato checksum (EIP-55), listas para `web3.py` y para
`ChainClient.set_direcciones`. Si el archivo falta o esta mal formado, se lanza
`DeploymentError` indicando la causa, para que el llamador no habilite experimentos con un
despliegue incompleto.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web3 import Web3

# experiments/runner-blockchain/runner_blockchain/chain/deployment.py -> repo root
ROOT = Path(__file__).resolve().parents[4]
# Ruta canonica donde el orquestador escribe el despliegue (ROOT/deployment.json).
DEFAULT_DEPLOYMENT_PATH = ROOT / "deployment.json"

# Contratos cuyas direcciones deben estar presentes en `deployment.json`.
CONTRATOS = ("EnergyToken", "MarketEscrow")


class DeploymentError(RuntimeError):
    """`deployment.json` ausente, ilegible o con un esquema invalido (R1.3)."""


@dataclass(frozen=True)
class Deployment:
    """Vista resuelta de `deployment.json` para el runner y los microservicios.

    `contratos` mapea nombre -> direccion en formato checksum (EIP-55). `herramientas`
    conserva el bloque de versiones (p. ej. `{"foundry": "1.9.0"}`).
    """

    chain_id: int
    rpc_url: str
    plataforma: str
    contratos: dict[str, str]
    herramientas: dict[str, str]
    desplegado_en: str
    ruta: Path

    @property
    def energy_token(self) -> str:
        """Direccion checksum del contrato EnergyToken."""
        return self.contratos["EnergyToken"]

    @property
    def market_escrow(self) -> str:
        """Direccion checksum del contrato MarketEscrow."""
        return self.contratos["MarketEscrow"]

    def direccion(self, contrato: str) -> str:
        """Direccion checksum de `contrato` (EnergyToken|MarketEscrow)."""
        try:
            return self.contratos[contrato]
        except KeyError as exc:
            raise DeploymentError(
                f"contrato desconocido '{contrato}'; conocidos: {', '.join(CONTRATOS)}"
            ) from exc

    def as_dict(self) -> dict[str, Any]:
        """Representacion serializable (sin la ruta) equivalente al `deployment.json` leido."""
        return {
            "chainId": self.chain_id,
            "rpcUrl": self.rpc_url,
            "plataforma": self.plataforma,
            "contratos": dict(self.contratos),
            "herramientas": dict(self.herramientas),
            "desplegadoEn": self.desplegado_en,
        }


def _checksum(contrato: str, direccion: Any) -> str:
    """Normaliza la direccion de `contrato` a checksum EIP-55 validando su forma."""
    if not isinstance(direccion, str) or not direccion.strip():
        raise DeploymentError(f"la direccion de '{contrato}' en deployment.json es invalida: {direccion!r}")
    try:
        return Web3.to_checksum_address(direccion.strip())
    except (ValueError, TypeError) as exc:
        raise DeploymentError(
            f"la direccion de '{contrato}' en deployment.json no es una direccion valida: {direccion!r}"
        ) from exc


def _resolver_contratos(crudo: Any) -> dict[str, str]:
    """Valida el bloque `contratos` y devuelve nombre -> direccion checksum."""
    if not isinstance(crudo, dict):
        raise DeploymentError("deployment.json no contiene un objeto 'contratos' valido")
    resueltos: dict[str, str] = {}
    for nombre in CONTRATOS:
        if nombre not in crudo:
            raise DeploymentError(f"deployment.json no incluye la direccion de '{nombre}'")
        resueltos[nombre] = _checksum(nombre, crudo[nombre])
    return resueltos


def parse_deployment(documento: dict[str, Any], *, ruta: Path = DEFAULT_DEPLOYMENT_PATH) -> Deployment:
    """Valida un documento de despliegue ya parseado y devuelve un `Deployment` resuelto."""
    if not isinstance(documento, dict):
        raise DeploymentError(f"deployment.json en {ruta} no es un objeto JSON")

    chain_id_crudo = documento.get("chainId")
    try:
        chain_id = int(chain_id_crudo)
    except (TypeError, ValueError) as exc:
        raise DeploymentError(f"deployment.json no contiene un 'chainId' valido: {chain_id_crudo!r}") from exc

    rpc_url = documento.get("rpcUrl")
    if not isinstance(rpc_url, str) or not rpc_url.strip():
        raise DeploymentError(f"deployment.json no contiene un 'rpcUrl' valido: {rpc_url!r}")

    plataforma = documento.get("plataforma")
    if not isinstance(plataforma, str) or not plataforma.strip():
        raise DeploymentError(f"deployment.json no contiene una 'plataforma' valida: {plataforma!r}")

    contratos = _resolver_contratos(documento.get("contratos"))

    herramientas_crudo = documento.get("herramientas", {})
    herramientas = (
        {str(k): str(v) for k, v in herramientas_crudo.items()}
        if isinstance(herramientas_crudo, dict)
        else {}
    )

    desplegado_en = documento.get("desplegadoEn")
    if not isinstance(desplegado_en, str):
        desplegado_en = ""

    return Deployment(
        chain_id=chain_id,
        rpc_url=rpc_url.strip(),
        plataforma=_checksum("plataforma", plataforma),
        contratos=contratos,
        herramientas=herramientas,
        desplegado_en=desplegado_en,
        ruta=ruta,
    )


def load_deployment(ruta: Path | str | None = None) -> Deployment:
    """Lee y valida `deployment.json` y devuelve un `Deployment` resuelto (R1.3).

    `ruta` es opcional; por defecto se usa `ROOT/deployment.json`, el mismo destino que
    escribe el orquestador. Lanza `DeploymentError` si el archivo falta, no se puede leer o
    no cumple el esquema (direcciones de ambos contratos, rpcUrl y chainId presentes).
    """
    destino = DEFAULT_DEPLOYMENT_PATH if ruta is None else Path(ruta)
    try:
        texto = destino.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DeploymentError(
            f"no se encontro deployment.json en {destino}; ejecuta el orquestador del entorno antes de "
            "los experimentos"
        ) from exc
    except OSError as exc:
        raise DeploymentError(f"no se pudo leer deployment.json en {destino}: {exc}") from exc

    try:
        documento = json.loads(texto)
    except ValueError as exc:
        raise DeploymentError(f"deployment.json en {destino} no es JSON valido: {exc}") from exc

    return parse_deployment(documento, ruta=destino)
