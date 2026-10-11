"""Bucle generico de consumo Kafka con commit manual DESPUES de procesar (at-least-once)."""
from __future__ import annotations

import logging
import threading
from time import perf_counter
from typing import Callable

log = logging.getLogger("process-billing.consumer")


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
                consumer.commit(message=msg, asynchronous=False)
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
