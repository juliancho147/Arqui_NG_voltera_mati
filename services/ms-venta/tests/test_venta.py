"""Pruebas unitarias de la logica de dominio de ms_venta (VentaService).

Cubren R5.3 (publicar/cancelar con vendedor como parametro, devolver ofertaId), R5.9/R5.10
(confirmacion <=30 s sin reintento; reversion/timeout no completan la operacion) sin tocar
una cadena real, usando el `FakeChainClient` de conftest.
"""
from __future__ import annotations

import pytest
from conftest import FakeChainClient, confirmada, revertida, timeout

from venta import ResultadoCancelar, ResultadoPublicar, VentaError, VentaService

VENDEDOR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def test_publicar_llama_contrato_con_vendedor_como_parametro(fake_chain: FakeChainClient):
    # publicar confirma y el recibo trae el evento OfertaPublicada con ofertaId=42.
    fake_chain.resultados = [confirmada(tx_hash="0xhash1")]
    fake_chain.recibos["0xhash1"] = {"logs": [{"ofertaId": 42}]}
    svc = VentaService(fake_chain)

    res = svc.publicar(VENDEDOR, id=1001, kwh=30)

    assert isinstance(res, ResultadoPublicar)
    # El vendedor viaja como primer parametro de publicar(vendedor, id, kwh) (modelo custodial).
    llamada = fake_chain.llamadas[0]
    assert llamada.nombre == "publicar"
    assert llamada.args == (VENDEDOR, 1001, 30)
    # La tx se firma con la cuenta de la plataforma y nonce explicito.
    enviada = fake_chain.txs_enviadas[0]
    assert enviada["from"] == fake_chain.plataforma
    assert enviada["nonce"] == fake_chain.nonce_base


def test_publicar_devuelve_oferta_id_del_evento(fake_chain: FakeChainClient):
    fake_chain.resultados = [confirmada(tx_hash="0xhash1", gas=71000, bloque=12)]
    fake_chain.recibos["0xhash1"] = {"logs": [{"ofertaId": 7}]}
    svc = VentaService(fake_chain)

    res = svc.publicar(VENDEDOR, 2002, 55)

    assert res.ofertaId == 7
    assert res.tx.confirmada is True
    assert res.tx.gasUsed == 71000
    assert res.tx.blockNumber == 12
    assert res.as_dict()["ofertaId"] == 7


def test_publicar_revertida_no_asigna_oferta_id(fake_chain: FakeChainClient):
    # R5.9/R5.10: si la tx revierte, no se extrae ofertaId ni se marca completada.
    fake_chain.resultados = [revertida(tx_hash="0xhash1")]
    svc = VentaService(fake_chain)

    res = svc.publicar(VENDEDOR, 3003, 10)

    assert res.ofertaId is None
    assert res.tx.confirmada is False


def test_publicar_timeout_no_asigna_oferta_id(fake_chain: FakeChainClient):
    fake_chain.resultados = [timeout(tx_hash="0xhash1")]
    svc = VentaService(fake_chain)

    res = svc.publicar(VENDEDOR, 4004, 10)

    assert res.ofertaId is None
    assert res.tx.estado.value == "timeout"


def test_publicar_confirmada_sin_evento_deja_oferta_id_none(fake_chain: FakeChainClient):
    # Confirmada pero sin log OfertaPublicada: ofertaId no se puede extraer.
    fake_chain.resultados = [confirmada(tx_hash="0xhash1")]
    fake_chain.recibos["0xhash1"] = {"logs": []}
    svc = VentaService(fake_chain)

    res = svc.publicar(VENDEDOR, 5005, 10)

    assert res.ofertaId is None
    assert res.tx.confirmada is True


@pytest.mark.parametrize(
    "vendedor,id_,kwh",
    [
        ("", 1, 1),          # vendedor vacio
        (None, 1, 1),        # vendedor ausente
        (VENDEDOR, -1, 1),   # id negativo
        (VENDEDOR, 1, -5),   # kwh negativo
        (VENDEDOR, "x", 1),  # id no entero
    ],
)
def test_publicar_rechaza_parametros_invalidos(fake_chain: FakeChainClient, vendedor, id_, kwh):
    svc = VentaService(fake_chain)
    with pytest.raises(VentaError):
        svc.publicar(vendedor, id_, kwh)
    # No se envio ninguna transaccion ante parametros invalidos.
    assert fake_chain.txs_enviadas == []


def test_cancelar_llama_contrato_y_confirma(fake_chain: FakeChainClient):
    fake_chain.resultados = [confirmada(tx_hash="0xhash1", gas=30000, bloque=20)]
    svc = VentaService(fake_chain)

    res = svc.cancelar(42)

    assert isinstance(res, ResultadoCancelar)
    assert res.ofertaId == 42
    assert res.tx.confirmada is True
    llamada = fake_chain.llamadas[0]
    assert llamada.nombre == "cancelar"
    assert llamada.args == (42,)
    enviada = fake_chain.txs_enviadas[0]
    assert enviada["from"] == fake_chain.plataforma
    assert enviada["nonce"] == fake_chain.nonce_base


def test_cancelar_revertida_reporta_no_confirmada(fake_chain: FakeChainClient):
    fake_chain.resultados = [revertida(tx_hash="0xhash1")]
    svc = VentaService(fake_chain)

    res = svc.cancelar(99)

    assert res.ofertaId == 99
    assert res.tx.confirmada is False


def test_cancelar_rechaza_oferta_id_invalida(fake_chain: FakeChainClient):
    svc = VentaService(fake_chain)
    with pytest.raises(VentaError):
        svc.cancelar(-3)
    assert fake_chain.txs_enviadas == []
