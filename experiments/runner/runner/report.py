"""Modelo de resultados (criterios PASS/FAIL/MANUAL/SKIP con evidencia) y generacion de reportes JSON + Markdown."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PASS, FAIL, MANUAL, SKIP = "PASS", "FAIL", "MANUAL", "SKIP"


@dataclass
class Criterion:
    id: str
    title: str
    status: str
    expected: str = ""
    observed: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentResult:
    experiment: str
    title: str
    hypothesis: str
    started: str = ""
    finished: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    criteria: list[Criterion] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)  # series, timeline, etc.
    error: str | None = None

    def add(self, id: str, title: str, ok: bool | None, expected: str = "", observed: str = "", **evidence) -> Criterion:
        status = MANUAL if ok is None else (PASS if ok else FAIL)
        c = Criterion(id, title, status, expected, observed, evidence)
        self.criteria.append(c)
        return c

    def manual(self, id: str, title: str, how: str) -> None:
        self.criteria.append(Criterion(id, title, MANUAL, observed=how))

    @property
    def verdict(self) -> str:
        if self.error or any(c.status == FAIL for c in self.criteria):
            return FAIL
        return PASS if any(c.status == PASS for c in self.criteria) else MANUAL

    def to_dict(self) -> dict:
        d = asdict(self)
        d["verdict"] = self.verdict
        return d


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _md_escape(s: Any) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def to_markdown(r: ExperimentResult) -> str:
    L = [f"# {r.title}", "", f"- Experimento: `{r.experiment}`", f"- Resultado global: **{r.verdict}**",
         f"- Inicio: {r.started}  Fin: {r.finished}", "", f"**Hipotesis.** {r.hypothesis}", ""]
    if r.params:
        L += ["## Parametros", ""] + [f"- `{k}`: {_md_escape(v)}" for k, v in r.params.items()] + [""]
    if r.error:
        L += ["## Error", "", f"```\n{r.error}\n```", ""]
    L += ["## Criterios", "", "| Id | Criterio | Estado | Esperado | Observado |", "|---|---|---|---|---|"]
    for c in r.criteria:
        L.append(f"| {c.id} | {_md_escape(c.title)} | **{c.status}** | {_md_escape(c.expected)} | {_md_escape(c.observed)} |")
    L.append("")
    ev = [c for c in r.criteria if c.evidence]
    if ev:
        L += ["## Evidencia", ""]
        for c in ev:
            L += [f"### {c.id} {c.title}", "", "```json", json.dumps(c.evidence, indent=2, ensure_ascii=False, default=str), "```", ""]
    if r.notes:
        L += ["## Notas", ""] + [f"- {n}" for n in r.notes] + [""]
    return "\n".join(L)


def write_report(r: ExperimentResult, reports_dir: Path, stamp: str | None = None) -> Path:
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    out = Path(reports_dir) / f"{stamp}-{r.experiment}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(r.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "report.md").write_text(to_markdown(r), encoding="utf-8")
    return out
