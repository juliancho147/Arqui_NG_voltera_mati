"""Pruebas unitarias de ms_certificado: emision, anclaje, fallback y verificacion.

Cubren el comportamiento de la tarea 6.3 sin tocar Anvil ni Pinata reales: se usa un cliente
de cadena en memoria (`FakeChain`) y el fallback local de contenido direccionable. Los
casos ejercitan R3.2/R3.3/R3.5/R3.7/R3.11/R3.12/R5.5/R5.6/R5.11.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from certificado_service import CertificadoError, CertificadoService, Veredicto
from config import Config
from contenido import AlmacenContenidoDisco, calcular_cid
from pdf import generar_pdf
from tests.fakes import FakeChain


def _config(tmp_path: Path, *, pinata: bool = False) -> Config:
    return Config(
        port=8085,
        rpc_url="http://localhost:8545",
        deployment_path=tmp_path / "deployment.json",
        almacen_dir=tmp_path / "almacen",
        pinata_jwt="jwt-de-prueba" if pinata else None,
        pinata_gateway="https://gateway.pinata.cloud/ipfs/",
    )


def _servicio(tmp_path: Path, chain: FakeChain, *, pinata: bool = False) -> CertificadoService:
    cfg = _config(tmp_path, pinata=pinata)
    return CertificadoService(cfg, chain, AlmacenContenidoDisco(cfg.almacen_dir))


DATOS = {"comprador": "0xabc", "kwh": 10, "precio": 3}


def test_pdf_es_determinista_por_contenido(tmp_path: Path) -> None:
    # R3.2: mismos datos -> mismos bytes -> mismo CID (insumo de Property 5).
    a = generar_pdf(1, DATOS)
    b = generar_pdf(1, DATOS)
    assert a == b
    assert calcular_cid(a) == calcular_cid(b)
    # Datos distintos -> contenido distinto.
    assert generar_pdf(1, DATOS) != generar_pdf(2, DATOS)


def test_emitir_guarda_en_fallback_y_ancla(tmp_path: Path) -> None:
    # Sin credenciales de Pinata: el guardado usa el almacen local y se ancla el CID (R3.3, R5.5).
    chain = FakeChain()
    svc = _servicio(tmp_path, chain)

    resultado = svc.emitir_certificado(1, DATOS)

    assert resultado.almacenamiento == "local"
    assert resultado.anclado is True
    assert resultado.tx_hash == "0xhash"
    # El CID anclado on-chain coincide con el CID por contenido del PDF generado.
    assert chain.certificados[1] == calcular_cid(generar_pdf(1, DATOS))
    assert resultado.cid == chain.certificados[1]


def test_no_ancla_si_el_anclaje_revierte_y_registra_compra(tmp_path: Path) -> None:
    # R5.11: si el anclaje no confirma, no queda anclado y la compra se registra como afectada.
    chain = FakeChain(anclaje_confirma=False)
    svc = _servicio(tmp_path, chain)

    resultado = svc.emitir_certificado(7, DATOS)

    assert resultado.anclado is False
    assert resultado.tx_hash is None
    assert 7 not in chain.certificados
    assert any(c["ofertaId"] == 7 for c in svc.compras_sin_anclar)


def test_verificar_integro_para_contenido_original(tmp_path: Path) -> None:
    # R3.5/R3.7: el contenido original contra su CID anclado devuelve INTEGRO.
    chain = FakeChain()
    svc = _servicio(tmp_path, chain)
    svc.emitir_certificado(1, DATOS)

    resultado = svc.verificar_certificado(1)

    assert resultado.veredicto is Veredicto.INTEGRO
    assert resultado.cid_anclado == resultado.cid_recalculado


def test_verificar_alterado_cuando_el_contenido_cambia(tmp_path: Path) -> None:
    # R3.6/R3.8: si el blob bajo el CID anclado se altera, la verificacion devuelve ALTERADO.
    chain = FakeChain()
    svc = _servicio(tmp_path, chain)
    resultado_emision = svc.emitir_certificado(1, DATOS)

    # Se corrompe el blob almacenado bajo ese CID (simula alteracion del contenido recuperado).
    ruta = (tmp_path / "almacen") / resultado_emision.cid
    datos = bytearray(ruta.read_bytes())
    datos[-10] ^= 0xFF
    ruta.write_bytes(bytes(datos))
    svc._almacen._blobs.clear()  # forzar relectura desde disco

    resultado = svc.verificar_certificado(1)

    assert resultado.veredicto is Veredicto.ALTERADO
    assert resultado.cid_recalculado != resultado.cid_anclado


def test_verificar_error_si_no_hay_cid_anclado(tmp_path: Path) -> None:
    # R3.11: sin CID anclado, el veredicto es ERROR (nunca INTEGRO).
    chain = FakeChain()
    svc = _servicio(tmp_path, chain)

    resultado = svc.verificar_certificado(99)

    assert resultado.veredicto is Veredicto.ERROR
    assert resultado.veredicto is not Veredicto.INTEGRO


def test_verificar_error_si_contenido_no_recuperable(tmp_path: Path) -> None:
    # R3.12: hay CID anclado pero el contenido no esta en ningun almacen -> ERROR.
    chain = FakeChain()
    svc = _servicio(tmp_path, chain)
    # Se ancla un CID que no corresponde a ningun blob guardado.
    chain.certificados[5] = calcular_cid(b"contenido-inexistente")

    resultado = svc.verificar_certificado(5)

    assert resultado.veredicto is Veredicto.ERROR
    assert resultado.cid_anclado == chain.certificados[5]
