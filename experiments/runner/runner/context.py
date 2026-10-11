"""Contexto de ejecucion: configuracion, clientes AWS perezosos, kubectl, bitacora y utilidades de espera."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable

from .config import REPORTS_DIR, Config
from .kube import Kube
from .safety import Journal, confirm, guard_name


class Context:
    def __init__(self, cfg: Config, *, yes: bool = False, dry_run: bool = False, kube: Kube | None = None, session: Any = None,
                 reports_dir: Path | None = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, input_fn: Callable[[str], str] = input,
                 isatty: bool | None = None, quick: bool = False, options: dict | None = None):
        self.cfg, self.yes, self.dry_run = cfg, yes, dry_run
        self.kube = kube or Kube(context=cfg.kube_context)
        self._session = session
        self.reports_dir = Path(reports_dir or REPORTS_DIR)
        self.journal = Journal(self.reports_dir / ".runner-changes.json")
        self.clock, self.sleep = clock, sleep
        self.input_fn, self.isatty = input_fn, isatty
        self.quick = quick  # tiempos de espera cortos (solo tests / ensayos)
        self.options = options or {}
        self._clients: dict[str, Any] = {}
        self._tables: dict[str, Any] = {}

    # ---- AWS
    @property
    def session(self):
        if self._session is None:
            import boto3
            self._session = boto3.Session(profile_name=self.cfg.profile, region_name=self.cfg.region)
        return self._session

    def client(self, service: str):
        if service not in self._clients:
            self._clients[service] = self.session.client(service, region_name=self.cfg.region)
        return self._clients[service]

    def table(self, key: str):
        name = self.cfg.table(key)
        if name not in self._tables:
            self._tables[name] = self.session.resource("dynamodb", region_name=self.cfg.region).Table(name)
        return self._tables[name]

    # ---- seguridad
    def guard(self, name: str, what: str = "recurso") -> str:
        return guard_name(name, self.cfg.prefix, what)

    def confirm(self, actions: list[str]) -> None:
        confirm(actions, yes=self.yes, input_fn=self.input_fn, isatty=self.isatty)

    # ---- utilidades
    def log(self, msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)

    def opt(self, name: str, default: Any = None) -> Any:
        v = self.options.get(name)
        return default if v is None else v

    def wait_until(self, predicate: Callable[[], Any], timeout: float, interval: float = 5.0, on_tick: Callable[[], None] | None = None):
        """Evalua `predicate` cada `interval` s hasta `timeout`. Devuelve (valor_truthy_o_ultimo, tiempo_transcurrido)."""
        t0 = self.clock()
        while True:
            if on_tick:
                on_tick()
            val = predicate()
            elapsed = self.clock() - t0
            if val or elapsed >= timeout:
                return val, elapsed
            self.sleep(interval)
