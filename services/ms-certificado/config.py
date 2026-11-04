"""Configuracion de ms_certificado (R3, R5.5, R5.6, R5.11).

Sigue el patron del repo para los microservicios que tocan la cadena: un modulo `config`
que resuelve del entorno todo lo que el servicio necesita y nada mas. En particular:

* El puerto HTTP del servicio (`MS_CERTIFICADO_PORT`, por defecto 8085).
* El endpoint JSON-RPC de Anvil y la ruta de `deployment.json`, de donde se resuelven las
  direcciones de los contratos (via el `chain_client`/`deployment` del runner blockchain).
* Las credenciales de Pinata (`PINATA_JWT`) y el gateway de recuperacion. **Nunca** se
  escriben en el repo ni se incluyen en el reporte (R3.4); se leen solo del entorno.
* El directorio del almacen local de contenido direccionable usado como *fallback* cuando
  no hay internet/credenciales de Pinata (R3.3).

La llave custodial de la plataforma (`PLATAFORMA_PRIVATE_KEY`) la consume directamente el
`chain_client`; aqui no se persiste ni se expone.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# services/ms-certificado/config.py -> repo root
ROOT = Path(__file__).resolve().parents[2]

# API real de Pinata para subir un archivo a IPFS y gateway para recuperarlo por CID.
PINATA_PIN_FILE_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"
DEFAULT_PINATA_GATEWAY = "https://gateway.pinata.cloud/ipfs/"

DEFAULT_PORT = 8085
DEFAULT_RPC_URL = "http://localhost:8545"
# Directorio por defecto del almacen local (fallback de Pinata). Fuera del control de
# versiones; nunca contiene credenciales, solo blobs indexados por su CID.
DEFAULT_ALMACEN_DIR = ROOT / ".certificados-local"


@dataclass(frozen=True)
class Config:
    """Configuracion resuelta del servicio ms_certificado."""

    port: int
    rpc_url: str
    deployment_path: Path
    almacen_dir: Path
    pinata_jwt: str | None
    pinata_gateway: str

    @property
    def pinata_habilitado(self) -> bool:
        """Hay credenciales para intentar usar Pinata (si no, se usa solo el fallback)."""
        return bool(self.pinata_jwt)


def _int_env(nombre: str, por_defecto: int) -> int:
    crudo = os.environ.get(nombre)
    if not crudo or not crudo.strip():
        return por_defecto
    try:
        return int(crudo.strip())
    except ValueError:
        return por_defecto


def cargar_config() -> Config:
    """Resuelve la configuracion de ms_certificado desde el entorno.

    Las credenciales de Pinata son opcionales: si faltan, el servicio opera con el almacen
    local de contenido direccionable (fallback) manteniendo el CID determinado por el
    contenido (R3.3). El JWT nunca se registra ni se devuelve en respuestas.
    """
    jwt = os.environ.get("PINATA_JWT")
    jwt = jwt.strip() if jwt and jwt.strip() else None

    gateway = os.environ.get("PINATA_GATEWAY", "").strip() or DEFAULT_PINATA_GATEWAY
    if not gateway.endswith("/"):
        gateway += "/"

    almacen = os.environ.get("MS_CERTIFICADO_ALMACEN_DIR", "").strip()
    almacen_dir = Path(almacen) if almacen else DEFAULT_ALMACEN_DIR

    deployment = os.environ.get("DEPLOYMENT_PATH", "").strip()
    deployment_path = Path(deployment) if deployment else (ROOT / "deployment.json")

    return Config(
        port=_int_env("MS_CERTIFICADO_PORT", DEFAULT_PORT),
        rpc_url=os.environ.get("RPC_URL", "").strip() or DEFAULT_RPC_URL,
        deployment_path=deployment_path,
        almacen_dir=almacen_dir,
        pinata_jwt=jwt,
        pinata_gateway=gateway,
    )
