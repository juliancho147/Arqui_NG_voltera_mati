"""Contexto de ejecucion: configuracion, clientes AWS perezosos, kubectl, bitacora y utilidades de espera."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable

from .config import REPORTS_DIR, Config
from .kube import Kube
from .safety import Journal, confirm, guard_name


NOISY_MUTATIONS = {"BatchWriteItem", "PutItem", "SendMessage", "DeleteMessage"}
_SERVICE_CLI = {"events": "events", "lambda": "lambda", "dynamodb": "dynamodb", "sqs": "sqs", "states": "stepfunctions",
                "cloudwatch": "cloudwatch"}
_READ_PREFIXES = ("Get", "Describe", "List", "Query", "Scan", "BatchGet", "Receive", "Head")


def _kebab(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i and not name[i - 1].isupper():
            out.append("-")
        out.append(ch.lower())
    return "".join(out)


def _short(v: Any, limit: int = 70) -> str:
    s = v if isinstance(v, str) else str(v)
    if isinstance(v, str) and v.startswith("http") and "/" in v:
        s = v.rsplit("/", 1)[-1]
    if isinstance(v, (list, dict)):
        s = f"<{type(v).__name__} de {len(v)}>" if len(str(v)) > limit else str(v)
    return s if len(s) <= limit else s[: limit - 3] + "..."


def service_op_key(model) -> str:
    return f"{model.service_model.service_name}:{model.name}:*"


def render_aws_command(service: str, operation: str, params: dict) -> tuple[str, bool, str]:
    """(linea tipo `aws sqs get-queue-attributes --queue-url X`, es_mutacion, clave_de_dedup)."""
    cli = _SERVICE_CLI.get(service, service)
    args = " ".join(f"--{_kebab(k)} {_short(v)}" for k, v in params.items())
    line = f"aws {cli} {_kebab(operation)} {args}".rstrip()
    return line, not operation.startswith(_READ_PREFIXES), f"{service}:{operation}:{args}"


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
        self._ddb_resource: Any = None
        self.echo: Callable[[str], None] | None = None      # modo demo: imprime cada comando AWS/kubectl
        self.phase_hook: Callable[[str, str], None] | None = None  # modo demo: banner + pausa + marca por fase
        self._echoed: set[str] = set()

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
            self._attach_echo(self._clients[service])
        return self._clients[service]

    def table(self, key: str):
        name = self.cfg.table(key)
        if name not in self._tables:
            if self._ddb_resource is None:
                self._ddb_resource = self.session.resource("dynamodb", region_name=self.cfg.region)
                self._attach_echo(self._ddb_resource.meta.client)
            self._tables[name] = self._ddb_resource.Table(name)
        return self._tables[name]

    # ---- modo demo: eco de comandos y fases
    def set_echo(self, fn: Callable[[str], None] | None) -> None:
        self.echo = fn
        self.kube.echo = fn
        for c in self._clients.values():
            self._attach_echo(c)
        if self._ddb_resource is not None:
            self._attach_echo(self._ddb_resource.meta.client)

    def _attach_echo(self, client) -> None:
        if self.echo is None or getattr(client, "_voltera_echo", False):
            return
        client._voltera_echo = True
        client.meta.events.register("provide-client-params.*.*", self._on_params)

    def _on_params(self, params, model, **_kw) -> None:
        if self.echo is None:
            return
        line, mutating, key = render_aws_command(model.service_model.service_name, model.name, params or {})
        if mutating and model.name not in NOISY_MUTATIONS:
            self.echo(line)
        elif key not in self._echoed:
            noisy = f"{service_op_key(model)}"
            if mutating and noisy in self._echoed:
                return
            self._echoed.add(key)
            if mutating:
                self._echoed.add(noisy)
                self.echo(line + "   (se repite por lotes/mensajes; se muestra una vez)")
            else:
                self.echo(line + "   (lectura; se repite cada ciclo de muestreo)")

    def phase(self, name: str, description: str = "") -> None:
        if self.phase_hook:
            self.phase_hook(name, description)

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
