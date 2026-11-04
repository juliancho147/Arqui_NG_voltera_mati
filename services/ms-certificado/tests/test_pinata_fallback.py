"""Prueba del fallback a almacen local cuando Pinata falla (R3.3), sin red real."""
from __future__ import annotations

from pathlib import Path

import pinata
from certificado_service import CertificadoService, Veredicto
from config import Config
from contenido import AlmacenContenidoDisco, calcular_cid
from pdf import generar_pdf
from tests.fakes import FakeChain


def _config(tmp_path: Path) -> Config:
    return Config(
        port=8085,
        rpc_url="http://localhost:8545",
        deployment_path=tmp_path / "deployment.json",
        almacen_dir=tmp_path / "almacen",
        pinata_jwt="jwt-de-prueba",
        pinata_gateway="https://gateway.pinata.cloud/ipfs/",
    )


def test_guardado_cae_al_fallback_si_pinata_falla(tmp_path: Path, monkeypatch) -> None:
    def _falla(*args, **kwargs):
        raise pinata.PinataNoDisponible("sin red")

    monkeypatch.setattr(pinata, "subir_pdf", _falla)

    cfg = _config(tmp_path)
    svc = CertificadoService(cfg, FakeChain(), AlmacenContenidoDisco(cfg.almacen_dir))
    resultado = svc.emitir_certificado(1, {"kwh": 5})

    # Pese a estar "habilitado", al fallar Pinata se guarda localmente con el mismo CID.
    assert resultado.almacenamiento == "local"
    assert resultado.cid == calcular_cid(generar_pdf(1, {"kwh": 5}))
    assert resultado.anclado is True


def test_verificacion_usa_fallback_si_gateway_falla(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pinata, "subir_pdf", lambda *a, **k: (_ for _ in ()).throw(pinata.PinataNoDisponible("x")))
    monkeypatch.setattr(pinata, "recuperar", lambda *a, **k: (_ for _ in ()).throw(pinata.PinataNoDisponible("x")))

    cfg = _config(tmp_path)
    svc = CertificadoService(cfg, FakeChain(), AlmacenContenidoDisco(cfg.almacen_dir))
    svc.emitir_certificado(2, {"kwh": 9})

    resultado = svc.verificar_certificado(2)
    # El gateway falla pero el blob local permite verificar INTEGRO por contenido.
    assert resultado.veredicto is Veredicto.INTEGRO
    assert resultado.origen == "local"
