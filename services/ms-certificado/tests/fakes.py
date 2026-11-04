"""Dobles de prueba para ms_certificado: una cadena en memoria que imita MarketEscrow.

Reproduce el comportamiento relevante del contrato para probar la logica del servicio sin
Anvil ni web3: `anclar(ofertaId, cid)` guarda el CID y `certificado(ofertaId)` lo devuelve
(cadena vacia si no hay ninguno, igual que el getter del mapping en Solidity).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class _Call:
    def __init__(self, fn):
        self._fn = fn

    def call(self):
        return self._fn()


class _FnAnclar:
    def __init__(self, cadena: "FakeChain", oferta_id: int, cid: str) -> None:
        self._cadena = cadena
        self._oferta_id = oferta_id
        self._cid = cid

    def build_transaction(self, overrides: dict[str, Any]) -> dict[str, Any]:
        return {"__fn": "anclar", "ofertaId": self._oferta_id, "cid": self._cid, **overrides}


class _FnCertificado:
    def __init__(self, cadena: "FakeChain", oferta_id: int) -> None:
        self._cadena = cadena
        self._oferta_id = oferta_id

    def call(self) -> str:
        return self._cadena.certificados.get(int(self._oferta_id), "")


class _Functions:
    def __init__(self, cadena: "FakeChain") -> None:
        self._cadena = cadena

    def anclar(self, oferta_id: int, cid: str) -> _FnAnclar:
        return _FnAnclar(self._cadena, oferta_id, cid)

    def certificado(self, oferta_id: int) -> _FnCertificado:
        return _FnCertificado(self._cadena, oferta_id)


class _Escrow:
    def __init__(self, cadena: "FakeChain") -> None:
        self.functions = _Functions(cadena)


@dataclass
class _ResultadoTx:
    estado_valor: str
    transactionHash: str | None

    @property
    def confirmada(self) -> bool:
        return self.estado_valor == "confirmada"

    @property
    def estado(self):
        class _E:
            value = self.estado_valor

        return _E()


class FakeChain:
    """Cliente de cadena en memoria con el subconjunto que usa CertificadoService."""

    def __init__(self, *, anclaje_confirma: bool = True) -> None:
        self.plataforma = "0x0000000000000000000000000000000000000001"
        self.certificados: dict[int, str] = {}
        self.anclaje_confirma = anclaje_confirma
        self._nonce = 0
        self.market_escrow = _Escrow(self)

    def siguiente_nonce(self) -> int:
        valor = self._nonce
        self._nonce += 1
        return valor

    def enviar_y_esperar(self, tx: dict[str, Any], timeout_s: int | None = None) -> _ResultadoTx:
        if tx.get("__fn") == "anclar" and self.anclaje_confirma:
            self.certificados[int(tx["ofertaId"])] = tx["cid"]
            return _ResultadoTx("confirmada", "0xhash")
        return _ResultadoTx("revertida", "0xhash")
