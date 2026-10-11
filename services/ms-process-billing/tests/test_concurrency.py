import threading
import time

from consumer import ConcurrentCommitter, run_consumer_concurrent


class Msg:
    def __init__(self, off, part=0, v=None):
        self._o, self._p, self._v = off, part, v or f"m{part}-{off}".encode()

    def topic(self): return "t"
    def partition(self): return self._p
    def offset(self): return self._o
    def value(self): return self._v
    def error(self): return None


class Part:
    def __init__(self, p): self.topic, self.partition = "t", p


class FakeConsumer:
    def __init__(self, msgs, stop=None):
        self.msgs, self.commits, self.closed, self.stop = list(msgs), [], False, stop
        self.lock = threading.Lock()

    def poll(self, t):
        if not self.msgs:
            time.sleep(0.01)
            return None
        return self.msgs.pop(0)

    def commit(self, offsets=None, asynchronous=True, message=None):
        assert asynchronous is False
        with self.lock:
            self.commits.append({(o.partition): o.offset for o in offsets})

    def close(self): self.closed = True


def last_commit(c):
    out = {}
    for d in c.commits:
        out.update(d)
    return out


def run(c, handler, stop, n, **kw):
    t = threading.Thread(target=run_consumer_concurrent, args=(c, handler, stop, n, 0.05), kwargs=kw)
    t.start()
    return t


def test_procesa_en_paralelo_y_confirma_todo():
    stop = threading.Event()
    c = FakeConsumer([Msg(i) for i in range(8)])
    active, peak, lock = [0], [0], threading.Lock()

    def handler(v):
        with lock:
            active[0] += 1; peak[0] = max(peak[0], active[0])
        time.sleep(0.1)
        with lock:
            active[0] -= 1

    t0 = time.time()
    t = run(c, handler, stop, 4)
    while last_commit(c).get(0) != 8 and time.time() - t0 < 5:
        time.sleep(0.02)
    stop.set(); t.join()
    assert last_commit(c) == {0: 8} and c.closed
    assert 2 <= peak[0] <= 4


def test_commit_solo_contiguo():
    stop = threading.Event()
    gate = threading.Event()
    c = FakeConsumer([Msg(0), Msg(1), Msg(2)])
    finished = []

    def handler(v):
        if v == b"m0-0":
            gate.wait(5)
        finished.append(v)

    t = run(c, handler, stop, 3)
    t0 = time.time()
    while len(finished) < 2 and time.time() - t0 < 5:
        time.sleep(0.02)
    time.sleep(0.2)
    assert last_commit(c) == {}          # offset 0 sigue en curso: no se confirma 1 ni 2
    gate.set()
    while last_commit(c).get(0) != 3 and time.time() - t0 < 5:
        time.sleep(0.02)
    stop.set(); t.join()
    assert last_commit(c) == {0: 3}


def test_particiones_independientes():
    stop = threading.Event()
    gate = threading.Event()
    c = FakeConsumer([Msg(0, 0), Msg(0, 1), Msg(1, 1)])

    def handler(v):
        if v == b"m0-0":
            gate.wait(5)

    t = run(c, handler, stop, 3)
    t0 = time.time()
    while last_commit(c).get(1) != 2 and time.time() - t0 < 5:
        time.sleep(0.02)
    assert last_commit(c) == {1: 2}
    gate.set(); stop.set(); t.join()
    assert last_commit(c)[0] == 1


def test_apagado_limpio_no_confirma_lo_interrumpido():
    stop = threading.Event()
    c = FakeConsumer([Msg(0), Msg(1)])
    started = threading.Event()

    def handler(v):
        if v == b"m0-0":
            started.set()
            raise InterruptedError("apagado")

    t = run(c, handler, stop, 2)
    started.wait(5)
    time.sleep(0.2)
    stop.set(); t.join(5)
    assert not t.is_alive() and c.closed
    assert 0 not in last_commit(c) or last_commit(c)[0] == 0  # nada del offset 0 en adelante


def test_revoke_drena_y_confirma():
    stop = threading.Event()
    c = FakeConsumer([])
    cc = ConcurrentCommitter(c, lambda v: time.sleep(0.05), stop, 2)
    cc.submit(Msg(0)); cc.submit(Msg(1))
    cc.on_revoke([Part(0)])
    assert last_commit(c) == {0: 2} and cc.in_flight == 0
    cc.close()
