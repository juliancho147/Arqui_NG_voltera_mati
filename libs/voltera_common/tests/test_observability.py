import json

from voltera_common import DomainEventPublisher, EmfAggregator, InMemoryBackend, emit_metric


def lines(capsys):
    return [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith("{")]


def test_emit_metric_emf(capsys):
    emit_metric("svc", "MeshPublishFailures")
    (d,) = lines(capsys)
    cw = d["_aws"]["CloudWatchMetrics"][0]
    assert cw["Namespace"] == "Voltera/Exp2" and cw["Dimensions"] == [["service"]]
    assert cw["Metrics"] == [{"Name": "MeshPublishFailures", "Unit": "Count"}] and d["MeshPublishFailures"] == 1 and d["service"] == "svc"


def test_aggregator_suma_y_dimensiones():
    out = []
    a = EmfAggregator("svc", writer=out.append)
    a.add("X"); a.add("X", 2); a.add("P", 1, dims={"pod": "p1"})
    assert a.flush() == 2
    docs = [json.loads(l) for l in out]
    plain = next(d for d in docs if "pod" not in d)
    pod = next(d for d in docs if "pod" in d)
    assert plain["X"] == 3 and pod["pod"] == "p1" and pod["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [["service", "pod"]]
    assert a.flush() == 0


def test_aggregator_periodico():
    import time
    out = []
    a = EmfAggregator("svc", interval=0.05, writer=out.append)
    a.start(); a.add("X"); time.sleep(0.3)
    assert out, "debe volcar durante la corrida, no solo al apagar"
    a.stop()


def test_publisher_loguea_y_cuenta_fallos(capsys):
    DomainEventPublisher("ms-x", InMemoryBackend()).publish("TarifaValidada", "C1", "F1")
    (ok,) = lines(capsys)
    assert ok["message"] == "evento publicado" and ok["cicloId"] == "C1" and ok["facturaId"] == "F1" and ok["tipo"] == "TarifaValidada"
    DomainEventPublisher("ms-x", InMemoryBackend(fail=True)).publish("TarifaValidada", "C1", "F1")
    docs = lines(capsys)
    assert any(d.get("MeshPublishFailures") == 1 for d in docs)
    assert any(d.get("message") == "fallo publicando evento al mesh" for d in docs)


class FakeCW:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def put_metric_data(self, Namespace, MetricData):
        if self.fail:
            raise RuntimeError("AccessDenied")
        self.calls.append((Namespace, MetricData))


def test_cloudwatch_sink_dimensiones_y_estadisticas():
    from voltera_common import CloudWatchSink
    cw = FakeCW()
    a = EmfAggregator("ms-process-billing", sink=CloudWatchSink("Voltera/Exp2", client=cw))
    a.add("MensajesDuplicados")
    a.add("MensajesProcesadosPorPod", 1, dims={"pod": "p1"})
    a.add("MensajeTotalMs", 100, "Milliseconds"); a.add("MensajeTotalMs", 300, "Milliseconds")
    a.flush()
    (ns, data), = cw.calls
    assert ns == "Voltera/Exp2"
    by = {d["MetricName"]: d for d in data}
    assert by["MensajesDuplicados"]["Value"] == 1 and by["MensajesDuplicados"]["Dimensions"] == [{"Name": "service", "Value": "ms-process-billing"}]
    assert {"Name": "pod", "Value": "p1"} in by["MensajesProcesadosPorPod"]["Dimensions"]
    st = by["MensajeTotalMs"]["StatisticValues"]
    assert (st["SampleCount"], st["Sum"], st["Minimum"], st["Maximum"]) == (2, 400, 100, 300)


def test_cloudwatch_sink_lotes_de_1000():
    from voltera_common import CloudWatchSink
    cw = FakeCW()
    a = EmfAggregator("s", sink=CloudWatchSink("N", client=cw))
    for i in range(2500):
        a.add(f"M{i}")
    a.flush()
    assert [len(c[1]) for c in cw.calls] == [1000, 1000, 500]


def test_cloudwatch_sink_no_lanza_si_falla(capsys):
    from voltera_common import CloudWatchSink
    sink = CloudWatchSink("N", client=FakeCW(fail=True))
    a = EmfAggregator("s", sink=sink)
    a.add("X")
    a.flush()  # no debe lanzar
    assert sink.failures == 1
    assert "fallo put_metric_data" in capsys.readouterr().out


def test_aggregator_from_env(monkeypatch):
    from voltera_common import CloudWatchSink, aggregator_from_env
    monkeypatch.delenv("METRICS_BACKEND", raising=False)
    assert aggregator_from_env("s").sink is None
    monkeypatch.setenv("METRICS_BACKEND", "cloudwatch")
    monkeypatch.setenv("CLOUDWATCH_NAMESPACE", "Otro/Ns")
    a = aggregator_from_env("s")
    assert isinstance(a.sink, CloudWatchSink) and a.sink.namespace == "Otro/Ns"
