"""Agrega automaticamente una seccion a experiments/RESULTADOS.md con la plantilla del final del archivo."""
from __future__ import annotations

import re
from pathlib import Path

from .config import ROOT
from .report import FAIL, MANUAL, PASS, ExperimentResult

RESULTADOS_PATH = ROOT / "experiments" / "RESULTADOS.md"
MARKER = "## Plantilla para pruebas siguientes"


def next_number(text: str) -> int:
    nums = [int(m) for m in re.findall(r"^## Prueba (\d+)", text, flags=re.M)]
    return (max(nums) if nums else 0) + 1


def _cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _medidas(res: ExperimentResult) -> list[str]:
    d = res.data
    L: list[str] = []
    serie = d.get("serie")
    if serie:  # exp1
        rows = [s for s in serie if s.get("fase") != "scale-down"]
        step = max(1, len(rows) // 12)
        pick = rows[::step]
        if rows and rows[-1] not in pick:
            pick.append(rows[-1])
        L += ["", "| Instante | Replicas | Lag | Terminadas |", "|---|---|---|---|"]
        L += [f"| {s['t']} s | {s.get('replicas')} | {s.get('lag')} | {s.get('terminadas')}/{res.params.get('N')} |" for s in pick]
    for key in ("serieA", "serieB"):
        sr = d.get(key)
        if sr:
            step = max(1, len(sr) // 12)
            pick = sr[::step] + ([sr[-1]] if sr[-1] not in sr[::step] else [])
            L += ["", f"Caso {key[-1]}:", "| Instante | Emitidas | Cola tx | DLQ tx | Cola comp | DLQ comp |", "|---|---|---|---|---|---|"]
            L += [f"| {s['t']} s | {s['emitidas']} | {s['colaTx']} | {s['dlqTx']} | {s['colaComp']} | {s['dlqComp']} |" for s in pick]
    sf = d.get("serieFallos")
    if sf:  # exp2 unificado
        step = max(1, len(sf) // 14)
        pick = sf[::step] + ([sf[-1]] if sf[-1] not in sf[::step] else [])
        L += ["", "| Instante | Fase | Emitidas | Enviadas | Pods | Cola tx | DLQ tx | Cola comp | DLQ comp |", "|---|---|---|---|---|---|---|---|---|"]
        L += [f"| {s['t']} s | {s.get('fase')} | {s['emitidas']} | {s.get('enviadas')} | {s.get('listas')} | {s['colaTx']} | {s['dlqTx']} | {s['colaComp']} | {s['dlqComp']} |" for s in pick]
        L += ["", "| Criterio | Esperado | Observado |", "|---|---|---|"]
        L += [f"| {c.id} {_cell(c.title)} | {_cell(c.expected)} | {_cell(c.observed)} |" for c in res.criteria if c.status != MANUAL]
    if not L:
        L = ["", "| Criterio | Esperado | Observado |", "|---|---|---|"]
        L += [f"| {c.id} {_cell(c.title)} | {_cell(c.expected)} | {_cell(c.observed)} |" for c in res.criteria if c.status != MANUAL]
    return L


def build_section(res: ExperimentResult, number: int, report_dir: Path | str, variante: str = "demo en pantalla") -> str:
    cnt = {s: sum(1 for c in res.criteria if c.status == s) for s in (PASS, FAIL, MANUAL)}
    p = {k: v for k, v in res.params.items() if k not in ("region", "prefijo")}
    fails = [c for c in res.criteria if c.status == FAIL]
    L = [f"## Prueba {number} — {res.title} ({variante})",
         f"- **Fecha/hora:** {res.started} → {res.finished} · **Ciclo:** `{res.params.get('cicloId', '')}` · **Reporte:** `reports/{Path(report_dir).name}/`",
         f"- **Parametros:** " + ", ".join(f"{k}={v}" for k, v in p.items()),
         f"- **Resultado global:** **{res.verdict}** ({cnt[PASS]} PASS, {cnt[FAIL]} FAIL, {cnt[MANUAL]} MANUAL)",
         "- **Medidas:**"]
    L += _medidas(res)
    L += ["", "- **Hallazgos / observaciones:**"]
    L += [f"  - {c.id} FAIL: {c.title} — esperado {c.expected}; observado {c.observed}" for c in fails] or ["  - Todos los criterios automaticos cumplidos."]
    if res.error:
        L.append(f"  - ERROR del runner: {res.error.splitlines()[0]}")
    L += [f"  - {n}" for n in res.notes]
    L += ["- **Acciones derivadas:** (completar tras revisar la grabacion)", ""]
    return "\n".join(L)


def append_section(res: ExperimentResult, report_dir: Path | str, path: Path | str = RESULTADOS_PATH, variante: str = "demo en pantalla") -> int:
    """Inserta la seccion antes de la plantilla final (o al final si no existe). Devuelve el numero de prueba."""
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    n = next_number(text)
    section = build_section(res, n, report_dir, variante)
    if MARKER in text:
        head, tail = text.split(MARKER, 1)
        head = head.rstrip()
        if head.endswith("---"):
            head = head[:-3].rstrip()
        text = f"{head}\n\n{section}\n---\n{MARKER}{tail}"
    else:
        text = text.rstrip() + ("\n\n" if text else "") + section
    path.write_text(text, encoding="utf-8")
    return n
