"""Experimentos del MVP de validacion blockchain local (E1, E2, E3).

Cada experimento genera sus casos con una semilla fija (derivada de `runId`/parametros para
reproducibilidad, R7.4), inyecta los casos a los microservicios reales, completa el flujo
on-chain, recolecta evidencia via el `Lector_Eventos` y produce un `ExperimentResult` con el
veredicto PASS/FAIL y las metricas medidas.

* E1 — Integridad del Oracle (`e1.py`): 200 inválidas (>=50 por categoria) + 200 válidas;
  tasa de rechazo 100%, 0 `Emitido` por inválidas, p95 de latencia <= 10 s (R2).
"""

from .e1 import (
    CasoE1,
    DatasetE1,
    E1Error,
    ejecutar_e1,
    generar_dataset_e1,
)

__all__ = [
    "CasoE1",
    "DatasetE1",
    "E1Error",
    "ejecutar_e1",
    "generar_dataset_e1",
]
