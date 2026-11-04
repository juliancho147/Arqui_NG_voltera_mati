"""Stubs de las integraciones accesorias de ms_oraculo: API de medidor y API de clima/temporada (R5.8).

Estas integraciones NO son el comportamiento que mide E1: lo que E1 valida es la *decision* de
aceptacion/rechazo del oraculo, que es logica real y determinista (R2.2). Por eso las fuentes
externas se sustituyen por respuestas predefinidas y deterministas:

- `MedidorStub` mantiene el padron de medidores conocidos y, para cada medidor, la referencia
  esperada de generacion (kWh) por fuente. Un `medidorId` fuera del padron es "medidor desconocido".
- `ClimaStub` aporta un factor estacional determinista por (fuente, epoca) que ajusta la referencia
  esperada (p. ej. menos solar en invierno). El ajuste es puro: misma entrada -> mismo factor.

La referencia resultante (`referencia_esperada`) es la base contra la que el oraculo decide si el
valor reportado esta "alterado". Todo aqui es deterministico y sin I/O para que el veredicto sea
reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Padron por defecto: medidor -> {fuente -> referencia base de kWh esperada}.
# Deterministico y predefinido (stub). El orquestador/experimento puede inyectar otro padron.
PADRON_POR_DEFECTO: dict[str, dict[str, int]] = {
    "MED-001": {"solar": 100, "eolica": 80},
    "MED-002": {"solar": 120, "eolica": 90},
    "MED-003": {"solar": 60, "hidro": 150},
    "MED-004": {"solar": 200},
    "MED-005": {"eolica": 110, "hidro": 140},
}


@dataclass(frozen=True)
class MedidorStub:
    """Stub del padron de medidores y su referencia base de generacion por fuente."""

    padron: dict[str, dict[str, int]] = field(default_factory=lambda: dict(PADRON_POR_DEFECTO))

    def es_conocido(self, medidor_id: str) -> bool:
        """True si `medidor_id` esta en el padron (sino es 'medidor desconocido')."""
        return medidor_id in self.padron

    def referencia_base(self, medidor_id: str, fuente: str) -> int | None:
        """Referencia base de kWh esperada para (medidor, fuente), o None si no hay dato."""
        return self.padron.get(medidor_id, {}).get(fuente)


@dataclass(frozen=True)
class ClimaStub:
    """Stub de clima/temporada: factor estacional determinista por (fuente, epoca).

    La epoca se interpreta como `AAAAMM` (p. ej. 202610). El mes selecciona un factor por
    fuente de una tabla predefinida; cualquier mes fuera de rango usa el factor neutro 1.0.
    Es una funcion pura de sus argumentos.
    """

    # fuente -> (factor por mes 1..12). Deterministico y predefinido (stub).
    factores: dict[str, tuple[float, ...]] = field(
        default_factory=lambda: {
            # Mas solar en verano del hemisferio norte (jun-ago), menos en invierno (dic-feb).
            "solar": (0.6, 0.7, 0.9, 1.0, 1.1, 1.2, 1.3, 1.2, 1.0, 0.9, 0.7, 0.6),
            # Mas eolica en invierno.
            "eolica": (1.2, 1.2, 1.1, 1.0, 0.9, 0.8, 0.8, 0.9, 1.0, 1.1, 1.2, 1.2),
            # Hidro relativamente estable.
            "hidro": (1.0, 1.0, 1.1, 1.1, 1.0, 0.9, 0.9, 0.9, 1.0, 1.0, 1.1, 1.0),
        }
    )

    def factor_estacional(self, fuente: str, epoca: int) -> float:
        """Factor estacional determinista para (fuente, epoca=AAAAMM). Neutro (1.0) si no aplica."""
        tabla = self.factores.get(fuente)
        if not tabla:
            return 1.0
        try:
            mes = int(epoca) % 100
        except (TypeError, ValueError):
            return 1.0
        if 1 <= mes <= 12:
            return tabla[mes - 1]
        return 1.0


def referencia_esperada(
    medidor: MedidorStub, clima: ClimaStub, medidor_id: str, fuente: str, epoca: int
) -> int | None:
    """Referencia esperada de kWh = base del medidor ajustada por el factor estacional del clima.

    Devuelve None si no hay referencia base para (medidor, fuente). El resultado es un entero
    determinista (redondeo hacia abajo), apto para comparar contra el valor reportado.
    """
    base = medidor.referencia_base(medidor_id, fuente)
    if base is None:
        return None
    factor = clima.factor_estacional(fuente, epoca)
    return int(base * factor)
