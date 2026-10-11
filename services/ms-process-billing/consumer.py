"""Bucle generico de consumo Kafka con commit manual DESPUES de procesar (at-least-once)."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from time import perf_counter
from typing import Callable

log = logging.getLogger("process-billing.consumer")


# Errores de commit que son NORMALES durante un rebalance (otro miembro entro o salio del grupo): el offset no se confirma y el
# mensaje se reentrega; la deduplicacion en DynamoDB lo descarta. NO deben matar el hilo consumidor (y con el, el pod).
_COMMIT_RECUPERABLE = ("ILLEGAL_GENERATION", "UNKNOWN_MEMBER_ID", "REBALANCE_IN_PROGRESS", "ASSIGNMENT_LOST", "_NO_OFFSET", "FENCED_INSTANCE_ID")


def commit_seguro(consumer, **kwargs) -> bool:
    """commit sincrono; True si confirmo, False si fallo por un rebalance (recuperable). Otros errores se propagan."""
    try:
        consumer.commit(asynchronous=False, **kwargs)
        return True
    except Exception as exc:  # noqa: BLE001 - KafkaException (confluent_kafka) no se importa aqui para no exigir la lib en tests
        err = exc.args[0] if getattr(exc, "args", None) else None
        name = err.name() if hasattr(err, "name") and callable(err.name) else ""
        texto = f"{name} {exc}"
        if any(c in texto for c in _COMMIT_RECUPERABLE):
            log.warning("commit omitido por rebalance (%s); el mensaje se reentrega y se deduplica", name or exc)
            return False
        raise


class PoisonMessage(Exception):
    """Mensaje no procesable (invalido): se registra y se omite (commit) para no bloquear la particion."""


def process_with_retry(handler: Callable[[bytes], object], value: bytes, stop: threading.Event, max_backoff: float = 30.0) -> bool:
    """True = procesado u omitido (hacer commit). False = apagado antes de lograrlo (NO commit)."""
    backoff = 0.5
    while not stop.is_set():
        try:
            handler(value)
            return True
        except PoisonMessage as exc:
            log.error("mensaje invalido omitido: %s", exc)
            return True
        except InterruptedError:
            return False
        except Exception as exc:
            log.error("fallo transitorio, reintento en %.1fs: %s", backoff, exc)
            if stop.wait(backoff):
                return False
            backoff = min(backoff * 2, max_backoff)
    return False


def run_consumer(consumer, handler, stop: threading.Event, poll_timeout: float = 1.0, on_idle: Callable[[], None] | None = None, process=process_with_retry,
                 on_done: Callable[[float, float, float], None] | None = None) -> None:
    """Un mensaje a la vez: poll -> handler -> commit sincrono. Sale al activarse `stop`."""
    try:
        while not stop.is_set():
            t0 = perf_counter()
            msg = consumer.poll(poll_timeout)
            poll_ms = (perf_counter() - t0) * 1000
            if msg is None:
                if on_idle:
                    try:
                        on_idle()
                    except Exception as exc:
                        log.error("on_idle fallo: %s", exc)
                continue
            if msg.error():
                code = msg.error().code() if hasattr(msg.error(), "code") else None
                log.warning("error de consumidor: %s (code=%s)", msg.error(), code)
                if hasattr(msg.error(), "fatal") and msg.error().fatal():
                    raise RuntimeError(str(msg.error()))
                continue
            t1 = perf_counter()
            done = process(handler, msg.value(), stop)
            handle_ms = (perf_counter() - t1) * 1000
            if done:
                t2 = perf_counter()
                commit_seguro(consumer, message=msg)
                commit_ms = (perf_counter() - t2) * 1000
                if on_done:
                    try:
                        on_done(poll_ms, handle_ms, commit_ms)
                    except Exception as exc:
                        log.error("on_done fallo: %s", exc)
            else:
                break  # apagando: el mensaje queda sin commit y se reentrega
    finally:
        try:
            consumer.close()
        except Exception:
            pass


def _topic_partition(topic: str, partition: int, offset: int):
    try:
        from confluent_kafka import TopicPartition
        return TopicPartition(topic, partition, offset)
    except ImportError:  # entorno de pruebas sin confluent_kafka
        from types import SimpleNamespace
        return SimpleNamespace(topic=topic, partition=partition, offset=offset)


class ConcurrentCommitter:
    """Procesa hasta N mensajes en paralelo y confirma solo el offset contiguo mas alto completado por particion.

    Dentro de una particion los offsets se completan en cualquier orden, pero el commit nunca salta un hueco:
    si el offset 5 sigue en curso y el 6 termino, se confirma hasta el 4. Tras una caida se reentregan 5 y 6
    (at-least-once; el dedup/idempotencia de los handlers absorbe el reproceso).
    """

    def __init__(self, consumer, handler, stop: threading.Event, concurrency: int, process=process_with_retry, on_done=None):
        self.consumer, self.handler, self.stop, self.process, self.on_done = consumer, handler, stop, process, on_done
        self.concurrency = concurrency
        self.pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="worker")
        self.lock = threading.Lock()
        self.order: dict[tuple, deque] = defaultdict(deque)  # (topic, part) -> offsets en vuelo/terminados, en orden de llegada
        self.done: dict[tuple, set] = defaultdict(set)       # offsets completados con exito
        self.futures: set = set()
        self.committed: dict[tuple, int] = {}

    @property
    def in_flight(self) -> int:
        return len(self.futures)

    def submit(self, msg, poll_ms: float = 0.0) -> None:
        tp = (msg.topic(), msg.partition())
        with self.lock:
            self.order[tp].append(msg.offset())
        self.futures.add(self.pool.submit(self._work, tp, msg.offset(), msg.value(), poll_ms))

    def _work(self, tp, offset: int, value: bytes, poll_ms: float) -> None:
        t1 = perf_counter()
        ok = self.process(self.handler, value, self.stop)
        handle_ms = (perf_counter() - t1) * 1000
        if not ok:
            return  # apagado: sin commit, se reentrega
        with self.lock:
            self.done[tp].add(offset)
        if self.on_done:
            try:
                self.on_done(poll_ms, handle_ms, 0.0)  # el commit es por lotes contiguos desde el hilo de poll (commitMs=0)
            except Exception as exc:
                log.error("on_done fallo: %s", exc)

    def reap(self, timeout: float = 0.0) -> None:
        """Recoge futuros terminados (esperando hasta `timeout` por el primero) y confirma lo contiguo."""
        if self.futures:
            finished, _ = wait(self.futures, timeout=timeout, return_when=FIRST_COMPLETED)
            for f in finished:
                self.futures.discard(f)
                if f.exception():
                    log.error("worker fallo: %s", f.exception())
        self.commit_contiguous()

    def commit_contiguous(self, only: set | None = None) -> None:
        to_commit = []
        with self.lock:
            for tp, q in self.order.items():
                if only is not None and tp not in only:
                    continue
                last = None
                while q and q[0] in self.done[tp]:
                    last = q.popleft()
                    self.done[tp].discard(last)
                if last is not None:
                    to_commit.append(_topic_partition(tp[0], tp[1], last + 1))
                    self.committed[tp] = last
        if to_commit:
            commit_seguro(self.consumer, offsets=to_commit)

    def drain(self) -> None:
        """Espera a que termine todo lo en vuelo y confirma lo contiguo (apagado limpio / rebalance)."""
        while self.futures:
            self.reap(timeout=1.0)
        self.commit_contiguous()

    def on_revoke(self, parts) -> None:
        """Rebalance: termina lo en curso y confirma antes de ceder las particiones; descarta el estado de las cedidas."""
        self.drain()
        with self.lock:
            for p in parts:
                self.order.pop((p.topic, p.partition), None)
                self.done.pop((p.topic, p.partition), None)

    def close(self) -> None:
        self.drain()
        self.pool.shutdown(wait=True)


def run_consumer_concurrent(consumer, handler, stop: threading.Event, concurrency: int, poll_timeout: float = 1.0, on_idle=None,
                            process=process_with_retry, on_done=None, committer: ConcurrentCommitter | None = None) -> None:
    """Hasta `concurrency` mensajes en paralelo por pod. El hilo de poll es el unico que llama a poll/commit."""
    cc = committer or ConcurrentCommitter(consumer, handler, stop, concurrency, process, on_done)
    try:
        while not stop.is_set():
            if cc.in_flight >= concurrency:
                cc.reap(timeout=poll_timeout)  # contrapresion: no se lee mas hasta liberar un hueco
                continue
            t0 = perf_counter()
            msg = consumer.poll(0 if cc.in_flight else poll_timeout)
            poll_ms = (perf_counter() - t0) * 1000
            if msg is None:
                cc.reap(timeout=poll_timeout if cc.in_flight else 0.0)
                if on_idle and not cc.in_flight:
                    try:
                        on_idle()
                    except Exception as exc:
                        log.error("on_idle fallo: %s", exc)
                continue
            if msg.error():
                code = msg.error().code() if hasattr(msg.error(), "code") else None
                log.warning("error de consumidor: %s (code=%s)", msg.error(), code)
                if hasattr(msg.error(), "fatal") and msg.error().fatal():
                    raise RuntimeError(str(msg.error()))
                continue
            cc.submit(msg, poll_ms)
            cc.reap(0.0)
    finally:
        try:
            cc.close()
        finally:
            try:
                consumer.close()
            except Exception:
                pass
