"""Pruebas del orquestador `Oraculo` y de los endpoints HTTP de ms_oraculo (R2.3, R2.4, R5.1)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from config import Settings
from health import serve_in_thread
from main import Oraculo, PublicacionError, make_app_server
from oraculo import VALOR_ALTERADO


def _payload(**over):
    base = {
        "lecturaId": "L-1",
        "medidorId": "MED-001",
        "epoca": 202606,
        "fuente": "solar",
        "kwh": 120,
        "precio": 5,
        "participante": "0xabc",
    }
    base.update(over)
    return base


class _Spy:
    """Publicador espia: cuenta publicaciones de GeneracionValidada por lecturaId."""

    def __init__(self, falla=False):
        self.llamadas = []
        self.falla = falla

    def __call__(self, lectura):
        if self.falla:
            raise PublicacionError("ms_energia caido")
        self.llamadas.append(lectura.lectura_id)
        return {"emitido": True}


def _oraculo(pub):
    return Oraculo(Settings(), pub)


def test_acepta_y_publica_generacion_validada():
    spy = _Spy()
    ora = _oraculo(spy)
    v = ora.procesar(_payload())
    assert v.aceptada is True
    assert spy.llamadas == ["L-1"]  # exactamente una publicacion (R2.4, R5.1)
    assert ora.aceptadas == 1


def test_rechaza_sin_publicar():
    spy = _Spy()
    ora = _oraculo(spy)
    v = ora.procesar(_payload(medidorId="MED-999"))
    assert v.aceptada is False
    assert spy.llamadas == []  # sin emision (R2.3)
    assert ora.rechazadas == 1


def test_duplicado_se_rechaza_tras_aceptar_el_primero():
    spy = _Spy()
    ora = _oraculo(spy)
    assert ora.procesar(_payload(lecturaId="L-1")).aceptada is True
    # mismo lecturaId -> duplicado
    assert ora.procesar(_payload(lecturaId="L-1")).aceptada is False
    # mismo (medidor, epoca), distinto id -> duplicado
    assert ora.procesar(_payload(lecturaId="L-2")).aceptada is False
    assert spy.llamadas == ["L-1"]  # solo la primera publico


def test_lectura_invalida_no_se_registra_como_duplicado():
    spy = _Spy()
    ora = _oraculo(spy)
    # primera invalida por valor
    assert ora.procesar(_payload(lecturaId="L-9", kwh=999)).categoria == VALOR_ALTERADO
    # misma (medidor, epoca) pero ahora valida: NO debe verse como duplicada porque la anterior se rechazo
    assert ora.procesar(_payload(lecturaId="L-10", kwh=120)).aceptada is True


def test_fallo_de_publicacion_no_marca_como_emitida():
    spy = _Spy(falla=True)
    ora = _oraculo(spy)
    with pytest.raises(PublicacionError):
        ora.procesar(_payload())
    assert ora.aceptadas == 0
    # como no se registro, un reintento posterior (con publicador sano) debe poder aceptarla
    spy.falla = False
    assert ora.procesar(_payload()).aceptada is True


# --- Endpoints HTTP ---

def _start_server(ora):
    srv = make_app_server(0, ora, lambda: {"ok": True})
    serve_in_thread(srv)
    return srv, srv.server_address[1]


def _post(port, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_endpoint_lecturas_acepta():
    srv, port = _start_server(_oraculo(_Spy()))
    try:
        code, body = _post(port, "/lecturas", _payload())
        assert code == 200
        assert body == {"aceptada": True, "lecturaId": "L-1"}
    finally:
        srv.shutdown()


def test_endpoint_lecturas_rechaza_con_motivo_y_categoria():
    srv, port = _start_server(_oraculo(_Spy()))
    try:
        code, body = _post(port, "/lecturas", _payload(medidorId="MED-999"))
        assert code == 200
        assert body["aceptada"] is False
        assert body["categoria"] == "medidor_desconocido"
        assert body["motivo"]
    finally:
        srv.shutdown()


def test_endpoint_contrato_invalido_responde_400():
    srv, port = _start_server(_oraculo(_Spy()))
    try:
        code, body = _post(port, "/lecturas", {"lecturaId": "L-1"})
        assert code == 400
    finally:
        srv.shutdown()


def test_endpoint_emision_fallida_responde_502():
    srv, port = _start_server(_oraculo(_Spy(falla=True)))
    try:
        code, body = _post(port, "/lecturas", _payload())
        assert code == 502
    finally:
        srv.shutdown()


def test_healthz_responde_ok():
    srv, port = _start_server(_oraculo(_Spy()))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
            assert r.status == 200
            assert json.loads(r.read())["ok"] is True
    finally:
        srv.shutdown()
