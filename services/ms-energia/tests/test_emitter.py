"""Pruebas unitarias de la emision idempotente por lectura de ms_energia (R5.2, R5.9, R5.10)."""
from __future__ import annotations

import threading

import pytest
from web3 import Web3

from emitter import EmisionService, GeneracionValidada, ValidacionError
from tests.fakes import EstadoTx, FakeChain, ResultadoTx

A = "0x" + "11" * 20  # direccion de participante valida


def payload(**over):
    base = {"a": A, "id": 7, "kwh": 100, "precio": 5, "lecturaId": "lect-1"}
    base.update(over)
    return base


# ---- parseo / validacion -----------------------------------------------------

def test_payload_valido_resuelve_campos():
    gen = GeneracionValidada.desde_payload(payload())
    assert gen.a == Web3.to_checksum_address(A)
    assert (gen.id, gen.kwh, gen.precio, gen.lectura_id) == (7, 100, 5, "lect-1")


@pytest.mark.parametrize(
    "over",
    [
        {"lecturaId": ""},
        {"a": "no-es-direccion"},
        {"kwh": 0},
        {"precio": 0},
        {"kwh": -3},
    ],
)
def test_payload_invalido_rechazado(over):
    with pytest.raises(ValidacionError):
        GeneracionValidada.desde_payload(payload(**over))


def test_falta_id_sin_fuente_epoca_es_invalido():
    p = payload()
    del p["id"]
    with pytest.raises(ValidacionError):
        GeneracionValidada.desde_payload(p)


def test_id_derivado_de_fuente_y_epoca():
    p = payload()
    del p["id"]
    p.update(fuente="solar", epoca=202610)
    gen = GeneracionValidada.desde_payload(p)
    assert isinstance(gen.id, int) and gen.id > 0
    # determinista: misma fuente+epoca => mismo id
    assert gen.id == GeneracionValidada.desde_payload({**p}).id


# ---- emision + confirmacion --------------------------------------------------

def test_emision_confirmada_llama_emitir_una_vez_con_los_argumentos():
    chain = FakeChain()
    svc = EmisionService(chain=chain, confirm_timeout_s=30)

    res = svc.emitir(GeneracionValidada.desde_payload(payload()))

    assert res.emitida is True
    assert res.estado == "confirmada"
    assert res.transaction_hash == "0xhash"
    assert res.gas_used == 21000 and res.block_number == 1
    assert len(chain.emitir_calls) == 1
    a, id_, kwh, precio, lectura_b32 = chain.emitir_calls[0]
    assert (a, id_, kwh, precio) == (Web3.to_checksum_address(A), 7, 100, 5)
    # lecturaId viaja como bytes32 derivado de keccak del texto
    assert lectura_b32 == Web3.keccak(text="lect-1")
    # se respeta el tope de confirmacion (R5.9)
    assert chain.enviadas[0][1] == 30


def test_lectura_id_hex_de_32_bytes_se_usa_literal():
    lectura_hex = "0x" + "ab" * 32
    chain = FakeChain()
    svc = EmisionService(chain=chain)
    svc.emitir(GeneracionValidada.desde_payload(payload(lecturaId=lectura_hex)))
    _, _, _, _, lectura_b32 = chain.emitir_calls[0]
    assert lectura_b32 == bytes.fromhex("ab" * 32)


# ---- idempotencia por lecturaId ---------------------------------------------

def test_reentrega_mismo_lectura_id_no_reemite():
    chain = FakeChain()
    svc = EmisionService(chain=chain)

    primero = svc.emitir(GeneracionValidada.desde_payload(payload()))
    segundo = svc.emitir(GeneracionValidada.desde_payload(payload()))
    tercero = svc.emitir(GeneracionValidada.desde_payload(payload(kwh=999)))  # mismo lecturaId

    assert len(chain.emitir_calls) == 1  # exactamente un emitir => exactamente un Emitido
    assert primero.duplicada is False
    assert segundo.duplicada is True and tercero.duplicada is True
    # la reentrega conserva el resultado original (misma tx), no re-emite con kwh distinto
    assert segundo.transaction_hash == primero.transaction_hash


def test_lecturas_distintas_emiten_por_separado():
    chain = FakeChain()
    svc = EmisionService(chain=chain)
    svc.emitir(GeneracionValidada.desde_payload(payload(lecturaId="lect-1")))
    svc.emitir(GeneracionValidada.desde_payload(payload(lecturaId="lect-2")))
    assert len(chain.emitir_calls) == 2


def test_idempotencia_bajo_concurrencia_un_solo_emitir():
    # 20 entregas concurrentes del MISMO lecturaId => exactamente un emitir.
    chain = FakeChain(delay=0.01)
    svc = EmisionService(chain=chain)
    resultados: list = []
    lock = threading.Lock()

    def worker():
        r = svc.emitir(GeneracionValidada.desde_payload(payload()))
        with lock:
            resultados.append(r)

    hilos = [threading.Thread(target=worker) for _ in range(20)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert len(chain.emitir_calls) == 1
    assert sum(1 for r in resultados if not r.duplicada) == 1
    assert sum(1 for r in resultados if r.duplicada) == 19


# ---- manejo de error (R5.10): sin reintento, sin marcar completada ----------

def test_revertida_no_marca_completada_y_registra_error():
    chain = FakeChain(resultado=ResultadoTx(EstadoTx.REVERTIDA, "0xrev"))
    svc = EmisionService(chain=chain)
    res = svc.emitir(GeneracionValidada.desde_payload(payload()))
    assert res.emitida is False
    assert res.estado == "revertida"
    assert res.error and "lect-1" in res.error


def test_timeout_no_marca_completada_y_registra_error():
    chain = FakeChain(resultado=ResultadoTx(EstadoTx.TIMEOUT, "0xto"))
    svc = EmisionService(chain=chain)
    res = svc.emitir(GeneracionValidada.desde_payload(payload()))
    assert res.emitida is False
    assert res.estado == "timeout"
    assert res.error and "lect-1" in res.error


def test_resultado_terminal_fallido_no_se_reintenta_en_reentrega():
    # Tras un fallo terminal, una reentrega del mismo lecturaId NO dispara otra tx (R5.10).
    chain = FakeChain(resultado=ResultadoTx(EstadoTx.TIMEOUT, "0xto"))
    svc = EmisionService(chain=chain)
    svc.emitir(GeneracionValidada.desde_payload(payload()))
    segundo = svc.emitir(GeneracionValidada.desde_payload(payload()))
    assert len(chain.emitir_calls) == 1
    assert segundo.duplicada is True and segundo.emitida is False
