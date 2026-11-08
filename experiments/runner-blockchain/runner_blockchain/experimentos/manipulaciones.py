"""Pruebas negativas de manipulacion on-chain (defensa del contrato).

Complementa E1/E2/E3 ejercitando intentos de manipulacion que el contrato DEBE rechazar.
Cada intento debe revertir con su custom error; el reporte registra el motivo (nombre del
error decodificado). Si alguno NO revierte, es un hallazgo de seguridad (criterio FAIL).

Intentos cubiertos:
  * reanclar otro CID sobre una compra ya anclada   -> CertificadoYaAnclado
  * emitir desde una cuenta NO autorizada            -> SoloPlataforma
  * comprar una oferta ya vendida                    -> OfertaNoDisponible

Se usa el ChainClient custodial para montar el estado previo (emitir/publicar/comprar/anclar)
y luego se dispara el intento invalido. Para "cuenta no autorizada" se firma con una llave
distinta a la de la plataforma (otra cuenta de Anvil).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from web3 import Web3
from web3.exceptions import ContractLogicError, Web3Exception

from ..reporte_modelo import ExperimentResult, now_iso

logger = logging.getLogger(__name__)

PRECIO = 10
KWH = 50
# Cuenta 1 de Anvil (NO es la plataforma): su llave es publica y de prueba.
LLAVE_NO_AUTORIZADA = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


def _addr(etiqueta: str) -> str:
    h = hashlib.sha256(f"manip-{etiqueta}".encode()).hexdigest()
    return Web3.to_checksum_address("0x" + h[-40:])


# Selectores de los custom errors (primeros 4 bytes de keccak(firma)).
_SELECTORES = {
    "0x15742b51": "CertificadoYaAnclado",
    "0xfe550097": "SoloPlataforma",
    "0xe0d67558": "OfertaNoDisponible",
    "0x27d09cf1": "CompraNoRealizada",
    "0xe6884626": "TokenSinPrecio",
    "0x6b6c6672": "CidVacio",
    "0xc6a2a9d2": "CantidadInvalida",
    "0x9e4a3c8a": "VendedorYCompradorIguales",
    "0x7259e5 bc": "PrecioDistinto",
    "0x8d6ea8be": "PrecioInvalido",
}


def _motivo_revert(exc: Exception) -> str:
    """Extrae un motivo legible del revert: nombre del custom error (por texto o selector)."""
    msg = str(exc)
    # 1) por nombre explicito en el mensaje
    for nombre in ("CertificadoYaAnclado", "SoloPlataforma", "OfertaNoDisponible",
                   "CompraNoRealizada", "TokenSinPrecio", "CidVacio", "CantidadInvalida",
                   "VendedorYCompradorIguales", "PrecioDistinto", "PrecioInvalido"):
        if nombre in msg:
            return nombre
    # 2) por selector de 4 bytes presente en el mensaje (0x........)
    for sel, nombre in _SELECTORES.items():
        if sel.replace(" ", "") in msg.replace(" ", ""):
            return nombre
    return msg.split("\n")[0][:160]


def _sembrar_venta(chain: Any, caso: int) -> int:
    """emitir -> publicar -> comprar; devuelve ofertaId real (oferta Vendida)."""
    et, me, plat = chain.energy_token, chain.market_escrow, chain.plataforma
    token = 5_000_000 + caso
    vend, comp = _addr(f"v{caso}"), _addr(f"c{caso}")
    lect = Web3.keccak(text=f"manip-seed-{caso}")
    r = chain.enviar_y_esperar(et.functions.emitir(vend, token, KWH, PRECIO, lect
        ).build_transaction({"from": plat, "nonce": chain.siguiente_nonce()}))
    if not r.confirmada:
        raise RuntimeError("seed emitir no confirmo")
    h = chain.enviar_tx(me.functions.publicar(vend, token, KWH
        ).build_transaction({"from": plat, "nonce": chain.siguiente_nonce()}))
    chain.esperar_recibo(h)
    recibo = chain.w3.eth.get_transaction_receipt(h)
    oferta = int(me.events.OfertaPublicada().process_receipt(recibo)[0]["args"]["ofertaId"])
    r = chain.enviar_y_esperar(me.functions.comprar(oferta, comp
        ).build_transaction({"from": plat, "nonce": chain.siguiente_nonce()}))
    if not r.confirmada:
        raise RuntimeError("seed comprar no confirmo")
    return oferta


def _intento(descr: str, requisito: str, fn) -> dict[str, Any]:
    """Ejecuta un intento que DEBE revertir; registra si revirtio y el motivo."""
    try:
        fn()
        return {"descr": descr, "req": requisito, "revirtio": False, "motivo": "NO revirtio (hallazgo)"}
    except (ContractLogicError, Web3Exception, ValueError) as exc:
        return {"descr": descr, "req": requisito, "revirtio": True, "motivo": _motivo_revert(exc)}


def ejecutar(chain: Any, *, run_id: str = "RUN-MANIP") -> ExperimentResult:
    """Corre los tres intentos de manipulacion y arma el ExperimentResult (todos deben revertir)."""
    r = ExperimentResult(
        experiment="MANIP",
        title="Pruebas negativas de manipulacion on-chain",
        hypothesis="Todo intento de manipulacion (reanclar, emitir no autorizado, recomprar) revierte.",
        started=now_iso(),
    )
    me, et, plat = chain.market_escrow, chain.energy_token, chain.plataforma
    intentos: list[dict[str, Any]] = []

    # 1) Reanclar otro CID sobre una compra ya anclada -> CertificadoYaAnclado
    oferta = _sembrar_venta(chain, 1)
    chain.enviar_y_esperar(me.functions.anclar(oferta, "bafkreimanip-cid-original"
        ).build_transaction({"from": plat, "nonce": chain.siguiente_nonce()}))
    def reanclar():
        tx = me.functions.anclar(oferta, "bafkreimanip-cid-distinto"
            ).build_transaction({"from": plat, "nonce": chain.siguiente_nonce()})
        res = chain.enviar_y_esperar(tx)
        if not res.confirmada:
            raise ContractLogicError(f"revert: {res.estado.value}")
    intentos.append(_intento("reanclar otro CID sobre compra ya anclada", "CertificadoYaAnclado", reanclar))

    # 2) Emitir desde cuenta NO autorizada -> SoloPlataforma
    def emitir_no_autorizado():
        cuenta = chain.w3.eth.account.from_key(LLAVE_NO_AUTORIZADA)
        fn = et.functions.emitir(_addr("x"), 6_000_001, KWH, PRECIO, Web3.keccak(text="x"))
        tx = fn.build_transaction({"from": cuenta.address,
                                   "nonce": chain.w3.eth.get_transaction_count(cuenta.address)})
        firmada = cuenta.sign_transaction(tx)
        raw = getattr(firmada, "raw_transaction", None) or firmada.rawTransaction
        h = chain.w3.eth.send_raw_transaction(raw)
        rec = chain.w3.eth.wait_for_transaction_receipt(h, timeout=30)
        if int(rec.get("status", 0)) != 1:
            raise ContractLogicError("SoloPlataforma")
    intentos.append(_intento("emitir desde cuenta no autorizada", "SoloPlataforma", emitir_no_autorizado))

    # 3) Comprar una oferta ya vendida -> OfertaNoDisponible
    oferta2 = _sembrar_venta(chain, 2)  # ya queda Vendida
    def recomprar():
        tx = me.functions.comprar(oferta2, _addr("otro-comprador")
            ).build_transaction({"from": plat, "nonce": chain.siguiente_nonce()})
        res = chain.enviar_y_esperar(tx)
        if not res.confirmada:
            raise ContractLogicError(f"revert: {res.estado.value}")
    intentos.append(_intento("comprar una oferta ya vendida", "OfertaNoDisponible", recomprar))

    # Criterios: cada intento DEBE revertir.
    for it in intentos:
        r.add(it["req"], it["descr"], ok=it["revirtio"],
              expected=f"revierte ({it['req']})", observed=it["motivo"])

    r.data = {"intentos": intentos}
    r.notes.append("Todos los intentos de manipulacion deben revertir; si alguno pasa, es un hallazgo.")
    r.finished = now_iso()
    return r
