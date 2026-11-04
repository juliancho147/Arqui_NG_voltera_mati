"""Modelo canonico de resultados por experimento (`ExperimentResult`/`Criterion`).

Unico modulo del paquete `runner_blockchain` con el modelo de resultados de los
experimentos. Replica el patron de `experiments/runner/runner/report.py` del runner
existente (criterios PASS/FAIL/MANUAL/SKIP con evidencia + veredicto agregado), pero vive
dentro de este paquete para que los experimentos E1/E2/E3 y el `Reporte_Resultados`
(`reporte.py`) construyan y escriban su reporte sin depender del otro paquete orientado a
AWS.

Consolida los tres modulos casi duplicados que se crearon durante la implementacion en
paralelo de E1/E2/E3 (`reporte_model.py`, `experimentos/modelo_resultado.py` y la version
anterior de este archivo). El esquema de campos es equivalente al del runner existente.

`ExperimentResult`:
  * `experiment`/`title`/`hypothesis`: identificacion del experimento.
  * `started`/`finished`: marcas temporales ISO-8601.
  * `params`: parametros de la corrida (cantidades, semilla, repeticiones, umbrales...).
  * `criteria`: lista de `Criterion` (cada criterio cuantitativo PASS/FAIL del experimento);
    un FAIL registra la metrica incumplida con su valor observado y el umbral esperado
    (R7.5).
  * `data`: datos auxiliares serializables (series, latencias, evidencia on-chain...).
  * `.verdict`: PASS/FAIL agregado (R7.4).

Un experimento es PASS si y solo si no hay error y ningun criterio es FAIL (habiendo al
menos un criterio PASS); si hay error o algun criterio FAIL es FAIL; si solo hay criterios
MANUAL/SKIP queda en MANUAL (R7.4, R7.5).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PASS, FAIL, MANUAL, SKIP = "PASS", "FAIL", "MANUAL", "SKIP"


@dataclass
class Criterion:
    """Un criterio cuantitativo del experimento, con esperado/observado y evidencia.

    `status` es PASS/FAIL/MANUAL/SKIP; `expected`/`observed` describen el umbral esperado y
    el valor medido (para que un FAIL registre la metrica incumplida, R7.5); `evidence`
    guarda datos adicionales serializables (p. ej. eventos on-chain con txHash/blockNumber).
    """

    id: str
    title: str
    status: str
    expected: str = ""
    observed: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentResult:
    """Resultado de un experimento: metadatos, criterios, metricas y evidencia on-chain."""

    experiment: str
    title: str
    hypothesis: str
    started: str = ""
    finished: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    criteria: list[Criterion] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)  # series, timeline, evidencia, etc.
    error: str | None = None

    def add(
        self,
        id: str,
        title: str,
        ok: bool | None,
        expected: str = "",
        observed: str = "",
        **evidence: Any,
    ) -> Criterion:
        """Agrega un criterio: `ok=True` -> PASS, `ok=False` -> FAIL, `ok=None` -> MANUAL."""
        status = MANUAL if ok is None else (PASS if ok else FAIL)
        c = Criterion(id, title, status, expected, observed, evidence)
        self.criteria.append(c)
        return c

    def manual(self, id: str, title: str, how: str) -> None:
        """Agrega un criterio que requiere verificacion manual."""
        self.criteria.append(Criterion(id, title, MANUAL, observed=how))

    @property
    def verdict(self) -> str:
        """Veredicto agregado: FAIL si hay error o algun criterio FAIL; si no, PASS."""
        if self.error or any(c.status == FAIL for c in self.criteria):
            return FAIL
        return PASS if any(c.status == PASS for c in self.criteria) else MANUAL

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict
        return d


def now_iso() -> str:
    """Marca temporal ISO-8601 local con offset (para `started`/`finished`)."""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _md_escape(s: Any) -> str:
    """Escapa `|` y saltos de linea para no romper las tablas Markdown."""
    return str(s).replace("|", "\\|").replace("\n", " ")


def to_markdown(r: ExperimentResult) -> str:
    """Renderiza un `ExperimentResult` individual a Markdown (reporte por experimento)."""
    L = [
        f"# {r.title}",
        "",
        f"- Experimento: `{r.experiment}`",
        f"- Resultado global: **{r.verdict}**",
        f"- Inicio: {r.started}  Fin: {r.finished}",
        "",
        f"**Hipotesis.** {r.hypothesis}",
        "",
    ]
    if r.params:
        L += ["## Parametros", ""] + [f"- `{k}`: {_md_escape(v)}" for k, v in r.params.items()] + [""]
    if r.error:
        L += ["## Error", "", f"```\n{r.error}\n```", ""]
    L += ["## Criterios", "", "| Id | Criterio | Estado | Esperado | Observado |", "|---|---|---|---|---|"]
    for c in r.criteria:
        L.append(
            f"| {c.id} | {_md_escape(c.title)} | **{c.status}** | {_md_escape(c.expected)} | {_md_escape(c.observed)} |"
        )
    L.append("")
    ev = [c for c in r.criteria if c.evidence]
    if ev:
        L += ["## Evidencia", ""]
        for c in ev:
            L += [
                f"### {c.id} {c.title}",
                "",
                "```json",
                json.dumps(c.evidence, indent=2, ensure_ascii=False, default=str),
                "```",
                "",
            ]
    if r.notes:
        L += ["## Notas", ""] + [f"- {n}" for n in r.notes] + [""]
    return "\n".join(L)


def write_report(r: ExperimentResult, reports_dir: Path, stamp: str | None = None) -> Path:
    """Escribe `report.json` + `report.md` de un unico experimento en `reports_dir`."""
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    out = Path(reports_dir) / f"{stamp}-{r.experiment}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(r.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (out / "report.md").write_text(to_markdown(r), encoding="utf-8")
    return out


__all__ = [
    "PASS",
    "FAIL",
    "MANUAL",
    "SKIP",
    "Criterion",
    "ExperimentResult",
    "now_iso",
    "to_markdown",
    "write_report",
]
