"""E3 — Control sin escrow: demuestra la doble venta cuando falta la guarda de atomicidad.

Contraste cientifico de E3: aisla la variable "proteccion del escrow". El `MarketEscrow`
real aplica `if (o.estado != Activa) revert OfertaNoDisponible` ANTES de mover tokens, lo
que garantiza exactamente una venta por oferta bajo concurrencia. Este control replica el
flujo de compra SIN esa guarda (un "mercado ingenuo"): todas las compras concurrentes que
leen la oferta como Activa proceden, produciendo MULTIPLES ventas de la misma oferta.

Se implementa off-chain (en memoria) a proposito: NO se despliega un contrato vulnerable en
la cadena. Modela un escrow sin la verificacion-antes-de-efecto con una ventana de carrera
realista (read-check-write sin lock), y procesa k compras concurrentes sobre la misma oferta.
El resultado esperado del control es k ventas (doble venta), lo que evidencia POR CONTRASTE
que la guarda del contrato real es la que evita el fraude.

Reporta, ademas, para el experimento REAL: cuantas de las k compras fueron rechazadas y por
que motivo (OfertaNoDisponible), que es la otra cara de "exactamente una venta".
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from ..reporte_modelo import ExperimentResult, now_iso


@dataclass
class _MercadoIngenuo:
    """Escrow SIN guarda de atomicidad: read-check-write con ventana de carrera."""

    activa: bool = True
    ventas: int = 0
    _retardo: float = 0.002  # agranda la ventana de carrera para evidenciar el defecto

    def comprar_sin_guarda(self) -> bool:
        # Lee el estado (como haria un contrato), pero NO re-verifica atomicamente antes de
        # escribir: justo la ausencia de `if estado != Activa revert` del contrato real.
        disponible = self.activa
        time.sleep(self._retardo)  # ventana donde otros hilos tambien ven Activa
        if disponible:
            self.ventas += 1       # efecto SIN proteccion -> multiples ventas
            self.activa = False
            return True
        return False


def ejecutar_control(run_id: str = "RUN-E3-CONTROL", *, compras: int = 10) -> ExperimentResult:
    """Dispara `compras` concurrentes sobre un mercado SIN escrow; espera doble venta."""
    r = ExperimentResult(
        experiment="E3-CONTROL",
        title="E3 control — mercado SIN escrow (demuestra doble venta)",
        hypothesis="Sin la guarda de atomicidad del escrow, N compras concurrentes producen N ventas.",
        started=now_iso(),
    )
    mercado = _MercadoIngenuo()
    with ThreadPoolExecutor(max_workers=compras) as pool:
        resultados = list(pool.map(lambda _: mercado.comprar_sin_guarda(), range(compras)))
    ventas = sum(1 for x in resultados if x)

    # El control es "exitoso" (demuestra el defecto) si hubo MAS de una venta.
    r.add("CTRL-1", "Mercado sin escrow produce doble venta bajo concurrencia",
          ok=(ventas > 1),
          expected=">1 venta (defecto esperado sin la guarda del contrato)",
          observed=f"{ventas} ventas de la misma oferta con {compras} compras concurrentes")
    r.data = {"compras": compras, "ventasSinEscrow": ventas,
              "contraste": "el MarketEscrow real limita esto a exactamente 1 (ver E3)"}
    r.notes.append("Control off-chain: NO se despliega un contrato vulnerable; aisla la guarda de atomicidad.")
    r.finished = now_iso()
    return r


def resumen_rechazos(resultados_compra: list[dict[str, Any]]) -> dict[str, Any]:
    """Resume, para el E3 REAL, las compras rechazadas por motivo (la cara B de 1 venta/oferta).

    `resultados_compra` es la lista de desenlaces que devuelve `ms_compra` en modo concurrente
    (cada item con `exito` y `estado`). Agrupa los rechazos por estado/motivo.
    """
    confirmadas = sum(1 for x in resultados_compra if x.get("exito"))
    rechazadas = [x for x in resultados_compra if not x.get("exito")]
    por_motivo: dict[str, int] = {}
    for x in rechazadas:
        motivo = x.get("estado") or "desconocido"
        por_motivo[motivo] = por_motivo.get(motivo, 0) + 1
    return {
        "total": len(resultados_compra),
        "confirmadas": confirmadas,
        "rechazadas": len(rechazadas),
        "rechazadasPorMotivo": por_motivo,
    }
