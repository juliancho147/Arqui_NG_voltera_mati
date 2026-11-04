"""Pruebas de las rutas HTTP de ms_venta (`main.make_app_server`).

Levantan el servidor con un VentaService doble y verifican el ruteo de
`POST /ofertas`, `POST /ofertas/{id}/cancelar` y `GET /healthz`, los codigos de estado
(201/200 en confirmacion, 502 en no confirmacion, 400 en entrada invalida) y que el
`id` de la ruta se transmita a `cancelar`.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

import pytest
from conftest import confirmada, revertida

import main
from venta import ResultadoCancelar, ResultadoPublicar, VentaError

VENDEDOR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


@dataclass
class StubService:
    resultado_publicar: ResultadoPublicar | None = None
    resultado_cancelar: ResultadoCancelar | None = None
    publicar_args: tuple | None = None
    cancelar_arg: int | None = None

    def publicar(self, vendedor, id, kwh, timeout_s=None):
        self.publicar_args = (vendedor, id, kwh)
        return self.resultado_publicar

    def cancelar(self, ofertaId, timeout_s=None):
        self.cancelar_arg = ofertaId
        return self.resultado_cancelar


def _arrancar(service, health=lambda: {"ok": True}):
    server = main.make_app_server(0, service, health)
    import threading

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, server.server_address[1]


def _post(puerto: int, ruta: str, cuerpo: dict | None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else b""
    req = urllib.request.Request(
        f"http://127.0.0.1:{puerto}{ruta}", data=datos, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _get(puerto: int, ruta: str):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}{ruta}") as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_post_ofertas_confirmada_devuelve_201_y_oferta_id():
    stub = StubService(resultado_publicar=ResultadoPublicar(ofertaId=42, tx=confirmada()))
    server, puerto = _arrancar(stub)
    try:
        code, body = _post(puerto, "/ofertas", {"vendedor": VENDEDOR, "id": 1001, "kwh": 30})
    finally:
        server.shutdown()
    assert code == 201
    assert body["ofertaId"] == 42
    assert stub.publicar_args == (VENDEDOR, 1001, 30)


def test_post_ofertas_no_confirmada_devuelve_502():
    stub = StubService(resultado_publicar=ResultadoPublicar(ofertaId=None, tx=revertida()))
    server, puerto = _arrancar(stub)
    try:
        code, body = _post(puerto, "/ofertas", {"vendedor": VENDEDOR, "id": 1, "kwh": 1})
    finally:
        server.shutdown()
    assert code == 502
    assert body["ofertaId"] is None


def test_post_cancelar_pasa_id_de_la_ruta_y_devuelve_200():
    stub = StubService(resultado_cancelar=ResultadoCancelar(ofertaId=7, tx=confirmada()))
    server, puerto = _arrancar(stub)
    try:
        code, body = _post(puerto, "/ofertas/7/cancelar", None)
    finally:
        server.shutdown()
    assert code == 200
    assert body["ofertaId"] == 7
    assert stub.cancelar_arg == 7


def test_post_cancelar_no_confirmada_devuelve_502():
    stub = StubService(resultado_cancelar=ResultadoCancelar(ofertaId=9, tx=revertida()))
    server, puerto = _arrancar(stub)
    try:
        code, _ = _post(puerto, "/ofertas/9/cancelar", None)
    finally:
        server.shutdown()
    assert code == 502


def test_post_ofertas_parametro_invalido_devuelve_400():
    class Rechaza(StubService):
        def publicar(self, vendedor, id, kwh, timeout_s=None):
            raise VentaError("'vendedor' debe ser una direccion")

    server, puerto = _arrancar(Rechaza())
    try:
        code, body = _post(puerto, "/ofertas", {"id": 1, "kwh": 1})
    finally:
        server.shutdown()
    assert code == 400
    assert "error" in body


def test_healthz_ok_devuelve_200():
    server, puerto = _arrancar(StubService(), health=lambda: {"ok": True, "service": "ms-venta"})
    try:
        code, body = _get(puerto, "/healthz")
    finally:
        server.shutdown()
    assert code == 200
    assert body["ok"] is True


def test_healthz_no_listo_devuelve_503():
    server, puerto = _arrancar(StubService(), health=lambda: {"ok": False})
    try:
        code, _ = _get(puerto, "/healthz")
    finally:
        server.shutdown()
    assert code == 503


def test_ruta_desconocida_devuelve_404():
    server, puerto = _arrancar(StubService())
    try:
        code, _ = _post(puerto, "/desconocido", {})
    finally:
        server.shutdown()
    assert code == 404
