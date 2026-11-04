"""Fixtures y dobles de prueba para ms_venta.

Evitan tocar una cadena real: un `ChainClient` falso registra las funciones invocadas,
las transacciones construidas y devuelve recibos/estados predefinidos, de modo que se
pueda verificar la construccion de `publicar`/`cancelar`, la firma custodial (el vendedor
viaja como parametro), la extraccion del `ofertaId` del evento `OfertaPublicada` y el
manejo de reversion/timeout sin levantar Anvil.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# services/ms-venta/tests/conftest.py -> repo root y paquete runner_blockchain.
ROOT = Path(__file__).resolve().parents[3]
RUNNER_BLOCKCHAIN = ROOT / "experiments" / "runner-blockchain"
for ruta in (str(ROOT / "services" / "ms-venta"), str(RUNNER_BLOCKCHAIN)):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from runner_blockchain.chain.chain_client import EstadoTx, ResultadoTx  # noqa: E402


@dataclass
class LlamadaFuncion:
    """Captura de una llamada a `contract.functions.<nombre>(*args)`."""

    nombre: str
    args: tuple

    def build_transaction(self, overrides: dict[str, Any]) -> dict[str, Any]:
        return {"funcion": self.nombre, "args": self.args, **overrides}


class _Functions:
    def __init__(self, registro: list[LlamadaFuncion]) -> None:
        self._registro = registro

    def __getattr__(self, nombre: str):
        def crear(*args):
            llamada = LlamadaFuncion(nombre=nombre, args=args)
            self._registro.append(llamada)
            return llamada
        return crear


class _EventoPublicada:
    """Doble del evento OfertaPublicada: decodifica logs sinteticos `{"ofertaId": n}`."""

    def process_receipt(self, recibo, **kwargs):
        salida = []
        for log in recibo.get("logs", []):
            if isinstance(log, dict) and "ofertaId" in log:
                salida.append({"args": {"ofertaId": log["ofertaId"]}})
        return salida


class _Events:
    def __getitem__(self, nombre: str):
        assert nombre == "OfertaPublicada"
        return lambda: _EventoPublicada()


class _Eth:
    def __init__(self, recibos: dict[str, dict]) -> None:
        self._recibos = recibos

    def get_transaction_receipt(self, tx_hash: str) -> dict:
        return self._recibos.get(tx_hash, {"logs": []})


class _W3:
    def __init__(self, recibos: dict[str, dict]) -> None:
        self.eth = _Eth(recibos)

    def is_connected(self) -> bool:
        return True


@dataclass
class FakeChainClient:
    """`ChainClient` falso: captura txs, simula envio/espera y expone un MarketEscrow doble."""

    plataforma: str = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    nonce_base: int = 7
    # Cola de resultados que `esperar_recibo`/`enviar_y_esperar` devolveran, en orden.
    resultados: list[ResultadoTx] = field(default_factory=list)
    # Logs por tx_hash que `get_transaction_receipt` devolvera (evento OfertaPublicada).
    recibos: dict[str, dict] = field(default_factory=dict)

    llamadas: list[LlamadaFuncion] = field(default_factory=list)
    txs_enviadas: list[dict] = field(default_factory=list)
    nonces_pedidos: int = 0
    _contador_hash: int = 0

    def __post_init__(self) -> None:
        self._registro: list[LlamadaFuncion] = self.llamadas
        self.w3 = _W3(self.recibos)
        self._direcciones = {"MarketEscrow": "0xAbC0000000000000000000000000000000000001"}

    # --- superficie usada por VentaService ---
    @property
    def market_escrow(self):
        doble = type("ME", (), {})()
        doble.functions = _Functions(self._registro)
        doble.events = _Events()
        return doble

    def siguiente_nonce(self) -> int:
        self.nonces_pedidos += 1
        return self.nonce_base

    def enviar_tx(self, tx: dict) -> str:
        self.txs_enviadas.append(tx)
        self._contador_hash += 1
        return f"0xhash{self._contador_hash}"

    def esperar_recibo(self, tx_hash: str, timeout_s=None) -> ResultadoTx:
        return self.resultados.pop(0)

    def enviar_y_esperar(self, tx: dict, timeout_s=None) -> ResultadoTx:
        self.enviar_tx(tx)
        return self.resultados.pop(0)


def confirmada(gas: int = 21000, bloque: int = 10, tx_hash: str = "0xhash1") -> ResultadoTx:
    return ResultadoTx(estado=EstadoTx.CONFIRMADA, transactionHash=tx_hash, gasUsed=gas, blockNumber=bloque)


def revertida(tx_hash: str = "0xhash1") -> ResultadoTx:
    return ResultadoTx(estado=EstadoTx.REVERTIDA, transactionHash=tx_hash, gasUsed=5000, blockNumber=11)


def timeout(tx_hash: str = "0xhash1") -> ResultadoTx:
    return ResultadoTx(estado=EstadoTx.TIMEOUT, transactionHash=tx_hash)


@pytest.fixture
def fake_chain() -> FakeChainClient:
    return FakeChainClient()
