import pytest

import handler as h
from voltera_common import InjectedFault

TX = {"cicloId": "C1", "facturaId": "C1-F1", "tipoTarifa": "RESIDENCIAL"}


@pytest.fixture(autouse=True)
def fresh():
    h._publisher = None
    yield
    h._publisher = None


def test_validada_publica_evento(ctx):
    r = h.handler(TX, ctx)
    assert r["aprobado"] is True and r["valorKwh"] == 650.0
    ev = h.get_publisher().backend.events()
    assert [e.name for e in ev] == ["TarifaValidada"]
    assert ev[0].facturaid == "C1-F1"


def test_rechazo_de_negocio_no_lanza(ctx):
    r = h.handler({**TX, "tipoTarifa": "MARCIANA"}, ctx)
    assert r["aprobado"] is False and r["motivo"].startswith("TARIFA_NO_DEFINIDA")
    assert h.get_publisher().backend.names() == ["TarifaRechazada"]


def test_error_tecnico_force_fail(ctx, monkeypatch):
    monkeypatch.setenv("FORCE_FAIL", "true")
    with pytest.raises(InjectedFault):
        h.handler(TX, ctx)


def test_payload_sin_ids_es_error_tecnico(ctx):
    with pytest.raises(ValueError):
        h.handler({"tipoTarifa": "RESIDENCIAL"}, ctx)


def test_tarifas_override(ctx, monkeypatch):
    monkeypatch.setenv("TARIFAS_JSON", '{"residencial": 1}')
    assert h.handler(TX, ctx)["valorKwh"] == 1.0
