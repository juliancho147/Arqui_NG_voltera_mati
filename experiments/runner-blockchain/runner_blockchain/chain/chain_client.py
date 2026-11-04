"""Cliente de cadena comun (`chain_client`) para la experimentacion blockchain local.

Resuelve el ABI de los contratos Foundry desde `blockchain/out/<Contrato>.sol/<Contrato>.json`
(sin transcribirlo a mano), construye objetos `Contract` de web3.py sobre la Cadena_Local
Anvil, lee la llave custodial de la plataforma de `PLATAFORMA_PRIVATE_KEY` y firma las
transacciones localmente con `eth_account`.

Expone helpers para:
  * enviar una transaccion ya firmada,
  * esperar el recibo con tope de 30 s sin reintento y devolver `gasUsed`,
    `transactionHash`, `blockNumber` y estado (confirmada / revertida / timeout),
  * repartir nonces secuenciales explicitos (una sola lectura de
    `eth_getTransactionCount`) para el envio concurrente de E3.

Modelo custodial: todas las escrituras de EnergyToken/MarketEscrow las firma la misma
cuenta (la plataforma, cuenta 0 de Anvil). El vendedor/comprador viajan como parametros
de la funcion, no como `msg.sender`. Tras enviar, se espera la confirmacion <=30 s; si la
tx se revierte o no confirma, NO se reintenta (R5.9, R5.10).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import TimeExhausted

# experiments/runner-blockchain/runner_blockchain/chain/chain_client.py -> repo root
ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = ROOT / "blockchain" / "out"

# Nombre de artefacto Foundry por contrato: out/<Contrato>.sol/<Contrato>.json
CONTRATOS = ("EnergyToken", "MarketEscrow")

DEFAULT_RPC_URL = "http://localhost:8545"
# Tope duro de confirmacion on-chain exigido por R5.9 (sin reintento, R5.10).
CONFIRM_TIMEOUT_S = 30
PRIVATE_KEY_ENV = "PLATAFORMA_PRIVATE_KEY"


class ChainClientError(RuntimeError):
    """Error de configuracion/uso del cliente de cadena (ABI, llave, RPC, etc.)."""


class EstadoTx(str, Enum):
    """Estado final de una transaccion tras esperar su recibo."""

    CONFIRMADA = "confirmada"
    REVERTIDA = "revertida"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ResultadoTx:
    """Resultado de esperar la confirmacion on-chain de una transaccion.

    Para TIMEOUT los campos del recibo quedan en None: no hubo recibo dentro del tope.
    """

    estado: EstadoTx
    transactionHash: str
    gasUsed: int | None = None
    blockNumber: int | None = None

    @property
    def confirmada(self) -> bool:
        return self.estado is EstadoTx.CONFIRMADA

    def as_dict(self) -> dict[str, Any]:
        return {
            "estado": self.estado.value,
            "transactionHash": self.transactionHash,
            "gasUsed": self.gasUsed,
            "blockNumber": self.blockNumber,
        }


def abi_path(contrato: str) -> Path:
    """Ruta del artefacto Foundry de `contrato` dentro de `blockchain/out/`."""
    return OUT_DIR / f"{contrato}.sol" / f"{contrato}.json"


def load_abi(contrato: str) -> list[dict[str, Any]]:
    """Carga el campo `abi` del artefacto Foundry de `contrato` desde `blockchain/out/`.

    No se duplica ni se transcribe el ABI a mano: se lee el JSON que produce `forge build`.
    """
    ruta = abi_path(contrato)
    try:
        artefacto = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChainClientError(
            f"no se encontro el artefacto de {contrato} en {ruta}; compila con `forge build` en blockchain/"
        ) from exc
    except (ValueError, OSError) as exc:
        raise ChainClientError(f"no se pudo leer el ABI de {contrato} en {ruta}: {exc}") from exc
    abi = artefacto.get("abi")
    if not isinstance(abi, list):
        raise ChainClientError(f"el artefacto de {contrato} en {ruta} no contiene un campo 'abi' valido")
    return abi


def load_private_key(env: str = PRIVATE_KEY_ENV) -> str:
    """Lee la llave privada custodial de la plataforma del entorno (`PLATAFORMA_PRIVATE_KEY`).

    Nunca se hardcodea en el repo ni se persiste en el reporte.
    """
    raw = os.environ.get(env)
    if not raw or not raw.strip():
        raise ChainClientError(
            f"falta la variable de entorno {env} con la llave privada custodial de la plataforma"
        )
    return raw.strip()


class ChainClient:
    """Cliente comun contra la Cadena_Local: ABI de Foundry + firma custodial + helpers de tx."""

    def __init__(
        self,
        rpc_url: str = DEFAULT_RPC_URL,
        *,
        private_key: str | None = None,
        contratos: dict[str, str] | None = None,
        web3: Web3 | None = None,
        confirm_timeout_s: int = CONFIRM_TIMEOUT_S,
    ) -> None:
        """Construye el cliente.

        * `rpc_url`: endpoint JSON-RPC de Anvil (ignorado si se pasa `web3`).
        * `private_key`: llave custodial; si es None se lee de `PLATAFORMA_PRIVATE_KEY`.
        * `contratos`: direcciones por contrato (p. ej. de `deployment.json`); se pueden
          asignar luego con `set_direcciones`. Solo se construyen los `Contract` cuando
          hay direccion disponible.
        * `web3`: inyectable para pruebas (mock del proveedor).
        """
        self.rpc_url = rpc_url
        self.confirm_timeout_s = confirm_timeout_s
        self.w3: Web3 = web3 if web3 is not None else Web3(Web3.HTTPProvider(rpc_url))
        self.account: LocalAccount = Account.from_key(private_key or load_private_key())
        self.plataforma: str = self.account.address
        self._abis: dict[str, list[dict[str, Any]]] = {c: load_abi(c) for c in CONTRATOS}
        self._direcciones: dict[str, str] = {}
        self._contracts: dict[str, Contract] = {}
        if contratos:
            self.set_direcciones(contratos)

    # ---- contratos -----------------------------------------------------------
    def set_direcciones(self, contratos: dict[str, str]) -> None:
        """Registra/actualiza direcciones de contrato y (re)construye sus objetos `Contract`."""
        for nombre, direccion in contratos.items():
            if nombre not in self._abis:
                raise ChainClientError(f"contrato desconocido '{nombre}'; conocidos: {', '.join(CONTRATOS)}")
            checksum = Web3.to_checksum_address(direccion)
            self._direcciones[nombre] = checksum
            self._contracts[nombre] = self.w3.eth.contract(address=checksum, abi=self._abis[nombre])

    def contract(self, nombre: str) -> Contract:
        """Devuelve el objeto `Contract` de web3.py para `nombre` (EnergyToken|MarketEscrow)."""
        try:
            return self._contracts[nombre]
        except KeyError as exc:
            if nombre not in self._abis:
                raise ChainClientError(
                    f"contrato desconocido '{nombre}'; conocidos: {', '.join(CONTRATOS)}"
                ) from exc
            raise ChainClientError(
                f"no hay direccion registrada para '{nombre}'; usa set_direcciones(...) o pasa 'contratos'"
            ) from exc

    @property
    def energy_token(self) -> Contract:
        return self.contract("EnergyToken")

    @property
    def market_escrow(self) -> Contract:
        return self.contract("MarketEscrow")

    def abi(self, contrato: str) -> list[dict[str, Any]]:
        """ABI cargado de `contrato` (para decodificar logs del Lector_Eventos, etc.)."""
        try:
            return self._abis[contrato]
        except KeyError as exc:
            raise ChainClientError(f"contrato desconocido '{contrato}'") from exc

    # ---- nonces --------------------------------------------------------------
    def siguiente_nonce(self) -> int:
        """Nonce actual (`pending`) de la cuenta de la plataforma, leido una vez."""
        return self.w3.eth.get_transaction_count(self.plataforma, "pending")

    def repartir_nonces(self, cantidad: int, base: int | None = None) -> list[int]:
        """Reparte `cantidad` nonces secuenciales explicitos `base, base+1, ...`.

        Una sola lectura de `eth_getTransactionCount` (si `base` es None) para el envio
        concurrente de E3: todas las compras las firma la misma cuenta custodial y comparten
        el espacio de nonce, asi que se asignan explicitamente para evitar colisiones (R5.9).
        """
        if cantidad < 0:
            raise ChainClientError("la cantidad de nonces no puede ser negativa")
        inicio = self.siguiente_nonce() if base is None else base
        return [inicio + i for i in range(cantidad)]

    # ---- firma y envio -------------------------------------------------------
    def firmar(self, tx: dict[str, Any]) -> bytes:
        """Firma localmente una transaccion ya construida con la llave custodial.

        Devuelve los bytes de la transaccion firmada (`rawTransaction`), listos para enviar.
        """
        firmada = self.account.sign_transaction(tx)
        # web3/eth-account exponen la carga cruda como `raw_transaction` (>=0.11) o `rawTransaction`.
        return getattr(firmada, "raw_transaction", None) or firmada.rawTransaction

    def enviar_firmada(self, raw_tx: bytes) -> str:
        """Envia una transaccion ya firmada y devuelve su hash en hex."""
        tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
        return tx_hash.hex()

    def enviar_tx(self, tx: dict[str, Any]) -> str:
        """Firma y envia una transaccion; devuelve el hash en hex (sin esperar recibo)."""
        return self.enviar_firmada(self.firmar(tx))

    def esperar_recibo(self, tx_hash: str, timeout_s: int | None = None) -> ResultadoTx:
        """Espera el recibo de `tx_hash` con tope de 30 s y SIN reintento.

        Devuelve un `ResultadoTx` con el estado:
          * CONFIRMADA  -> recibo con status == 1 (gasUsed/blockNumber poblados),
          * REVERTIDA   -> recibo con status == 0,
          * TIMEOUT     -> no hubo recibo dentro del tope (campos del recibo en None).
        """
        tope = self.confirm_timeout_s if timeout_s is None else timeout_s
        try:
            recibo = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=tope)
        except TimeExhausted:
            return ResultadoTx(estado=EstadoTx.TIMEOUT, transactionHash=_hex(tx_hash))
        confirmada = int(recibo.get("status", 0)) == 1
        return ResultadoTx(
            estado=EstadoTx.CONFIRMADA if confirmada else EstadoTx.REVERTIDA,
            transactionHash=_hex(recibo.get("transactionHash", tx_hash)),
            gasUsed=_opt_int(recibo.get("gasUsed")),
            blockNumber=_opt_int(recibo.get("blockNumber")),
        )

    def enviar_y_esperar(self, tx: dict[str, Any], timeout_s: int | None = None) -> ResultadoTx:
        """Firma, envia y espera la confirmacion (<=30 s, sin reintento) en un solo paso."""
        tx_hash = self.enviar_tx(tx)
        return self.esperar_recibo(tx_hash, timeout_s)


def _hex(value: Any) -> str:
    """Normaliza un hash (bytes/HexBytes/str) a cadena hex con prefijo `0x`."""
    if isinstance(value, str):
        return value
    hexfn = getattr(value, "hex", None)
    if callable(hexfn):
        h = hexfn()
        return h if h.startswith("0x") else f"0x{h}"
    return str(value)


def _opt_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def build_chain_client(
    rpc_url: str = DEFAULT_RPC_URL,
    *,
    contratos: dict[str, str] | None = None,
    private_key: str | None = None,
) -> ChainClient:
    """Fabrica conveniente: lee `PLATAFORMA_PRIVATE_KEY` del entorno salvo que se pase explicita."""
    return ChainClient(rpc_url, private_key=private_key, contratos=contratos)
