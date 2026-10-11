import json
import threading
import urllib.request

from consumer import PoisonMessage, run_consumer
from health import make_server, serve_in_thread


class Msg:
    def __init__(self, v):
        self._v = v

    def value(self):
        return self._v

    def error(self):
        return None


class FakeConsumer:
    def __init__(self, msgs, stop=None, stop_after=None):
        self.msgs, self.commits, self.closed = list(msgs), [], False
        self.stop, self.stop_after = stop, stop_after

    def poll(self, t):
        if not self.msgs:
            if self.stop:
                self.stop.set()
            return None
        return self.msgs.pop(0)

    def commit(self, message=None, asynchronous=True):
        assert asynchronous is False
        self.commits.append(message.value())

    def close(self):
        self.closed = True


def test_commit_solo_despues_de_procesar():
    stop = threading.Event()
    order = []
    c = FakeConsumer([Msg(b"a"), Msg(b"b")], stop)

    def handler(v):
        order.append(("proc", v, list(c.commits)))

    run_consumer(c, handler, stop, poll_timeout=0)
    assert c.commits == [b"a", b"b"] and c.closed
    assert order[0] == ("proc", b"a", []) and order[1] == ("proc", b"b", [b"a"])


def test_reintenta_hasta_exito_y_omite_poison():
    stop = threading.Event()
    c = FakeConsumer([Msg(b"a"), Msg(b"bad")], stop)
    calls = {"n": 0}

    def handler(v):
        if v == b"bad":
            raise PoisonMessage("x")
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("sqs caido")

    import consumer as cm
    orig = cm.process_with_retry
    run_consumer(c, handler, stop, poll_timeout=0, process=lambda h, v, s: orig(h, v, s, max_backoff=0.01))
    assert calls["n"] == 2 and c.commits == [b"a", b"bad"]


def test_sigterm_sin_commit_del_mensaje_en_curso():
    stop = threading.Event()
    c = FakeConsumer([Msg(b"a")])

    def handler(v):
        stop.set()
        raise InterruptedError()

    run_consumer(c, handler, stop, poll_timeout=0)
    assert c.commits == [] and c.closed


def test_health_endpoint():
    srv = make_server(0, lambda: {"ok": True, "x": 1})
    serve_in_thread(srv)
    port = srv.server_address[1]
    r = urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz")
    assert r.status == 200 and json.loads(r.read())["ok"] is True
    srv.shutdown()
    bad = make_server(0, lambda: {"ok": False})
    serve_in_thread(bad)
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{bad.server_address[1]}/healthz")
        assert False
    except urllib.error.HTTPError as e:
        assert e.code == 503
    bad.shutdown()
