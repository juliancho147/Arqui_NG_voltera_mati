import threading

import pytest

from consumer import commit_seguro, run_consumer


class KErr:
    def __init__(self, n): self.n = n
    def name(self): return self.n
    def __str__(self): return f"KafkaError{{{self.n}}}"


class FakeKafkaException(Exception):
    pass


class Msg:
    def __init__(self, v=b"x"): self._v = v
    def error(self): return None
    def value(self): return self._v


class Cons:
    """Entrega 2 mensajes; el primer commit falla con ILLEGAL_GENERATION (rebalance)."""
    def __init__(self, err):
        self.msgs, self.err, self.commits, self.closed = [Msg(), Msg()], err, 0, False
    def poll(self, t):
        return self.msgs.pop(0) if self.msgs else None
    def commit(self, **kw):
        self.commits += 1
        if self.commits == 1 and self.err:
            raise FakeKafkaException(KErr(self.err))
    def close(self): self.closed = True


def test_commit_seguro_traga_illegal_generation():
    assert commit_seguro(Cons("ILLEGAL_GENERATION"), message=Msg()) is False


def test_commit_seguro_propaga_errores_no_recuperables():
    with pytest.raises(FakeKafkaException):
        commit_seguro(Cons("TOPIC_AUTHORIZATION_FAILED"), message=Msg())


def test_el_hilo_consumidor_sobrevive_a_un_commit_fallido_por_rebalance():
    stop, vistos = threading.Event(), []
    c = Cons("ILLEGAL_GENERATION")

    def handler(v):
        vistos.append(v)
        if len(vistos) == 2:
            stop.set()

    run_consumer(c, handler, stop, poll_timeout=0)
    assert len(vistos) == 2 and c.commits == 2  # el segundo mensaje se proceso y confirmo: el hilo no murio
