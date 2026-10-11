import threading

import pytest

from conftest import consumo, sqs_bodies
from consumer import PoisonMessage
from ingest import IngestProcessor


def test_publica_transaccion_armada_en_sqs(aws, settings):
    table, sqs, url = aws
    p = IngestProcessor(settings, table, sqs)
    assert p.handle(consumo("C1-F1")) == "NUEVO"
    (body,) = sqs_bodies(sqs, url)
    assert body["cicloId"] == "C1" and body["facturaId"] == "C1-F1" and body["tipoTarifa"] == "RESIDENCIAL"
    assert table.get_item(Key={"cicloId": "C1", "sk": "DEDUP#C1-F1"})["Item"]["estado"] == "ENVIADO"


def test_duplicado_no_reenvia(aws, settings):
    table, sqs, url = aws
    p = IngestProcessor(settings, table, sqs)
    p.handle(consumo("C1-F1"))
    assert p.handle(consumo("C1-F1")) == "DUPLICADO"
    assert len(sqs_bodies(sqs, url)) == 1 and p.counters["duplicados"] == 1


def test_crash_entre_dedup_y_sqs_reenvia(aws, settings):
    """Pod muerto tras el claim (estado PROCESANDO): la reentrega NO debe perder la solicitud (Exp. 3)."""
    table, sqs, url = aws
    table.put_item(Item={"cicloId": "C1", "sk": "DEDUP#C1-F1", "estado": "PROCESANDO"})
    p = IngestProcessor(settings, table, sqs)
    assert p.handle(consumo("C1-F1")) == "REENVIAR"
    assert len(sqs_bodies(sqs, url)) == 1


def test_retardo_por_mensaje_y_apagado(aws, settings):
    table, sqs, url = aws
    stop = threading.Event()
    stop.set()
    p = IngestProcessor(settings, table, sqs, stop=stop)
    with pytest.raises(InterruptedError):
        p.handle(consumo("C1-F1", retardoSegundos=5.0))
    assert sqs_bodies(sqs, url) == []  # nada publicado; sin commit => se reentrega


def test_retardo_env_corto(aws, settings):
    table, sqs, url = aws
    settings.simulated_delay_seconds = 0.05
    IngestProcessor(settings, table, sqs).handle(consumo("C1-F2"))
    assert len(sqs_bodies(sqs, url)) == 1


def test_mensaje_invalido_es_poison(aws, settings):
    table, sqs, _ = aws
    with pytest.raises(PoisonMessage):
        IngestProcessor(settings, table, sqs).handle(b"no-json")


class Rec:
    def __init__(self):
        self.calls = []

    def add(self, name, value=1, unit="Count", dims=None):
        self.calls.append((name, value, dims))


def test_metricas_reenviados_y_por_pod(aws, settings, monkeypatch):
    table, sqs, _ = aws
    monkeypatch.setenv("HOSTNAME", "pod-a")
    table.put_item(Item={"cicloId": "C1", "sk": "DEDUP#C1-F1", "estado": "PROCESANDO"})
    m = Rec()
    p = IngestProcessor(settings, table, sqs, metrics=m)
    p.handle(consumo("C1-F1"))
    p.handle(consumo("C1-F2"))
    p.handle(consumo("C1-F2"))
    names = [c[0] for c in m.calls]
    assert names.count("MensajesReenviados") == 1 and names.count("MensajesDuplicados") == 1
    assert ("MensajesProcesadosPorPod", 1, {"pod": "pod-a"}) in m.calls
