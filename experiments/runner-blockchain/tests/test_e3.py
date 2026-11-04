"""Pruebas de E3 con dobles de los microservicios y del Lector_Eventos.

Validan la logica off-chain de E3 (generacion reproducible, analisis de evidencia,
metricas y veredicto PASS/FAIL) sin requerir la Cadena_Local: se inyectan clientes falsos
de ms_venta/ms_compra y un Lector_Eventos que devuelve eventos sinteticos. La atomicidad
del escrow la validan los tests Foundry y la corrida real (fuera de alcance aqui).
"""
from __future__ import annotations

from runner_blockchain.eventos.lector import EventoOnChain
from runner_blockchain.experimentos import e3
from runner_blockchain.reporte_modelo import FAIL, PASS


class FakeVenta:
    """ms_venta falso: asigna ofertaId secuenciales y registra las publicaciones."""

    def __init__(self, fallar_indices=()):
        self._next = 1
        self.publicadas: list[tuple[str, int, int]] = []
        self._fallar = set(fallar_indices)
        self._i = 0

    def publicar(self, vendedor, token_id, kwh):
        idx = self._i
        self._i += 1
        if idx in self._fallar:
            return None
        oferta_id = self._next
        self._next += 1
        self.publicadas.append((vendedor, token_id, kwh))
        return oferta_id


class FakeCompra:
    """ms_compra falso: devuelve 1 confirmada y el resto revertidas (comportamiento del escrow)."""

    def __init__(self):
        self.disparos: list[tuple[int, int]] = []

    def comprar_concurrente(self, oferta_id, compradores):
        self.disparos.append((oferta_id, len(compradores)))
        res = []
        for i, c in enumerate(compradores):
            res.append({"ofertaId": oferta_id, "comprador": c, "exito": i == 0,
                        "estado": "confirmada" if i == 0 else "revertida"})
        return res


class FakeLector:
    """Lector_Eventos falso: devuelve los eventos preconfigurados para `leer_eventos`."""

    def __init__(self, eventos):
        self._eventos = eventos

    def leer_eventos(self, run_id, *, from_block=0, to_block="latest", incluir_gas=True):
        return list(self._eventos)


def _compra(run_id, oferta_id, kwh=e3.KWH_POR_OFERTA, gas=90000, bn=10):
    return EventoOnChain(run_id=run_id, tipo="Compra", contrato="MarketEscrow",
                         args={"ofertaId": oferta_id, "kwh": kwh, "comprador": "0xabc"},
                         transaction_hash=f"0x{oferta_id:064x}", block_number=bn, log_index=0, gas_used=gas)


def _emitido(run_id, token_id, kwh=e3.KWH_POR_OFERTA, gas=70000, bn=5):
    return EventoOnChain(run_id=run_id, tipo="Emitido", contrato="EnergyToken",
                         args={"id": token_id, "kwh": kwh, "a": "0xdef"},
                         transaction_hash=f"0x{token_id:064x}", block_number=bn, log_index=0, gas_used=gas)


def _escenario_ok(run_id, n=e3.REPETICIONES):
    """Eventos de una corrida ideal: 1 Compra por oferta y 1 Emitido por oferta con kWh iguales."""
    eventos = []
    for i in range(n):
        oferta_id = i + 1
        eventos.append(_emitido(run_id, e3._token_id(i)))
        eventos.append(_compra(run_id, oferta_id))
    return eventos


def test_e3_pass_cuando_una_venta_por_oferta_y_kwh_conservados():
    run_id = "run-pass"
    eventos = _escenario_ok(run_id)
    r = e3.ejecutar_e3(run_id, FakeLector(eventos), venta=FakeVenta(), compra=FakeCompra(), sembrar=False)
    assert r.verdict == PASS, [c.__dict__ for c in r.criteria]
    m = r.data["metricas"]
    assert m["doblesVentas"] == 0
    assert m["diffKwh"] == 0
    assert m["conservacionKwhPct"] == 100.0
    assert m["ofertasConUnaVenta"] == e3.REPETICIONES
    # gas registrado por operacion (R4.7)
    assert m["gasTotal"] > 0 and len(m["gasPorOperacion"]) == 2 * e3.REPETICIONES


def test_e3_fail_por_doble_venta():
    run_id = "run-doble"
    eventos = _escenario_ok(run_id)
    # Agrega una segunda Compra sobre la oferta 1 -> doble venta.
    eventos.append(_compra(run_id, 1))
    r = e3.ejecutar_e3(run_id, FakeLector(eventos), venta=FakeVenta(), compra=FakeCompra(), sembrar=False)
    assert r.verdict == FAIL
    assert r.data["metricas"]["doblesVentas"] == 1
    r45 = next(c for c in r.criteria if c.id == "R4.5")
    assert r45.status == FAIL


def test_e3_fail_por_kwh_no_conservados():
    run_id = "run-kwh"
    eventos = _escenario_ok(run_id)
    # Un Emitido extra sobre un token de E3 (el de la oferta 0) rompe la conservacion:
    # suma kWh tokenizados que no corresponden a ninguna venta validada.
    eventos.append(_emitido(run_id, e3._token_id(0), kwh=50))
    r = e3.ejecutar_e3(run_id, FakeLector(eventos), venta=FakeVenta(), compra=FakeCompra(), sembrar=False)
    assert r.verdict == FAIL
    assert r.data["metricas"]["diffKwh"] == 50
    r46 = next(c for c in r.criteria if c.id == "R4.6")
    assert r46.status == FAIL


def test_e3_fail_por_oferta_sin_venta():
    run_id = "run-sin-venta"
    # Solo 9 compras: la oferta 10 queda sin evento Compra.
    eventos = []
    for i in range(e3.REPETICIONES):
        eventos.append(_emitido(run_id, e3._token_id(i)))
    for i in range(e3.REPETICIONES - 1):
        eventos.append(_compra(run_id, i + 1))
    r = e3.ejecutar_e3(run_id, FakeLector(eventos), venta=FakeVenta(), compra=FakeCompra(), sembrar=False)
    assert r.verdict == FAIL
    r44 = next(c for c in r.criteria if c.id == "R4.4")
    assert r44.status == FAIL


def test_e3_dispara_10_ofertas_con_100_compras():
    run_id = "run-scope"
    venta, compra = FakeVenta(), FakeCompra()
    e3.ejecutar_e3(run_id, FakeLector(_escenario_ok(run_id)), venta=venta, compra=compra, sembrar=False)
    assert len(venta.publicadas) == e3.REPETICIONES
    assert all(n == e3.COMPRAS_POR_OFERTA for _, n in compra.disparos)
    assert len(compra.disparos) == e3.REPETICIONES


def test_generar_casos_es_reproducible_por_semilla():
    a = e3.generar_casos("run-rep")
    b = e3.generar_casos("run-rep")
    assert [c.token_id for c in a] == [c.token_id for c in b]
    assert a[0].compradores == b[0].compradores
    # distinto runId -> distinto dataset
    c = e3.generar_casos("otro-run")
    assert a[0].compradores != c[0].compradores


def test_e3_fail_si_falla_una_publicacion():
    run_id = "run-pub-fail"
    venta = FakeVenta(fallar_indices={3})  # la 4a oferta no publica
    eventos = _escenario_ok(run_id, n=e3.REPETICIONES - 1)
    r = e3.ejecutar_e3(run_id, FakeLector(eventos), venta=venta, compra=FakeCompra(), sembrar=False)
    r41 = next(c for c in r.criteria if c.id == "R4.1")
    assert r41.status == FAIL
    assert r.verdict == FAIL


class FakeSembrador:
    """Sembrador falso: registra las emisiones y puede simular un fallo de siembra."""

    def __init__(self, fallar_indices=()):
        self.emisiones: list[tuple[str, int, int]] = []
        self._fallar = set(fallar_indices)
        self._i = 0

    def emitir(self, vendedor, token_id, kwh, precio=None):
        idx = self._i
        self._i += 1
        if idx in self._fallar:
            return None
        self.emisiones.append((vendedor, token_id, kwh))
        return kwh


def test_e3_siembra_antes_de_publicar_cada_oferta():
    run_id = "run-seed"
    venta, sembrador = FakeVenta(), FakeSembrador()
    e3.ejecutar_e3(run_id, FakeLector(_escenario_ok(run_id)),
                   venta=venta, compra=FakeCompra(), sembrador=sembrador)
    # Se sembro (emitio) una vez por cada oferta antes de publicarla.
    assert len(sembrador.emisiones) == e3.REPETICIONES
    # Cada emision uso el mismo kWh que la oferta publicada.
    assert all(kwh == e3.KWH_POR_OFERTA for _, _, kwh in sembrador.emisiones)


def test_e3_falla_publicacion_si_falla_la_siembra():
    run_id = "run-seed-fail"
    venta = FakeVenta()
    sembrador = FakeSembrador(fallar_indices={2})  # la 3a oferta no se puede sembrar
    eventos = _escenario_ok(run_id, n=e3.REPETICIONES - 1)
    r = e3.ejecutar_e3(run_id, FakeLector(eventos),
                       venta=venta, compra=FakeCompra(), sembrador=sembrador)
    r41 = next(c for c in r.criteria if c.id == "R4.1")
    assert r41.status == FAIL
    # La oferta que no se sembro no se publica.
    assert len(venta.publicadas) == e3.REPETICIONES - 1
