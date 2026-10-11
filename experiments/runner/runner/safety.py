"""Seguridad operativa: confirmacion interactiva, guardas de prefijo y bitacora de cambios revertibles."""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Callable


class SafetyError(RuntimeError):
    pass


class Aborted(RuntimeError):
    pass


def guard_name(name: str, prefix: str, what: str = "recurso") -> str:
    """Solo se actua sobre recursos AWS cuyo nombre empiece con el prefijo del proyecto (p. ej. voltera-exp2-)."""
    if not name or not name.startswith(prefix):
        raise SafetyError(f"{what} '{name}' no empieza con el prefijo '{prefix}': se rechaza la accion")
    return name


def arn_resource(arn: str) -> str:
    return arn.rsplit(":", 1)[-1]


def confirm(actions: list[str], *, yes: bool, input_fn: Callable[[str], str] = input, isatty: bool | None = None) -> None:
    """Pide confirmacion antes de modificar estado. Sin --yes y sin terminal interactiva, aborta."""
    if yes:
        return
    tty = sys.stdin.isatty() if isatty is None else isatty
    print("\nEl experimento va a MODIFICAR estado:", file=sys.stderr)
    for a in actions:
        print(f"  - {a}", file=sys.stderr)
    if not tty:
        raise Aborted("se requiere confirmacion interactiva (use --yes para omitirla)")
    if input_fn("Continuar? [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
        raise Aborted("el operador no confirmo")


class Journal:
    """Registro persistente (JSON) de cada cambio con la informacion para revertirlo (`python -m runner restore`).

    Entrada: {id, ts, kind, target, before, revertible, restored}
      kind = lambda_env | lambda_concurrency | pod_delete (no revertible: lo repone el Deployment)
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8") or "[]")

    def _save(self, entries: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def record(self, kind: str, target: str, before: dict, revertible: bool = True) -> str:
        entries = self._load()
        eid = uuid.uuid4().hex[:12]
        entries.append({"id": eid, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind, "target": target,
                        "before": before, "revertible": revertible, "restored": not revertible})
        self._save(entries)
        return eid

    def mark_restored(self, eid: str) -> None:
        entries = self._load()
        for e in entries:
            if e["id"] == eid:
                e["restored"] = True
        self._save(entries)

    def pending(self) -> list[dict]:
        return [e for e in self._load() if e["revertible"] and not e["restored"]]

    def all(self) -> list[dict]:
        return self._load()
