"""Dobles de prueba de ms_compra: un `chain_client` falso que imita al escrow.

El `FakeChainClient` reproduce el contrato necesario por `CompraService` sin red ni web3:

  * `market_escrow.functions.comprar(ofertaId, comprador).build_transaction(params)` arma
    un dict de tx que incluye el `from`, el `nonce` (si se paso) y los argumentos.
  * `repartir_nonces(n)` hace UNA lectura del nonce base y reparte `base, base+1, ...`,
    igual que el `ChainClient` real (una sola `eth_getTransactionCount`).
  * `enviar_tx` registra la tx (con su nonce) y devuelve un hash determinista.
  * `esperar_recibo` consulta al "escrow" simulado si esa compra confirma o revierte.

El escrow simulado garantiza, por oferta Activa, que **la primera compra en llegar** gana
(CONFIRMADA) y el resto revierte con `OfertaNoDisponible`, para ejercitar el modo
concurrente de E3 de forma determinista.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any


class EstadoTx(str, Enum):
    CONFIRMADA = "confirmada"
    REVERTIDA = "revertida"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ResultadoTx:
    """Replica del `ResultadoTx` del chain_client real (lo que lee `CompraService`)."""

    estado: EstadoTx
    transactionHash: str
    gasUsed: int | None = None
    blockNumber: int | None = None

    @property
    def confirmada(self) -> bool:
        return self.estado is EstadoTx.CONFIRMADA


class _Escrow:
    """Escrow simulado: una oferta Activa admite exactamente una compra confirmada."""

    def __init__(self, ofertas_activas: set[int]) -> None:
        self._activas = set(ofertas_activas)
        self._vendidas: set[int] = set()
        self._lock = threading.Lock()

    def intentar_compra(self, oferta_id: int) -> bool:
        """Devuelve True si esta compra confirma (primera sobre una oferta Activa)."""
        with self._lock:
            if oferta_id in self._activas and oferta_id not in self._vendidas:
                self._vendidas.add(oferta_id)
                return True
            return False


class _ComprarCall:
    """Representa `comprar(ofertaId, comprador)` y arma la tx en `build_transaction`."""

    def __init__(self, oferta_id: int, comprador: str) -> None:
        self._oferta_id = oferta_id
        self._comprador = comprador

    def build_transaction(self, params: dict[str, Any]) -> dict[str, Any]:
        tx = dict(params)
        tx.update({"fn": "comprar", "ofertaId": self._oferta_id, "comprador": self._comprador})
        return tx


class _Functions:
    def comprar(self, oferta_id: int, comprador: str) -> _ComprarCall:
        return _ComprarCall(oferta_id, comprador)


class _Contract:
    def __init__(self) -> None:
        self.functions = _Functions()


class FakeChainClient:
    """`ChainClientLike` de prueba con escrow simulado y contabilidad de nonces/envios."""

    def __init__(
        self,
        *,
        ofertas_activas: set[int] | None = None,
        nonce_base: int = 7,
        forzar_timeout: bool = False,
        plataforma: str = "0xPLATAFORMA",
    ) -> None:
        self.plataforma = plataforma
        self._contract = _Contract()
        self._escrow = _Escrow(ofertas_activas or set())
        self._nonce_base = nonce_base
        self._forzar_timeout = forzar_timeout
        self.lecturas_nonce = 0  # cuantas veces se consulto el nonce base
        self.nonces_asignados: list[int] = []
        self.txs_enviadas: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._contador = 0

    @property
    def market_escrow(self) -> _Contract:
        return self._contract

    def repartir_nonces(self, cantidad: int, base: int | None = None) -> list[int]:
        if cantidad < 0:
            raise ValueError("cantidad negativa")
        if base is None:
            self.lecturas_nonce += 1  # una sola lectura de eth_getTransactionCount
            inicio = self._nonce_base
        else:
            inicio = base
        asignados = [inicio + i for i in range(cantidad)]
        self.nonces_asignados.extend(asignados)
        return asignados

    def enviar_tx(self, tx: dict[str, Any]) -> str:
        with self._lock:
            self._contador += 1
            idx = self._contador
            self.txs_enviadas.append(dict(tx))
        return f"0x{idx:064x}"

    def esperar_recibo(self, tx_hash: str, timeout_s: int | None = None) -> ResultadoTx:
        if self._forzar_timeout:
            return ResultadoTx(estado=EstadoTx.TIMEOUT, transactionHash=tx_hash)
        # Recuperar la tx por hash para saber a que oferta corresponde.
        idx = int(tx_hash, 16)
        tx = self.txs_enviadas[idx - 1]
        confirma = self._escrow.intentar_compra(int(tx["ofertaId"]))
        if confirma:
            return ResultadoTx(
                estado=EstadoTx.CONFIRMADA,
                transactionHash=tx_hash,
                gasUsed=50_000,
                blockNumber=1,
            )
        return ResultadoTx(estado=EstadoTx.REVERTIDA, transactionHash=tx_hash)
