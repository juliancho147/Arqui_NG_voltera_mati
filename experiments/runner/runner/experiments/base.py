"""Base comun de los experimentos: plan (dry-run), ejecucion protegida y utilidades."""
from __future__ import annotations

import traceback
from typing import Callable

from ..context import Context
from ..report import ExperimentResult, now_iso


class Experiment:
    name = "expN"
    title = ""
    hypothesis = ""
    mutates = False  # True => pide confirmacion

    def __init__(self, ctx: Context, n: int, ciclo_id: str):
        self.ctx, self.n, self.ciclo_id = ctx, n, ciclo_id
        self.cfg = ctx.cfg

    # --- a implementar
    def plan(self) -> list[str]:
        raise NotImplementedError

    def mutations(self) -> list[str]:
        return []

    def execute(self, r: ExperimentResult) -> None:
        raise NotImplementedError

    # --- comun
    def scale_time(self, base: float, per_msg: float = 2.0, free: int = 10) -> float:
        """Tiempo maximo proporcional a N: `base` mas `per_msg` s por cada mensaje por encima de `free` (10 = escala del plan)."""
        return base + max(0, self.n - free) * float(self.ctx.opt("time_per_msg", per_msg))

    def run(self) -> ExperimentResult:
        r = ExperimentResult(self.name, self.title, self.hypothesis, started=now_iso(),
                             params={"N": self.n, "cicloId": self.ciclo_id, "region": self.cfg.region, "prefijo": self.cfg.prefix})
        if self.mutates:
            self.ctx.confirm(self.mutations())
        try:
            self.execute(r)
            self.ctx.phase("veredicto", "Contabilidad final y criterios PASS/FAIL")
        except Exception as exc:  # noqa: BLE001 - el reporte debe generarse siempre
            r.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}"
            self.ctx.log(f"ERROR en {self.name}: {exc}")
        r.finished = now_iso()
        return r


def fmt_ids(ids, limit: int = 12) -> list:
    ids = sorted(ids)
    return ids if len(ids) <= limit else ids[:limit] + [f"... (+{len(ids) - limit})"]
