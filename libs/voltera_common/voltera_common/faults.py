"""Inyeccion de fallos del Exp. 2: FORCE_FAIL=true o FAIL_RATE (0..1). Compatible con los placeholders."""
from __future__ import annotations

import os
import random


class InjectedFault(RuntimeError):
    """Fallo tecnico inyectado (se reintenta por Step Functions / SQS)."""


def maybe_fail(rng: random.Random | None = None, label: str = "") -> None:
    suffix = f" [{label}]" if label else ""
    if os.environ.get("FORCE_FAIL", "false").strip().lower() == "true":
        raise InjectedFault(f"fallo inyectado (FORCE_FAIL){suffix}")
    try:
        rate = float(os.environ.get("FAIL_RATE", "0") or 0)
    except ValueError:
        rate = 0.0
    if rate > 0 and (rng or random).random() < rate:
        raise InjectedFault(f"fallo inyectado (FAIL_RATE){suffix}")
