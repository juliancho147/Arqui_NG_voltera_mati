import json
import random

import pytest

from voltera_common import (
    EVENT_DATA_MODELS, EVENT_TYPES, DomainEventPublisher, InMemoryBackend, InjectedFault, KafkaBackend,
    PublishError, correlation_from, make_event, maybe_fail, parse_cloudevent,
)

ASYNCAPI_TYPES = {
    "CicloDeFacturacionIniciado": "ciclo-de-facturacion-iniciado",
    "ConsumoFacturablePreparado": "consumo-facturable-preparado",
    "TarifaValidada": "tarifa-validada",
    "TarifaRechazada": "tarifa-rechazada",
    "CargoEnergeticoCalculado": "cargo-energetico-calculado",
    "CalculoDeCargoRechazado": "calculo-de-cargo-rechazado",
    "FacturaEmitida": "factura-emitida",
    "EmisionDeFacturaRechazada": "emision-de-factura-rechazada",
    "NotificacionRegistrada": "notificacion-registrada",
    "FacturaNotificada": "factura-notificada",
    "NotificacionFallida": "notificacion-fallida",
    "ProcesoDeFacturacionCompletado": "proceso-de-facturacion-completado",
    "ProcesoDeFacturacionFallido": "proceso-de-facturacion-fallido",
}

SAMPLE = {
    "CicloDeFacturacionIniciado": {"totalUnidades": 3},
    "TarifaRechazada": {"motivo": "x"},
    "CargoEnergeticoCalculado": {"valorCargo": 10.5},
    "CalculoDeCargoRechazado": {"motivo": "x"},
    "FacturaEmitida": {"numeroFactura": "FV-000001"},
    "EmisionDeFacturaRechazada": {"motivo": "x"},
    "NotificacionFallida": {"motivo": "x"},
    "ProcesoDeFacturacionCompletado": {"emitidas": 1},
    "ProcesoDeFacturacionFallido": {"motivo": "x"},
}


def test_types_match_catalog():
    assert set(EVENT_TYPES) == set(ASYNCAPI_TYPES)
    for name, kebab in ASYNCAPI_TYPES.items():
        assert EVENT_TYPES[name] == f"com.voltera.facturacion.{kebab}.v1"


@pytest.mark.parametrize("name", sorted(EVENT_DATA_MODELS))
def test_roundtrip_every_event(name):
    ev = make_event(name, "ms-test", "C1", "F1", **SAMPLE.get(name, {}))
    assert ev.subject == "F1" and ev.cicloid == "C1" and ev.facturaid == "F1"
    assert ev.source == "/voltera/ms-test"
    back = parse_cloudevent(ev.to_bytes())
    assert back.name == name and back.id == ev.id
    assert back.data["cicloId"] == "C1" and back.data["facturaId"] == "F1"
    assert back.headers()["cicloId"] == "C1"


def test_invalid_event_rejected():
    with pytest.raises(ValueError):
        make_event("Inexistente", "s", "C", "F")
    with pytest.raises(ValueError):
        parse_cloudevent("no json")
    with pytest.raises(ValueError):
        parse_cloudevent({"specversion": "1.0"})
    with pytest.raises(Exception):
        make_event("TarifaRechazada", "s", "C", "F")  # falta motivo


def test_correlation():
    assert correlation_from({"cicloId": "C", "facturaId": "F"}).headers() == {"cicloId": "C", "facturaId": "F"}
    with pytest.raises(ValueError):
        correlation_from({"cicloId": "C"})


def test_publisher_in_memory():
    be = InMemoryBackend()
    pub = DomainEventPublisher("ms-tarifas", be)
    assert pub.publish("TarifaValidada", "C1", "F1", valorKwh=1.0)
    m = be.messages[0]
    assert m.topic == "voltera.eventos" and m.key == "F1"
    assert m.headers["cicloId"] == "C1" and m.headers["facturaId"] == "F1"
    assert json.loads(m.value)["type"].endswith("tarifa-validada.v1")


def test_publisher_best_effort_and_strict():
    be = InMemoryBackend(fail=True)
    assert DomainEventPublisher("s", be).publish("TarifaValidada", "C", "F") is False
    with pytest.raises(PublishError):
        DomainEventPublisher("s", be, best_effort=False).publish("TarifaValidada", "C", "F")


class FakeProducer:
    def __init__(self, err=None):
        self.err, self.sent = err, []
        self._cbs = []

    def produce(self, topic, key, value, headers, on_delivery):
        self.sent.append((topic, key, value, headers))
        self._cbs.append(on_delivery)

    def poll(self, t):
        return 0

    def flush(self, t):
        for cb in self._cbs:
            cb(self.err, None)
        return 0


def test_kafka_backend_with_fake_producer():
    p = FakeProducer()
    kb = KafkaBackend("x:9092", producer=p)
    kb.send("voltera.eventos", "F1", b"{}", {"cicloId": "C1", "facturaId": "F1"})
    kb.flush()
    assert p.sent[0][1] == b"F1" and ("cicloId", b"C1") in p.sent[0][3]
    bad = KafkaBackend("x", producer=FakeProducer(err="boom"))
    bad.send("t", "k", b"v", {})
    with pytest.raises(PublishError):
        bad.flush()


def test_faults(monkeypatch):
    monkeypatch.delenv("FORCE_FAIL", raising=False)
    monkeypatch.setenv("FAIL_RATE", "0")
    maybe_fail()
    monkeypatch.setenv("FORCE_FAIL", "true")
    with pytest.raises(InjectedFault):
        maybe_fail()
    monkeypatch.setenv("FORCE_FAIL", "false")
    monkeypatch.setenv("FAIL_RATE", "1")
    with pytest.raises(InjectedFault):
        maybe_fail(random.Random(1))
    monkeypatch.setenv("FAIL_RATE", "0.5")
    outcomes = set()
    rng = random.Random(0)
    for _ in range(40):
        try:
            maybe_fail(rng)
            outcomes.add("ok")
        except InjectedFault:
            outcomes.add("fail")
    assert outcomes == {"ok", "fail"}
