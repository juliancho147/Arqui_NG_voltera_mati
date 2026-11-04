"""Pruebas unitarias de ms_compra (R5.4, R5.9, R5.10).

Cubren:
  * compra individual confirmada / revertida / timeout, con hash de tx (R5.4);
  * sin reintento ante reversion/timeout (R5.10);
  * modo concurrente: nonces explicitos (una sola lectura), envio en paralelo y, para una
    oferta Activa, exactamente una confirma y el resto revierte (R4.1/R4.2 ejercitado por E3);
  * endpoints HTTP `GET /healthz`, `POST /compras`, `POST /compras/concurrentes`.
"""
from __future__ import annotations

from main import CompraService, ResultadoCompra, make_handler

from fakes import FakeChainClient


# ---- compra individual ------------------------------------------------------------------
def test_compra_confirmada_devuelve_exito_y_hash() -> None:
    chain = FakeChainClient(ofertas_activas={1})
    service = CompraService(chain)

    res = service.comprar(1, "0xCOMPRADOR")

    assert isinstance(res, ResultadoCompra)
    assert res.exito is True
    assert res.estado == "confirmada"
    assert res.transactionHash is not None
    assert res.gasUsed == 50_000
    assert res.blockNumber == 1
    # El comprador viaja como parametro de comprar(ofertaId, comprador).
    tx = chain.txs_enviadas[0]
    assert tx["fn"] == "comprar" and tx["ofertaId"] == 1 and tx["comprador"] == "0xCOMPRADOR"
    assert tx["from"] == chain.plataforma


def test_compra_sobre_oferta_no_activa_revierte_sin_exito() -> None:
    chain = FakeChainClient(ofertas_activas=set())  # oferta 9 no esta Activa
    service = CompraService(chain)

    res = service.comprar(9, "0xCOMPRADOR")

    assert res.exito is False
    assert res.estado == "revertida"
    # Aun en reversion se conserva el hash para evidencia.
    assert res.transactionHash is not None


def test_compra_timeout_no_reintenta() -> None:
    chain = FakeChainClient(ofertas_activas={1}, forzar_timeout=True)
    service = CompraService(chain)

    res = service.comprar(1, "0xCOMPRADOR")

    assert res.exito is False
    assert res.estado == "timeout"
    # Sin reintento: exactamente un envio (R5.10).
    assert len(chain.txs_enviadas) == 1


# ---- modo concurrente (E3) --------------------------------------------------------------
def test_concurrente_una_sola_lectura_de_nonce_y_nonces_explicitos() -> None:
    chain = FakeChainClient(ofertas_activas={1}, nonce_base=100)
    service = CompraService(chain)
    compradores = [f"0xC{i}" for i in range(5)]

    service.comprar_concurrente(1, compradores)

    # Una unica lectura de eth_getTransactionCount para repartir los nonces.
    assert chain.lecturas_nonce == 1
    # Nonces explicitos secuenciales base, base+1, ...
    assert chain.nonces_asignados == [100, 101, 102, 103, 104]
    # Cada tx enviada llevo su nonce explicito.
    nonces_en_tx = sorted(tx["nonce"] for tx in chain.txs_enviadas)
    assert nonces_en_tx == [100, 101, 102, 103, 104]


def test_concurrente_sobre_oferta_activa_confirma_exactamente_una() -> None:
    chain = FakeChainClient(ofertas_activas={42})
    service = CompraService(chain)
    compradores = [f"0xC{i}" for i in range(100)]

    resultados = service.comprar_concurrente(42, compradores)

    assert len(resultados) == 100
    confirmadas = [r for r in resultados if r.exito]
    revertidas = [r for r in resultados if not r.exito]
    assert len(confirmadas) == 1
    assert len(revertidas) == 99
    assert all(r.estado == "revertida" for r in revertidas)
    # Se enviaron las 100 transacciones (disparo en paralelo).
    assert len(chain.txs_enviadas) == 100


def test_concurrente_resultados_en_orden_de_compradores() -> None:
    chain = FakeChainClient(ofertas_activas={5})
    service = CompraService(chain)
    compradores = ["0xA", "0xB", "0xC"]

    resultados = service.comprar_concurrente(5, compradores)

    assert [r.comprador for r in resultados] == compradores


def test_concurrente_lista_vacia_no_lee_nonce() -> None:
    chain = FakeChainClient(ofertas_activas={1})
    service = CompraService(chain)

    resultados = service.comprar_concurrente(1, [])

    assert resultados == []
    assert chain.lecturas_nonce == 0
    assert chain.txs_enviadas == []


# ---- transporte HTTP --------------------------------------------------------------------
def _invocar(service: CompraService, metodo: str, path: str, cuerpo: dict | None = None):
    """Invoca el handler HTTP en memoria y devuelve (status, payload_json)."""
    import io
    import json

    Handler = make_handler(service)

    cuerpo_bytes = json.dumps(cuerpo).encode() if cuerpo is not None else b""
    cabeceras = f"{metodo} {path} HTTP/1.1\r\nContent-Length: {len(cuerpo_bytes)}\r\n\r\n"
    entrada = io.BytesIO(cabeceras.encode() + cuerpo_bytes)
    salida = io.BytesIO()

    class _Conn:
        def makefile(self, mode, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            return entrada if "r" in mode else salida

        def sendall(self, data):  # noqa: ANN001
            salida.write(data)

    Handler(_Conn(), ("127.0.0.1", 0), server=None)

    salida.seek(0)
    bruto = salida.getvalue().decode("utf-8", errors="replace")
    encabezado, _, cuerpo_resp = bruto.partition("\r\n\r\n")
    status = int(encabezado.splitlines()[0].split()[1])
    payload = json.loads(cuerpo_resp) if cuerpo_resp.strip() else {}
    return status, payload


def test_http_healthz() -> None:
    service = CompraService(FakeChainClient())
    status, payload = _invocar(service, "GET", "/healthz")
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["service"] == "ms_compra"


def test_http_post_compras_confirmada() -> None:
    service = CompraService(FakeChainClient(ofertas_activas={3}))
    status, payload = _invocar(service, "POST", "/compras", {"ofertaId": 3, "comprador": "0xZ"})
    assert status == 200
    assert payload["exito"] is True
    assert payload["transactionHash"] is not None


def test_http_post_compras_revertida_devuelve_409() -> None:
    service = CompraService(FakeChainClient(ofertas_activas=set()))
    status, payload = _invocar(service, "POST", "/compras", {"ofertaId": 3, "comprador": "0xZ"})
    assert status == 409
    assert payload["exito"] is False


def test_http_post_compras_payload_invalido() -> None:
    service = CompraService(FakeChainClient())
    status, payload = _invocar(service, "POST", "/compras", {"comprador": "0xZ"})
    assert status == 400
    assert "error" in payload


def test_http_post_concurrentes_resumen() -> None:
    service = CompraService(FakeChainClient(ofertas_activas={7}))
    status, payload = _invocar(
        service,
        "POST",
        "/compras/concurrentes",
        {"ofertaId": 7, "compradores": ["0xA", "0xB", "0xC", "0xD"]},
    )
    assert status == 200
    assert payload["resumen"]["total"] == 4
    assert payload["resumen"]["confirmadas"] == 1
    assert payload["resumen"]["revertidas"] == 3
    assert len(payload["resultados"]) == 4


def test_http_ruta_desconocida() -> None:
    service = CompraService(FakeChainClient())
    status, _ = _invocar(service, "GET", "/no-existe")
    assert status == 404
