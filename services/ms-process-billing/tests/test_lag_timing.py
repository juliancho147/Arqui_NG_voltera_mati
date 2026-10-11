import threading

from conftest import consumo
from consumer import run_consumer
from ingest import IngestProcessor, report_timing
from lag import compute_lag, lag_reporter


class TP:
    def __init__(self, topic, partition, offset=-1001):
        self.topic, self.partition, self.offset = topic, partition, offset


class LagConsumer:
    def __init__(self, parts, committed, marks, positions=None):
        self.parts, self._committed, self.marks, self.positions = parts, committed, marks, positions or {}

    def assignment(self):
        return [TP("t", p) for p in self.parts]

    def committed(self, tps, timeout=None):
        return [TP("t", p, self._committed.get(p, -1001)) for p in self.parts]

    def get_watermark_offsets(self, tp, timeout=None):
        return self.marks[tp.partition]

    def position(self, tps):
        return [TP("t", tps[0].partition, self.positions.get(tps[0].partition, -1001))]


def test_lag_solo_particiones_asignadas():
    c = LagConsumer([0, 2], {0: 10, 2: 4}, {0: (0, 15), 2: (0, 4), 1: (0, 99)})
    assert compute_lag(c) == (5, 2)


def test_lag_sin_commit_usa_posicion_y_luego_low():
    c = LagConsumer([0, 1], {}, {0: (0, 10), 1: (3, 9)}, positions={0: 7})
    assert compute_lag(c) == (3 + 6, 2)


def test_lag_sin_particiones_es_cero():
    assert compute_lag(LagConsumer([], {}, {})) == (0, 0)


class Rec:
    def __init__(self):
        self.calls = []

    def add(self, name, value=1, unit="Count", dims=None):
        self.calls.append((name, value, unit, dims))


def test_lag_reporter_emite_metricas_y_cero():
    m = Rec()
    lag_reporter(LagConsumer([0], {0: 5}, {0: (0, 5)}), m, "ms-process-billing", "t", "pod-a")()
    assert ("KafkaConsumerLag", 0, "Count", {"topic": "t"}) in m.calls
    assert ("ParticionesAsignadas", 1, "Count", {"pod": "pod-a"}) in m.calls


def test_lag_reporter_no_lanza_si_falla():
    class Boom:
        def assignment(self):
            raise RuntimeError("x")
    m = Rec()
    lag_reporter(Boom(), m, "s", "t", "p")()
    assert m.calls == []


def test_timings_por_etapa_y_sobrecosto(aws, settings):
    table, sqs, _ = aws
    settings.simulated_delay_seconds = 0.1
    p = IngestProcessor(settings, table, sqs)
    p.handle(consumo("C1-F1"))
    t = p.last_timings
    assert t["delayMs"] >= 95 and t["claimMs"] > 0 and t["sqsMs"] > 0 and t["updateMs"] > 0
    m = Rec()
    rec = report_timing(p, m, None, poll_ms=1.0, handle_ms=t["delayMs"] + 20, commit_ms=5.0)
    assert abs(rec["sobrecostoMs"] - 25.0) < 0.2
    names = {c[0]: c for c in m.calls}
    assert names["MensajeTotalMs"][2] == "Milliseconds" and names["MensajeSobrecostoMs"][1] < names["MensajeTotalMs"][1]


def test_on_done_se_invoca_tras_commit():
    class Msg:
        def value(self): return b"x"
        def error(self): return None

    class C:
        def __init__(self, stop): self.stop, self.n, self.commits = stop, 0, 0
        def poll(self, t):
            self.n += 1
            if self.n > 1:
                self.stop.set(); return None
            return Msg()
        def commit(self, message=None, asynchronous=True): self.commits += 1
        def close(self): pass

    stop = threading.Event()
    got = []
    c = C(stop)
    run_consumer(c, lambda v: None, stop, 0, on_done=lambda a, b, d: got.append((a, b, d)))
    assert c.commits == 1 and len(got) == 1 and all(x >= 0 for x in got[0])
