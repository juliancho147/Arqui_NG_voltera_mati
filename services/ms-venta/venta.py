"""Logica de dominio de ms_venta: publicar y cancelar ofertas en `MarketEscrow` (R5.3).

Se separa de la capa HTTP (`main.py`) para poder probar la construccion de transacciones,
la firma custodial, la espera de confirmacion <=30 s (R5.9, R5.10) y la extraccion del
`ofertaId` sin levantar un servidor.

Modelo custodial (R5.3, R5.7): todas las escrituras las firma la cuenta de la plataforma
via `ChainClient`; el vendedor viaja como parametro `publicar(vendedor, id, kwh)`, no como
`msg.sender`. `publicar` devuelve `ofertaId` on-chain; como el valor de retorno de una
transaccion escrita no esta disponible en el recibo, el `ofertaId` se extrae del evento
`OfertaPublicada` (que lo lleva indexado) de los logs del recibo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runner_blockchain.chain.chain_client import ChainClient, ResultadoTx

try:  # web3.py expone la politica DISCARD para ignorar logs ajenos al evento.
    from web3.logs import DISCARD as _DISCARD
except Exception:  # pragma: no cover - compatibilidad defensiva
    _DISCARD = None

# Nombre del evento que MarketEscrow emite al publicar, con `ofertaId` indexado.
EVENTO_PUBLICADA = "OfertaPublicada"


class VentaError(RuntimeError):
    """Error de dominio de ms_venta (parametros invalidos o resultado on-chain no confirmado)."""


@dataclass(frozen=True)
class ResultadoPublicar:
    """Resultado de publicar una oferta: `ofertaId` on-chain + evidencia de la transaccion.

    `ofertaId` solo esta poblado cuando la transaccion se confirmo y se pudo decodificar el
    evento `OfertaPublicada`. Si la tx se revierte o agota el tope, `ofertaId` es None y
    `tx.confirmada` es False (R5.9, R5.10: no se marca la operacion como completada).
    """

    ofertaId: int | None
    tx: ResultadoTx

    def as_dict(self) -> dict[str, Any]:
        return {"ofertaId": self.ofertaId, "tx": self.tx.as_dict()}


@dataclass(frozen=True)
class ResultadoCancelar:
    """Resultado de cancelar una oferta: evidencia de la transaccion on-chain."""

    ofertaId: int
    tx: ResultadoTx

    def as_dict(self) -> dict[str, Any]:
        return {"ofertaId": self.ofertaId, "tx": self.tx.as_dict()}


def _as_int(valor: Any, campo: str) -> int:
    """Convierte `valor` a int no negativo o lanza `VentaError` describiendo el campo."""
    try:
        n = int(valor)
    except (TypeError, ValueError) as exc:
        raise VentaError(f"'{campo}' debe ser un entero, recibido {valor!r}") from exc
    if n < 0:
        raise VentaError(f"'{campo}' no puede ser negativo, recibido {n}")
    return n


class VentaService:
    """Publica y cancela ofertas en `MarketEscrow` firmando de forma custodial."""

    def __init__(self, chain: ChainClient) -> None:
        self._chain = chain

    @property
    def market_escrow(self):
        return self._chain.market_escrow

    def _construir_tx(self, funcion) -> dict[str, Any]:
        """Construye una tx firmable para `funcion` asignandole `from` y un `nonce` explicito.

        Reutiliza el reparto de nonce del `chain_client` (una sola lectura) para que las
        publicaciones/cancelaciones secuenciales de la corrida no colisionen de nonce.
        """
        nonce = self._chain.siguiente_nonce()
        return funcion.build_transaction(
            {"from": self._chain.plataforma, "nonce": nonce}
        )

    def _extraer_oferta_id(self, recibo_logs) -> int | None:
        """Extrae el `ofertaId` del evento `OfertaPublicada` en los logs del recibo.

        Devuelve None si no se encuentra el evento (p. ej. tx revertida). Usa el decodificador
        del ABI de web3.py; ignora logs que no correspondan al evento.
        """
        if not recibo_logs:
            return None
        evento = self.market_escrow.events[EVENTO_PUBLICADA]()
        kwargs = {"errors": _DISCARD} if _DISCARD is not None else {}
        procesados = evento.process_receipt({"logs": recibo_logs}, **kwargs)
        for entrada in procesados:
            args = getattr(entrada, "args", None)
            if args is None and isinstance(entrada, dict):
                args = entrada.get("args", {})
            oferta = args.get("ofertaId") if args is not None else None
            if oferta is not None:
                return int(oferta)
        return None

    def publicar(self, vendedor: str, id: int, kwh: int, timeout_s: int | None = None) -> ResultadoPublicar:
        """Publica una oferta: `MarketEscrow.publicar(vendedor, id, kwh)` y devuelve el `ofertaId`.

        Firma custodial, espera confirmacion <=30 s sin reintento (R5.9, R5.10) y extrae el
        `ofertaId` del evento `OfertaPublicada` del recibo. Si la tx no se confirma, `ofertaId`
        es None y el resultado lo refleja en `tx.estado`.
        """
        if not isinstance(vendedor, str) or not vendedor.strip():
            raise VentaError(f"'vendedor' debe ser una direccion, recibido {vendedor!r}")
        id_i = _as_int(id, "id")
        kwh_i = _as_int(kwh, "kwh")

        funcion = self.market_escrow.functions.publicar(vendedor, id_i, kwh_i)
        tx = self._construir_tx(funcion)
        tx_hash = self._chain.enviar_tx(tx)
        resultado = self._chain.esperar_recibo(tx_hash, timeout_s)
        if not resultado.confirmada:
            return ResultadoPublicar(ofertaId=None, tx=resultado)

        recibo = self._chain.w3.eth.get_transaction_receipt(tx_hash)
        oferta_id = self._extraer_oferta_id(recibo.get("logs"))
        return ResultadoPublicar(ofertaId=oferta_id, tx=resultado)

    def cancelar(self, ofertaId: int, timeout_s: int | None = None) -> ResultadoCancelar:
        """Cancela una oferta: `MarketEscrow.cancelar(ofertaId)`.

        Firma custodial y espera confirmacion <=30 s sin reintento (R5.9, R5.10).
        """
        oferta_i = _as_int(ofertaId, "ofertaId")
        funcion = self.market_escrow.functions.cancelar(oferta_i)
        tx = self._construir_tx(funcion)
        resultado = self._chain.enviar_y_esperar(tx, timeout_s)
        return ResultadoCancelar(ofertaId=oferta_i, tx=resultado)
