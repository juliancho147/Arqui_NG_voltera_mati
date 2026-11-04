"""Pruebas del servidor HTTP de ms_energia: `POST /emisiones` y `GET /healthz`."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from web3 import Web3

from emitter import EmisionService
from server import make_server, serve_in_thread
from tests.fakes import EstadoTx, FakeChain, ResultadoTx

A = "0x" + "11" * 20


@pytest.fixture()
def servidor():
    chain = FakeChain()
    svc = EmisionService(chain=chain)
    server = make_server(0, svc, check=lambda: {"ok": True, "service": "ms-energia"})
    serve_in_thread(server)
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}", chain, svc
    finally:
        server.shutdown()


def _post(base: str, path: str, obj: dict):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _get(base: str, path: str):
    req = urllib.request.Request(base + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_healthz_ok(servidor):
    base, _chain, _svc = servidor
    code, body = _get(base, "/healthz")
    assert code == 200 and body["ok"] is True


def test_post_emisiones_confirmada(servidor):
    base, chain, _svc = servidor
    code, body = _post(base, "/emisiones", {"a": A, "id": 7, "kwh": 100, "precio": 5, "lecturaId": "L1"})
    assert code == 200
    assert body["emitida"] is True and body["lecturaId"] == "L1"
    assert len(chain.emitir_calls) == 1


def test_post_emisiones_idempotente(servidor):
    base, chain, _svc = servidor
    body1 = {"a": A, "id": 7, "kwh": 100, "precio": 5, "lecturaId": "L1"}
    _post(base, "/emisiones", body1)
    code, body = _post(base, "/emisiones", body1)
    assert code == 200 and body["duplicada"] is True
    assert len(chain.emitir_calls) == 1


def test_post_emisiones_payload_invalido(servidor):
    base, _chain, _svc = servidor
    code, body = _post(base, "/emisiones", {"a": A, "kwh": 0, "lecturaId": "L1", "id": 1, "precio": 2})
    assert code == 400 and "error" in body


def test_post_emisiones_revertida_502(servidor):
    base, chain, svc = servidor
    chain.resultado = ResultadoTx(EstadoTx.REVERTIDA, "0xrev")
    code, body = _post(base, "/emisiones", {"a": A, "id": 7, "kwh": 100, "precio": 5, "lecturaId": "L9"})
    assert code == 502
    assert body["emitida"] is False and body["estado"] == "revertida"


def test_ruta_desconocida_404(servidor):
    base, _chain, _svc = servidor
    code, _ = _post(base, "/otra", {})
    assert code == 404
