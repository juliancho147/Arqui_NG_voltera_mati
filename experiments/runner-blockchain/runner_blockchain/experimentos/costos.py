"""Gas -> costo y decision de arquitectura (R4.7, R7.3).

Convierte el gas medido on-chain en costo monetario a un precio de gas declarado y a un
precio de ETH declarado, y deriva el costo por kWh tokenizado. A partir de ese costo propone
cambios de diseno (emision por lotes, anclaje por cierre mensual) con su ahorro estimado.

Todos los supuestos son PARAMETROS explicitos (no se ocultan): precio de gas en gwei y precio
de ETH en USD. Asi el lector puede recalcular con otros valores. El gas por operacion se toma
de la evidencia real de los experimentos (recibos on-chain).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GWEI = 1e-9  # 1 gwei = 1e-9 ETH


@dataclass
class SupuestosCosto:
    """Supuestos declarados para la conversion gas -> dinero."""
    gas_price_gwei: float = 20.0   # precio de gas declarado (gwei)
    eth_usd: float = 3000.0        # precio de ETH declarado (USD)
    kwh_por_emision: int = 100     # kWh que tokeniza una emision individual (supuesto)

    def costo_usd(self, gas: int) -> float:
        """Costo en USD de consumir `gas` a los precios declarados."""
        eth = gas * self.gas_price_gwei * GWEI
        return eth * self.eth_usd


def analizar(gas_por_op: dict[str, int], sup: SupuestosCosto | None = None) -> dict[str, Any]:
    """Convierte gas por operacion en costo y deriva costo por kWh + recomendaciones.

    `gas_por_op` mapea nombre de operacion -> gas (p.ej. {"emitir":248388,"publicar":...,
    "comprar":277526,"anclar":...}). Devuelve un dict con costos y decisiones de arquitectura.
    """
    sup = sup or SupuestosCosto()
    costos = {op: {"gas": g, "usd": round(sup.costo_usd(g), 6)} for op, g in gas_por_op.items()}

    gas_emitir = gas_por_op.get("emitir", 0)
    costo_emitir = sup.costo_usd(gas_emitir)
    costo_por_kwh = (costo_emitir / sup.kwh_por_emision) if sup.kwh_por_emision else 0.0

    # Decision 1: emision por lotes. Emitir N lecturas en una sola tx comparte el costo base
    # (~21000 de gas de la tx) y reduce overhead por emision. Estimacion conservadora: el
    # costo marginal por emision adicional baja ~ (gas_emitir - 21000); el ahorro por lote de
    # L es ~ (L-1) * 21000 de gas.
    base_tx = 21000
    def ahorro_lote(L: int) -> dict[str, Any]:
        gas_individual = L * gas_emitir
        gas_lote = base_tx + L * max(0, gas_emitir - base_tx)
        ahorro_gas = max(0, gas_individual - gas_lote)
        return {"lote": L, "gasIndividual": gas_individual, "gasLote": gas_lote,
                "ahorroGas": ahorro_gas, "ahorroUsd": round(sup.costo_usd(ahorro_gas), 4),
                "ahorroPct": round(100 * ahorro_gas / gas_individual, 1) if gas_individual else 0.0}

    # Decision 2: anclaje por cierre mensual. En vez de anclar 1 CID por compra, anclar un
    # unico CID (raiz de un arbol de Merkle / CID de un indice) por periodo. Ahorro ~ (M-1)
    # anclajes por cada M compras del mes.
    gas_anclar = gas_por_op.get("anclar", 0)
    def ahorro_anclaje(M: int) -> dict[str, Any]:
        gas_individual = M * gas_anclar
        gas_mensual = gas_anclar  # un solo anclaje agregado
        ahorro_gas = max(0, gas_individual - gas_mensual)
        return {"comprasMes": M, "gasIndividual": gas_individual, "gasMensual": gas_mensual,
                "ahorroGas": ahorro_gas, "ahorroUsd": round(sup.costo_usd(ahorro_gas), 4),
                "ahorroPct": round(100 * ahorro_gas / gas_individual, 1) if gas_individual else 0.0}

    return {
        "supuestos": {"gasPriceGwei": sup.gas_price_gwei, "ethUsd": sup.eth_usd,
                      "kwhPorEmision": sup.kwh_por_emision},
        "costoPorOperacion": costos,
        "costoEmisionUsd": round(costo_emitir, 6),
        "costoPorKwhUsd": round(costo_por_kwh, 8),
        "decisiones": {
            "emisionPorLotes": [ahorro_lote(L) for L in (10, 50, 100)],
            "anclajePorCierreMensual": [ahorro_anclaje(M) for M in (30, 100, 1000)],
        },
        "recomendacion": (
            "A este costo por kWh, la emision 1-tx-por-lectura y el anclaje 1-CID-por-compra "
            "dominan el gasto. Recomendacion: (1) EMISION POR LOTES — agregar lecturas validadas "
            "de un periodo en una sola tx de emision por (fuente,epoca), amortizando el costo base "
            "de transaccion; (2) ANCLAJE POR CIERRE MENSUAL — anclar una sola raiz (Merkle) de todos "
            "los certificados del mes en vez de un CID por compra, manteniendo verificabilidad por "
            "inclusion. Ambos reducen el gas total sin perder la garantia on-chain."
        ),
    }
