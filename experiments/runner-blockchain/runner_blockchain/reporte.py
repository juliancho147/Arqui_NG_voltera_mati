"""Reporte_Resultados a nivel de corrida: `report.json` + `report.md` (R7.1–R7.5).

El Runner_Experimentos ejecuta uno o varios experimentos (E1/E2/E3) en una sola corrida y
obtiene un `ExperimentResult` por experimento (modelo consolidado en `reporte_modelo.py`).
Este modulo agrega esos resultados en un unico reporte de corrida y lo escribe en un
directorio por corrida con dos archivos:

* `report.json`: documento serializable con la cabecera de la corrida y, por experimento, el
  veredicto PASS/FAIL, los criterios (esperado/observado), las metricas, la evidencia
  on-chain (eventos con `transactionHash`/`blockNumber`/`gasUsed`) y la frontera on/off-chain.
* `report.md`: el mismo contenido en Markdown legible.

Cabecera de corrida (R7.2): `runId`, `inicio`, `fin`, `cantidades` inyectadas por
experimento, `repeticiones`, `contratos` (direcciones desplegadas, de `deployment.json`) y
`herramientas` (Foundry/Anvil).

Evidencia on-chain (R7.3): se consolidan los eventos `Emitido`/`Compra`/`Anclado` observados
por el `Lector_Eventos` (cada uno con su `transactionHash`, `blockNumber` y, cuando aplica,
`gasUsed`), junto con una descripcion explicita de la frontera on-chain/off-chain.

Veredicto reproducible (R7.4): el veredicto de cada experimento sale de su `ExperimentResult`
(derivado de criterios deterministas sobre datasets con semilla fija); el veredicto de la
corrida es PASS solo si todos los experimentos son PASS. No se introduce aqui ninguna fuente
de no-determinismo: los mismos resultados producen el mismo reporte (salvo marcas
temporales, que no afectan el veredicto).

FAIL (R7.5): por cada experimento FAIL se listan las metricas incumplidas con su valor
observado y el umbral esperado (tomados de los criterios en estado FAIL).

Credenciales de Pinata / llave de la plataforma (R3.4): nunca aparecen en el reporte. El
escritor saneа el documento final eliminando cualquier clave sensible por si un experimento
las hubiese arrastrado por error a sus parametros o datos.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .reporte_modelo import FAIL, PASS, ExperimentResult, now_iso

logger = logging.getLogger(__name__)

# Frontera on-chain / off-chain explicita del MVP (R7.3), para dejarla clara en el reporte.
FRONTERA_ON_OFF_CHAIN = {
    "onChain": (
        "Emision de tokens (EnergyToken.emitir -> Emitido), atomicidad de la venta "
        "(MarketEscrow.comprar -> Compra) y anclaje del CID (MarketEscrow.anclar -> Anclado). "
        "Firmado por la plataforma (modelo custodial)."
    ),
    "offChain": (
        "Validacion del oraculo (ms_oraculo), generacion/verificacion del certificado por "
        "contenido (ms_certificado, con Pinata real + fallback local) y la orquestacion/medicion "
        "del runner. Las APIs de medidor y clima son stub."
    ),
}

# Claves sensibles que nunca deben aparecer en el reporte (R3.4). Se comparan sin distinguir
# mayusculas/minusculas contra las claves de cualquier dict anidado del documento.
CLAVES_SENSIBLES = frozenset(
    k.lower()
    for k in (
        "PINATA_JWT",
        "pinataJwt",
        "pinata_jwt",
        "jwt",
        "authorization",
        "apiKey",
        "api_key",
        "apiSecret",
        "api_secret",
        "secret",
        "PLATAFORMA_PRIVATE_KEY",
        "privateKey",
        "private_key",
    )
)

# Eventos on-chain que constituyen la evidencia de la corrida (R6.1, R7.3).
TIPOS_EVIDENCIA = ("Emitido", "Compra", "Anclado")


@dataclass
class RunReport:
    """Reporte de una corrida completa: cabecera + resultados por experimento (R7.1, R7.2)."""

    run_id: str
    started: str
    finished: str
    params: dict[str, Any] = field(default_factory=dict)
    contratos: dict[str, str] = field(default_factory=dict)
    herramientas: dict[str, str] = field(default_factory=dict)
    experiments: list[ExperimentResult] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """Veredicto de la corrida: PASS solo si todos los experimentos son PASS (R7.4)."""
        if not self.experiments:
            return FAIL
        return PASS if all(e.verdict == PASS for e in self.experiments) else FAIL

    def cantidades(self) -> dict[str, Any]:
        """Cantidades de casos inyectados por experimento (R7.2), leidas de sus parametros."""
        out: dict[str, Any] = {}
        for e in self.experiments:
            p = e.params or {}
            det: dict[str, Any] = {}
            for clave in ("invalidas", "validas", "totalAlterados", "comprasPorOferta"):
                if clave in p:
                    det[clave] = p[clave]
            if "porCategoria" in p:
                det["porCategoria"] = p["porCategoria"]
            if "conteoPorForma" in p:
                det["conteoPorForma"] = p["conteoPorForma"]
            out[e.experiment] = det
        return out

    def repeticiones(self) -> dict[str, Any]:
        """Repeticiones por experimento (R7.2); E3 las expone en `repeticiones`."""
        return {
            e.experiment: (e.params or {}).get("repeticiones", 1) for e in self.experiments
        }

    def header(self) -> dict[str, Any]:
        """Cabecera de la corrida (R7.2)."""
        return {
            "runId": self.run_id,
            "inicio": self.started,
            "fin": self.finished,
            "cantidades": self.cantidades(),
            "repeticiones": self.repeticiones(),
            "contratos": dict(self.contratos),
            "herramientas": dict(self.herramientas),
            "params": dict(self.params),
        }

    def evidencia_on_chain(self) -> list[dict[str, Any]]:
        """Evidencia on-chain consolidada de todos los experimentos (R7.3).

        Reune los eventos `Emitido`/`Compra`/`Anclado` presentes en `data["eventos"]` o
        `data["evidencia"]` de cada `ExperimentResult`. Cada evento conserva su
        `transactionHash`, `blockNumber` y `gasUsed`. Se deduplica por
        `(transactionHash, logIndex, tipo)` por si un mismo evento aparece en dos vistas.
        """
        vistos: set[tuple[Any, Any, Any]] = set()
        consolidada: list[dict[str, Any]] = []
        for e in self.experiments:
            for evento in _eventos_de(e):
                if evento.get("tipo") not in TIPOS_EVIDENCIA:
                    continue
                clave = (
                    evento.get("transactionHash"),
                    evento.get("logIndex"),
                    evento.get("tipo"),
                )
                if clave in vistos:
                    continue
                vistos.add(clave)
                consolidada.append(
                    {
                        "experimento": e.experiment,
                        "tipo": evento.get("tipo"),
                        "contrato": evento.get("contrato"),
                        "transactionHash": evento.get("transactionHash"),
                        "blockNumber": evento.get("blockNumber"),
                        "gasUsed": evento.get("gasUsed"),
                        "logIndex": evento.get("logIndex"),
                        "args": evento.get("args", {}),
                    }
                )
        return consolidada

    def metricas_incumplidas(self) -> dict[str, list[dict[str, str]]]:
        """Por cada experimento FAIL, las metricas incumplidas con valor y umbral (R7.5)."""
        out: dict[str, list[dict[str, str]]] = {}
        for e in self.experiments:
            if e.verdict != FAIL:
                continue
            fallidas = [
                {
                    "id": c.id,
                    "criterio": c.title,
                    "observado": c.observed,
                    "umbral": c.expected,
                }
                for c in e.criteria
                if c.status == FAIL
            ]
            if e.error:
                fallidas.append(
                    {"id": "error", "criterio": "error de ejecucion", "observado": e.error, "umbral": ""}
                )
            out[e.experiment] = fallidas
        return out

    def to_dict(self) -> dict[str, Any]:
        """Documento serializable completo de la corrida (base de `report.json`), saneado."""
        doc = {
            "runId": self.run_id,
            "verdict": self.verdict,
            "header": self.header(),
            "fronteraOnOffChain": dict(FRONTERA_ON_OFF_CHAIN),
            "experiments": [_experimento_a_dict(e) for e in self.experiments],
            "evidenciaOnChain": self.evidencia_on_chain(),
            "metricasIncumplidas": self.metricas_incumplidas(),
        }
        return sanear(doc)


def _eventos_de(e: ExperimentResult) -> list[dict[str, Any]]:
    """Extrae la lista de eventos on-chain del `data` de un experimento (si la hay)."""
    data = e.data or {}
    for clave in ("eventos", "evidencia"):
        valor = data.get(clave)
        if isinstance(valor, list):
            return [ev for ev in valor if isinstance(ev, dict)]
    return []


def _experimento_a_dict(e: ExperimentResult) -> dict[str, Any]:
    """Vista por experimento para el reporte: veredicto, criterios, metricas y evidencia."""
    base = e.to_dict()
    metricas = {}
    params = e.params or {}
    if isinstance(params.get("metricas"), dict):
        metricas = params["metricas"]
    base["metricas"] = metricas
    base["eventos"] = _eventos_de(e)
    return base


# ---------------------------------------------------------------------------
# Saneado de credenciales (R3.4)
# ---------------------------------------------------------------------------
def sanear(valor: Any) -> Any:
    """Elimina recursivamente cualquier clave sensible del documento (R3.4).

    Recorre dicts y listas; si una clave coincide (sin distinguir caso) con una clave
    sensible conocida (JWT de Pinata, llave de la plataforma, secretos de API), se descarta
    por completo del documento. No muta la entrada: devuelve una copia saneada.
    """
    if isinstance(valor, dict):
        return {
            k: sanear(v)
            for k, v in valor.items()
            if str(k).lower() not in CLAVES_SENSIBLES
        }
    if isinstance(valor, (list, tuple)):
        return [sanear(v) for v in valor]
    return valor


# ---------------------------------------------------------------------------
# Construccion del reporte de corrida
# ---------------------------------------------------------------------------
def construir_reporte(
    run_id: str,
    experiments: Iterable[ExperimentResult],
    *,
    contratos: dict[str, str] | None = None,
    herramientas: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    started: str | None = None,
    finished: str | None = None,
) -> RunReport:
    """Agrega los `ExperimentResult` de la corrida en un `RunReport` con cabecera (R7.1, R7.2).

    `contratos` y `herramientas` suelen venir de `deployment.json` (ver
    `reporte_desde_deployment`). Si no se dan `started`/`finished`, se derivan de los
    experimentos (primer inicio y ultimo fin) o de la hora actual.
    """
    exps = list(experiments)
    inicio = started or _primer_inicio(exps) or now_iso()
    fin = finished or _ultimo_fin(exps) or now_iso()
    return RunReport(
        run_id=run_id,
        started=inicio,
        finished=fin,
        params=dict(params or {}),
        contratos=dict(contratos or {}),
        herramientas=dict(herramientas or {}),
        experiments=exps,
    )


def reporte_desde_deployment(
    run_id: str,
    experiments: Iterable[ExperimentResult],
    deployment: Any,
    *,
    params: dict[str, Any] | None = None,
    started: str | None = None,
    finished: str | None = None,
) -> RunReport:
    """Construye el `RunReport` tomando contratos/herramientas de un `Deployment` (R7.2).

    `deployment` es un `runner_blockchain.chain.deployment.Deployment` (o cualquier objeto
    con atributos `contratos` y `herramientas`). Asi la cabecera registra las direcciones
    desplegadas y las versiones de Foundry/Anvil sin que el llamador las reparse.
    """
    contratos = dict(getattr(deployment, "contratos", {}) or {})
    herramientas = dict(getattr(deployment, "herramientas", {}) or {})
    parametros = dict(params or {})
    if getattr(deployment, "chain_id", None) is not None:
        parametros.setdefault("chainId", deployment.chain_id)
    if getattr(deployment, "rpc_url", None):
        parametros.setdefault("rpcUrl", deployment.rpc_url)
    return construir_reporte(
        run_id,
        experiments,
        contratos=contratos,
        herramientas=herramientas,
        params=parametros,
        started=started,
        finished=finished,
    )


def _primer_inicio(exps: list[ExperimentResult]) -> str | None:
    marcas = [e.started for e in exps if e.started]
    return min(marcas) if marcas else None


def _ultimo_fin(exps: list[ExperimentResult]) -> str | None:
    marcas = [e.finished for e in exps if e.finished]
    return max(marcas) if marcas else None


# ---------------------------------------------------------------------------
# Serializacion a Markdown
# ---------------------------------------------------------------------------
def _md_escape(s: Any) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def to_markdown(report: RunReport) -> str:
    """Renderiza el `RunReport` a Markdown (cabecera, por experimento, evidencia, frontera)."""
    doc = report.to_dict()  # saneado: usamos sus datos ya sin credenciales (R3.4)
    header = doc["header"]
    L: list[str] = [
        f"# Reporte de corrida `{report.run_id}`",
        "",
        f"- Veredicto de la corrida: **{doc['verdict']}**",
        f"- Inicio: {header['inicio']}  Fin: {header['fin']}",
        "",
        "## Cabecera",
        "",
        f"- `runId`: {header['runId']}",
        f"- `repeticiones`: {_md_escape(header['repeticiones'])}",
        f"- `cantidades`: {_md_escape(header['cantidades'])}",
    ]
    if header["contratos"]:
        L.append("- `contratos`:")
        L += [f"  - `{k}`: {v}" for k, v in header["contratos"].items()]
    if header["herramientas"]:
        L.append("- `herramientas`:")
        L += [f"  - `{k}`: {v}" for k, v in header["herramientas"].items()]
    if header["params"]:
        L.append("- `params`:")
        L += [f"  - `{k}`: {_md_escape(v)}" for k, v in header["params"].items()]
    L.append("")

    # Frontera on/off-chain (R7.3).
    L += [
        "## Frontera on-chain / off-chain",
        "",
        f"- **On-chain:** {doc['fronteraOnOffChain']['onChain']}",
        f"- **Off-chain:** {doc['fronteraOnOffChain']['offChain']}",
        "",
    ]

    # Resumen por experimento (R7.1).
    L += ["## Experimentos", "", "| Experimento | Titulo | Veredicto |", "|---|---|---|"]
    for e in doc["experiments"]:
        L.append(f"| {e['experiment']} | {_md_escape(e['title'])} | **{e['verdict']}** |")
    L.append("")

    for e in doc["experiments"]:
        L += [f"### {e['experiment']} — {_md_escape(e['title'])}", "", f"- Veredicto: **{e['verdict']}**"]
        if e.get("metricas"):
            L.append("- Metricas:")
            L += [f"  - `{k}`: {_md_escape(v)}" for k, v in e["metricas"].items()]
        if e.get("error"):
            L += ["", "```", str(e["error"]), "```"]
        L += ["", "| Id | Criterio | Estado | Esperado | Observado |", "|---|---|---|---|---|"]
        for c in e.get("criteria", []):
            L.append(
                f"| {c['id']} | {_md_escape(c['title'])} | **{c['status']}** | "
                f"{_md_escape(c['expected'])} | {_md_escape(c['observed'])} |"
            )
        L.append("")

    # Metricas incumplidas de los FAIL (R7.5).
    incumplidas = doc["metricasIncumplidas"]
    if incumplidas:
        L += ["## Metricas incumplidas (FAIL)", ""]
        for exp, items in incumplidas.items():
            L.append(f"### {exp}")
            L += ["", "| Id | Criterio | Observado (valor) | Umbral esperado |", "|---|---|---|---|"]
            for it in items:
                L.append(
                    f"| {it['id']} | {_md_escape(it['criterio'])} | "
                    f"{_md_escape(it['observado'])} | {_md_escape(it['umbral'])} |"
                )
            L.append("")

    # Evidencia on-chain (R7.3).
    evidencia = doc["evidenciaOnChain"]
    L += ["## Evidencia on-chain", ""]
    if evidencia:
        L += ["| Experimento | Tipo | Contrato | txHash | blockNumber | gasUsed |", "|---|---|---|---|---|---|"]
        for ev in evidencia:
            L.append(
                f"| {ev['experimento']} | {ev['tipo']} | {ev.get('contrato', '')} | "
                f"{ev.get('transactionHash', '')} | {ev.get('blockNumber', '')} | "
                f"{ev.get('gasUsed', '')} |"
            )
    else:
        L.append("_Sin eventos on-chain observados en esta corrida._")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Escritura de report.json + report.md
# ---------------------------------------------------------------------------
def escribir_reporte(
    report: RunReport,
    reports_dir: Path | str,
    *,
    stamp: str | None = None,
) -> Path:
    """Escribe `report.json` y `report.md` de la corrida en un directorio por corrida (R7.1).

    El directorio es `reports_dir/<stamp>-<runId>`; `stamp` por defecto es la hora local. El
    JSON se saneа de credenciales (R3.4) via `RunReport.to_dict`. Devuelve el directorio.
    """
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    out = Path(reports_dir) / f"{stamp}-{report.run_id}"
    out.mkdir(parents=True, exist_ok=True)

    doc = report.to_dict()
    (out / "report.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (out / "report.md").write_text(to_markdown(report), encoding="utf-8")
    logger.info(
        "Reporte_Resultados de la corrida %s escrito en %s (veredicto=%s)",
        report.run_id,
        out,
        report.verdict,
    )
    return out


__all__ = [
    "RunReport",
    "FRONTERA_ON_OFF_CHAIN",
    "CLAVES_SENSIBLES",
    "sanear",
    "construir_reporte",
    "reporte_desde_deployment",
    "to_markdown",
    "escribir_reporte",
]
