from botocore.exceptions import ClientError  # noqa: F401

import pytest

from state import CycleState
from voltera_common import make_event


def ev(name, fid, ciclo="C1", **data):
    return make_event(name, "x", ciclo, fid, **data).to_bytes()


def inicio(total, ciclo="C1"):
    return ev("CicloDeFacturacionIniciado", "CICLO", ciclo, totalUnidades=total)


@pytest.fixture
def st(aws, settings, publisher):
    return CycleState(settings, aws[0], publisher, clock=lambda: 1000.0)


def meta(aws):
    return aws[0].get_item(Key={"cicloId": "C1", "sk": "META"})["Item"]


def test_completado_cuando_todas_terminan(aws, st, backend):
    st.handle(inicio(2))
    st.handle(ev("FacturaNotificada", "F1"))
    assert backend.names() == []
    st.handle(ev("TarifaRechazada", "F2", motivo="x"))
    (done,) = backend.events()
    assert done.name == "ProcesoDeFacturacionCompletado" and done.facturaid == "CICLO"
    assert done.data["emitidas"] == 1 and done.data["rechazadas"] == 1
    assert meta(aws)["estado"] == "COMPLETADO"


def test_eventos_antes_del_inicio_y_repetidos(aws, st, backend):
    st.handle(ev("FacturaNotificada", "F1"))
    st.handle(ev("FacturaNotificada", "F1"))  # duplicado: no cuenta dos veces
    st.handle(ev("FacturaNotificada", "F2"))
    assert backend.events() == []  # aun no se conoce el total
    st.handle(inicio(2))
    assert backend.names() == ["ProcesoDeFacturacionCompletado"]
    assert int(meta(aws)["emitidas"]) == 2


def test_no_reemite_completado(aws, st, backend):
    st.handle(inicio(1))
    st.handle(ev("FacturaNotificada", "F1"))
    st.handle(ev("FacturaNotificada", "F1"))
    st.handle(inicio(1))
    assert backend.names() == ["ProcesoDeFacturacionCompletado"]


def test_fallo_definitivo_y_recuperacion_por_redrive(aws, st, backend):
    st.handle(inicio(2))
    st.handle(ev("FacturaNotificada", "F1"))
    st.handle(ev("NotificacionFallida", "F2", motivo="x", intento=1, definitivo=False))  # intermedio: ignorado
    assert backend.events() == []
    st.handle(ev("NotificacionFallida", "F2", motivo="x", intento=3, definitivo=True))
    assert backend.names() == ["ProcesoDeFacturacionFallido"]
    assert meta(aws)["estado"] == "FALLIDO"
    st.handle(ev("FacturaNotificada", "F2"))  # el redrive de la DLQ funciona
    assert backend.names()[-1] == "ProcesoDeFacturacionCompletado"
    m = meta(aws)
    assert (int(m["emitidas"]), int(m["fallidas"]), m["estado"]) == (2, 0, "COMPLETADO")


def test_timeout_emite_fallido_una_vez(aws, settings, publisher, backend):
    t = {"now": 1000.0}
    st = CycleState(settings, aws[0], publisher, clock=lambda: t["now"])
    st.handle(inicio(2))
    assert st.sweep_timeouts() == []
    t["now"] += 61
    assert st.sweep_timeouts() == ["C1"]
    assert st.sweep_timeouts() == []
    (e,) = backend.events()
    assert e.name == "ProcesoDeFacturacionFallido" and e.data["motivo"] == "TIMEOUT_CICLO"


def test_ignora_eventos_irrelevantes(st, backend):
    st.handle(ev("TarifaValidada", "F1"))
    assert backend.events() == []


def test_metricas_de_ciclo(aws, settings, publisher):
    from test_ingest import Rec
    t = {"now": 1000.0}
    m = Rec()
    st = CycleState(settings, aws[0], publisher, clock=lambda: t["now"], metrics=m)
    st.handle(inicio(1))
    t["now"] += 42
    st.handle(ev("FacturaNotificada", "F1"))
    assert ("CiclosCompletados", 1, None) in [(c[0], c[1], c[2]) for c in m.calls]
    dur = [c for c in m.calls if c[0] == "CicloDuracionSegundos"]
    assert dur and dur[0][1] == 42.0
    st2 = CycleState(settings, aws[0], publisher, clock=lambda: t["now"], metrics=m)
    st2.handle(inicio(2, "C2"))
    t["now"] += 61
    st2.sweep_timeouts()
    assert "CiclosFallidos" in [c[0] for c in m.calls]
